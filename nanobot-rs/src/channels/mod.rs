use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::Result;
use async_trait::async_trait;
use serde_json::{Value, json};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::bus::{InboundMessage, MessageBus, OutboundMessage};
use crate::config::{Config, TelegramConfig};

#[async_trait]
pub trait Channel: Send + Sync {
    fn name(&self) -> &'static str;
    async fn start(&self) -> Result<()>;
    async fn stop(&self) -> Result<()>;
    async fn send(&self, msg: OutboundMessage) -> Result<()>;
}

#[derive(Default)]
pub struct CliChannel;

#[async_trait]
impl Channel for CliChannel {
    fn name(&self) -> &'static str {
        "cli"
    }

    async fn start(&self) -> Result<()> {
        Ok(())
    }

    async fn stop(&self) -> Result<()> {
        Ok(())
    }

    async fn send(&self, _msg: OutboundMessage) -> Result<()> {
        Ok(())
    }
}

pub struct TelegramChannel {
    config: TelegramConfig,
    bus: MessageBus,
    client: reqwest::Client,
    running: AtomicBool,
    offset: Arc<Mutex<i64>>,
}

impl TelegramChannel {
    pub fn new(config: TelegramConfig, bus: MessageBus) -> Self {
        Self {
            config,
            bus,
            client: reqwest::Client::new(),
            running: AtomicBool::new(false),
            offset: Arc::new(Mutex::new(0)),
        }
    }

    fn is_allowed(&self, sender_id: &str, username: Option<&str>) -> bool {
        if self.config.allow_from.is_empty() {
            return false;
        }
        if self.config.allow_from.iter().any(|value| value == "*") {
            return true;
        }
        self.config.allow_from.iter().any(|allowed| {
            allowed == sender_id
                || username
                    .map(|username| allowed == username)
                    .unwrap_or(false)
        })
    }

    fn base_url(&self, method: &str) -> String {
        format!(
            "{}/bot{}/{}",
            self.config.api_base.trim_end_matches('/'),
            self.config.token,
            method
        )
    }
}

#[async_trait]
impl Channel for TelegramChannel {
    fn name(&self) -> &'static str {
        "telegram"
    }

    async fn start(&self) -> Result<()> {
        self.running.store(true, Ordering::SeqCst);
        while self.running.load(Ordering::SeqCst) {
            let offset = *self.offset.lock().await;
            let response = self
                .client
                .post(self.base_url("getUpdates"))
                .json(&json!({
                    "timeout": 20,
                    "offset": offset,
                    "allowed_updates": ["message"]
                }))
                .send()
                .await;
            let response = match response {
                Ok(response) => response,
                Err(error) => {
                    warn!("telegram polling failed: {error}");
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    continue;
                }
            };
            let payload: Value = match response.json().await {
                Ok(value) => value,
                Err(error) => {
                    warn!("telegram returned invalid payload: {error}");
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    continue;
                }
            };
            let Some(results) = payload.get("result").and_then(Value::as_array) else {
                continue;
            };
            for update in results {
                if let Some(update_id) = update.get("update_id").and_then(Value::as_i64) {
                    *self.offset.lock().await = update_id + 1;
                }
                let Some(message) = update.get("message") else {
                    continue;
                };
                let chat_id = message
                    .get("chat")
                    .and_then(|chat| chat.get("id"))
                    .and_then(Value::as_i64)
                    .map(|id| id.to_string());
                let sender_id = message
                    .get("from")
                    .and_then(|from| from.get("id"))
                    .and_then(Value::as_i64)
                    .map(|id| id.to_string());
                let username = message
                    .get("from")
                    .and_then(|from| from.get("username"))
                    .and_then(Value::as_str);
                let text = message.get("text").and_then(Value::as_str);
                if let (Some(chat_id), Some(sender_id), Some(text)) = (chat_id, sender_id, text) {
                    if !self.is_allowed(&sender_id, username) {
                        continue;
                    }
                    let mut metadata = HashMap::new();
                    if let Some(message_id) = message.get("message_id").and_then(Value::as_i64) {
                        metadata.insert("message_id".to_string(), json!(message_id.to_string()));
                    }
                    self.bus
                        .publish_inbound(InboundMessage {
                            channel: "telegram".to_string(),
                            sender_id,
                            chat_id,
                            content: text.to_string(),
                            timestamp: chrono::Utc::now(),
                            metadata,
                            session_key_override: None,
                        })
                        .await?;
                }
            }
        }
        Ok(())
    }

    async fn stop(&self) -> Result<()> {
        self.running.store(false, Ordering::SeqCst);
        Ok(())
    }

    async fn send(&self, msg: OutboundMessage) -> Result<()> {
        for chunk in split_telegram_message(&msg.content) {
            self.client
                .post(self.base_url("sendMessage"))
                .json(&json!({
                    "chat_id": msg.chat_id,
                    "text": chunk,
                }))
                .send()
                .await?
                .error_for_status()?;
        }
        Ok(())
    }
}

fn split_telegram_message(content: &str) -> Vec<String> {
    const LIMIT: usize = 4000;
    if content.chars().count() <= LIMIT {
        return vec![content.to_string()];
    }
    let mut chunks = Vec::new();
    let mut current = String::new();
    for ch in content.chars() {
        current.push(ch);
        if current.chars().count() >= LIMIT {
            chunks.push(current);
            current = String::new();
        }
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    chunks
}

pub struct ChannelManager {
    bus: MessageBus,
    channels: HashMap<String, Arc<dyn Channel>>,
    dispatch_handle: Mutex<Option<JoinHandle<()>>>,
    start_handles: Mutex<Vec<JoinHandle<()>>>,
}

impl ChannelManager {
    pub fn new(config: &Config, bus: MessageBus) -> Self {
        let mut channels: HashMap<String, Arc<dyn Channel>> = HashMap::new();
        channels.insert("cli".to_string(), Arc::new(CliChannel));
        if config.channels.telegram.enabled {
            channels.insert(
                "telegram".to_string(),
                Arc::new(TelegramChannel::new(
                    config.channels.telegram.clone(),
                    bus.clone(),
                )),
            );
        }
        Self {
            bus,
            channels,
            dispatch_handle: Mutex::new(None),
            start_handles: Mutex::new(Vec::new()),
        }
    }

    pub fn enabled_channels(&self) -> Vec<String> {
        self.channels.keys().cloned().collect()
    }

    pub async fn start_all(&self) {
        let channels = self.channels.values().cloned().collect::<Vec<_>>();
        let mut handles = self.start_handles.lock().await;
        for channel in channels {
            let name = channel.name();
            handles.push(tokio::spawn(async move {
                if let Err(error) = channel.start().await {
                    error!("channel {name} failed: {error}");
                }
            }));
        }
        let bus = self.bus.clone();
        let channels = self.channels.clone();
        *self.dispatch_handle.lock().await = Some(tokio::spawn(async move {
            loop {
                let Some(msg) = bus.consume_outbound().await else {
                    continue;
                };
                if let Some(channel) = channels.get(&msg.channel) {
                    if let Err(error) = channel.send(msg).await {
                        error!("failed to send outbound message: {error}");
                    }
                } else {
                    warn!("unknown channel: {}", msg.channel);
                }
            }
        }));
        info!("channels started: {:?}", self.enabled_channels());
    }

    pub async fn stop_all(&self) {
        for channel in self.channels.values() {
            let _ = channel.stop().await;
        }
        if let Some(handle) = self.dispatch_handle.lock().await.take() {
            handle.abort();
        }
        let mut handles = self.start_handles.lock().await;
        for handle in handles.drain(..) {
            handle.abort();
        }
    }
}
