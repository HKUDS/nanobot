use std::collections::HashMap;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tokio::sync::{Mutex, mpsc};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InboundMessage {
    pub channel: String,
    pub sender_id: String,
    pub chat_id: String,
    pub content: String,
    #[serde(default = "Utc::now")]
    pub timestamp: DateTime<Utc>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub session_key_override: Option<String>,
}

impl InboundMessage {
    pub fn session_key(&self) -> String {
        self.session_key_override
            .clone()
            .unwrap_or_else(|| format!("{}:{}", self.channel, self.chat_id))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutboundMessage {
    pub channel: String,
    pub chat_id: String,
    pub content: String,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Clone)]
pub struct MessageBus {
    inbound_tx: mpsc::Sender<InboundMessage>,
    inbound_rx: Arc<Mutex<mpsc::Receiver<InboundMessage>>>,
    outbound_tx: mpsc::Sender<OutboundMessage>,
    outbound_rx: Arc<Mutex<mpsc::Receiver<OutboundMessage>>>,
}

impl MessageBus {
    pub fn new(buffer: usize) -> Self {
        let (inbound_tx, inbound_rx) = mpsc::channel(buffer);
        let (outbound_tx, outbound_rx) = mpsc::channel(buffer);
        Self {
            inbound_tx,
            inbound_rx: Arc::new(Mutex::new(inbound_rx)),
            outbound_tx,
            outbound_rx: Arc::new(Mutex::new(outbound_rx)),
        }
    }

    pub async fn publish_inbound(&self, msg: InboundMessage) -> anyhow::Result<()> {
        self.inbound_tx.send(msg).await?;
        Ok(())
    }

    pub async fn consume_inbound(&self) -> Option<InboundMessage> {
        self.inbound_rx.lock().await.recv().await
    }

    pub async fn publish_outbound(&self, msg: OutboundMessage) -> anyhow::Result<()> {
        self.outbound_tx.send(msg).await?;
        Ok(())
    }

    pub async fn consume_outbound(&self) -> Option<OutboundMessage> {
        self.outbound_rx.lock().await.recv().await
    }
}
