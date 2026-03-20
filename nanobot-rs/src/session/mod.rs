use std::collections::HashSet;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMessage {
    pub role: String,
    #[serde(default)]
    pub content: Value,
    #[serde(default)]
    pub timestamp: Option<DateTime<Utc>>,
    #[serde(default)]
    pub tool_calls: Option<Vec<Value>>,
    #[serde(default)]
    pub tool_call_id: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
}

impl SessionMessage {
    pub fn to_llm_message(&self) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("role".to_string(), json!(self.role));
        obj.insert("content".to_string(), self.content.clone());
        if let Some(tool_calls) = &self.tool_calls {
            obj.insert("tool_calls".to_string(), json!(tool_calls));
        }
        if let Some(tool_call_id) = &self.tool_call_id {
            obj.insert("tool_call_id".to_string(), json!(tool_call_id));
        }
        if let Some(name) = &self.name {
            obj.insert("name".to_string(), json!(name));
        }
        Value::Object(obj)
    }
}

#[derive(Debug, Clone)]
pub struct Session {
    pub key: String,
    pub messages: Vec<SessionMessage>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub last_consolidated: usize,
}

impl Session {
    pub fn new(key: impl Into<String>) -> Self {
        let now = Utc::now();
        Self {
            key: key.into(),
            messages: Vec::new(),
            created_at: now,
            updated_at: now,
            last_consolidated: 0,
        }
    }

    pub fn clear(&mut self) {
        self.messages.clear();
        self.last_consolidated = 0;
        self.updated_at = Utc::now();
    }

    pub fn get_history(&self, max_messages: usize) -> Vec<Value> {
        let unconsolidated = &self.messages[self.last_consolidated..];
        let mut sliced = if max_messages == 0 || max_messages >= unconsolidated.len() {
            unconsolidated.to_vec()
        } else {
            unconsolidated[unconsolidated.len() - max_messages..].to_vec()
        };

        if let Some(pos) = sliced.iter().position(|m| m.role == "user") {
            sliced = sliced[pos..].to_vec();
        }

        let start = legal_start(&sliced);
        if start > 0 {
            sliced = sliced[start..].to_vec();
        }

        sliced.into_iter().map(|m| m.to_llm_message()).collect()
    }
}

fn legal_start(messages: &[SessionMessage]) -> usize {
    let mut declared = HashSet::<String>::new();
    let mut start = 0;
    for (idx, msg) in messages.iter().enumerate() {
        match msg.role.as_str() {
            "assistant" => {
                if let Some(tool_calls) = &msg.tool_calls {
                    for call in tool_calls {
                        if let Some(id) = call.get("id").and_then(Value::as_str) {
                            declared.insert(id.to_string());
                        }
                    }
                }
            }
            "tool" => {
                if let Some(tool_call_id) = &msg.tool_call_id {
                    if !declared.contains(tool_call_id) {
                        start = idx + 1;
                        declared.clear();
                        for prev in &messages[start..=idx] {
                            if prev.role == "assistant" {
                                if let Some(tool_calls) = &prev.tool_calls {
                                    for call in tool_calls {
                                        if let Some(id) = call.get("id").and_then(Value::as_str) {
                                            declared.insert(id.to_string());
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    }
    start
}

#[derive(Debug, Clone)]
pub struct SessionStore {
    dir: PathBuf,
}

impl SessionStore {
    pub fn new(workspace: &Path) -> Result<Self> {
        let dir = workspace.join("sessions");
        std::fs::create_dir_all(&dir)
            .with_context(|| format!("failed to create {}", dir.display()))?;
        Ok(Self { dir })
    }

    pub fn path_for(&self, key: &str) -> PathBuf {
        let safe = key.replace(':', "_");
        self.dir.join(format!("{safe}.jsonl"))
    }

    pub fn get_or_create(&self, key: &str) -> Result<Session> {
        let path = self.path_for(key);
        if !path.exists() {
            return Ok(Session::new(key));
        }
        let raw = std::fs::read_to_string(&path)
            .with_context(|| format!("failed to read session {}", path.display()))?;
        let mut created_at = Utc::now();
        let mut updated_at = Utc::now();
        let mut last_consolidated = 0usize;
        let mut messages = Vec::new();
        for line in raw.lines().filter(|line| !line.trim().is_empty()) {
            let value: Value = serde_json::from_str(line)?;
            if value.get("_type").and_then(Value::as_str) == Some("metadata") {
                if let Some(created) = value.get("created_at").and_then(Value::as_str) {
                    created_at = created.parse().unwrap_or(created_at);
                }
                if let Some(updated) = value.get("updated_at").and_then(Value::as_str) {
                    updated_at = updated.parse().unwrap_or(updated_at);
                }
                last_consolidated = value
                    .get("last_consolidated")
                    .and_then(Value::as_u64)
                    .unwrap_or(0) as usize;
            } else {
                messages.push(serde_json::from_value(value)?);
            }
        }
        Ok(Session {
            key: key.to_string(),
            messages,
            created_at,
            updated_at,
            last_consolidated,
        })
    }

    pub fn save(&self, session: &Session) -> Result<()> {
        let mut lines = Vec::with_capacity(session.messages.len() + 1);
        lines.push(serde_json::to_string(&json!({
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "last_consolidated": session.last_consolidated,
        }))?);
        for message in &session.messages {
            lines.push(serde_json::to_string(message)?);
        }
        let path = self.path_for(&session.key);
        std::fs::write(&path, lines.join("\n") + "\n")
            .with_context(|| format!("failed to write session {}", path.display()))?;
        Ok(())
    }
}
