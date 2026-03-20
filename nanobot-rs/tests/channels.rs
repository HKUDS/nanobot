use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use axum::extract::State;
use axum::routing::post;
use axum::{Json, Router};
use nanobot_rs::bus::{MessageBus, OutboundMessage};
use nanobot_rs::channels::{Channel, ChannelManager, TelegramChannel};
use nanobot_rs::config::{Config, TelegramConfig};
use serde_json::{Value, json};
use tokio::net::TcpListener;
use tokio::sync::Mutex;

#[derive(Clone, Default)]
struct TelegramState {
    updates: Arc<Mutex<Vec<Value>>>,
    sent: Arc<Mutex<Vec<Value>>>,
}

async fn get_updates(
    State(state): State<TelegramState>,
    Json(_payload): Json<Value>,
) -> Json<Value> {
    let updates = state.updates.lock().await.clone();
    Json(json!({"ok": true, "result": updates}))
}

async fn send_message(
    State(state): State<TelegramState>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    state.sent.lock().await.push(payload);
    Json(json!({"ok": true, "result": {"message_id": 1}}))
}

async fn start_server(state: TelegramState) -> SocketAddr {
    let app = Router::new()
        .route("/bottoken/getUpdates", post(get_updates))
        .route("/bottoken/sendMessage", post(send_message))
        .with_state(state);
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let addr = listener.local_addr().expect("local addr");
    tokio::spawn(async move {
        axum::serve(listener, app).await.expect("serve");
    });
    addr
}

#[tokio::test]
async fn channel_manager_only_enables_configured_channels() {
    let config = Config::default();
    let manager = ChannelManager::new(&config, MessageBus::new(32));
    assert_eq!(manager.enabled_channels(), vec!["cli".to_string()]);
}

#[tokio::test]
async fn telegram_channel_receives_allowed_text_messages() {
    let state = TelegramState {
        updates: Arc::new(Mutex::new(vec![json!({
            "update_id": 1,
            "message": {
                "message_id": 10,
                "text": "hello",
                "chat": {"id": 99},
                "from": {"id": 42, "username": "alice"}
            }
        })])),
        sent: Arc::new(Mutex::new(Vec::new())),
    };
    let addr = start_server(state.clone()).await;
    let bus = MessageBus::new(32);
    let channel = TelegramChannel::new(
        TelegramConfig {
            enabled: true,
            token: "token".to_string(),
            allow_from: vec!["42".to_string()],
            api_base: format!("http://{addr}"),
        },
        bus.clone(),
    );
    let handle = tokio::spawn({
        let channel = channel;
        async move { channel.start().await.expect("telegram start") }
    });
    let inbound = tokio::time::timeout(std::time::Duration::from_secs(2), bus.consume_inbound())
        .await
        .expect("timely inbound")
        .expect("message");
    assert_eq!(inbound.channel, "telegram");
    assert_eq!(inbound.content, "hello");
    handle.abort();
}

#[tokio::test]
async fn telegram_channel_sends_outbound_text() {
    let state = TelegramState::default();
    let addr = start_server(state.clone()).await;
    let bus = MessageBus::new(32);
    let channel = TelegramChannel::new(
        TelegramConfig {
            enabled: true,
            token: "token".to_string(),
            allow_from: vec!["*".to_string()],
            api_base: format!("http://{addr}"),
        },
        bus,
    );
    channel
        .send(OutboundMessage {
            channel: "telegram".to_string(),
            chat_id: "123".to_string(),
            content: "hello".to_string(),
            metadata: HashMap::new(),
        })
        .await
        .expect("send");
    let sent = state.sent.lock().await;
    assert_eq!(sent.len(), 1);
    assert_eq!(sent[0].get("text").and_then(Value::as_str), Some("hello"));
}
