use async_trait::async_trait;
use serde_json::{Value, json};

#[derive(Debug, Clone)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: Value,
}

impl ToolCall {
    pub fn to_openai_tool_call(&self) -> Value {
        json!({
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments.to_string(),
            }
        })
    }
}

#[derive(Debug, Clone)]
pub struct LlmResponse {
    pub content: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub finish_reason: String,
}

impl LlmResponse {
    pub fn has_tool_calls(&self) -> bool {
        !self.tool_calls.is_empty()
    }
}

#[async_trait]
pub trait LlmProvider: Send + Sync {
    fn default_model(&self) -> &str;

    async fn chat(
        &self,
        messages: Vec<Value>,
        tools: Vec<Value>,
        model: &str,
    ) -> anyhow::Result<LlmResponse>;

    async fn chat_with_retry(
        &self,
        messages: Vec<Value>,
        tools: Vec<Value>,
        model: &str,
    ) -> anyhow::Result<LlmResponse> {
        let mut last_error = None;
        for delay in [1u64, 2, 4] {
            match self.chat(messages.clone(), tools.clone(), model).await {
                Ok(response) => return Ok(response),
                Err(error) => {
                    last_error = Some(error);
                    tokio::time::sleep(std::time::Duration::from_secs(delay)).await;
                }
            }
        }
        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("provider request failed")))
    }
}

#[derive(Clone)]
pub struct OpenAIProvider {
    client: reqwest::Client,
    api_key: String,
    api_base: String,
    default_model: String,
}

impl OpenAIProvider {
    pub fn new(api_key: String, api_base: String, default_model: String) -> Self {
        Self {
            client: reqwest::Client::new(),
            api_key,
            api_base,
            default_model,
        }
    }
}

#[async_trait]
impl LlmProvider for OpenAIProvider {
    fn default_model(&self) -> &str {
        &self.default_model
    }

    async fn chat(
        &self,
        messages: Vec<Value>,
        tools: Vec<Value>,
        model: &str,
    ) -> anyhow::Result<LlmResponse> {
        let body = json!({
            "model": model,
            "messages": messages,
            "tools": if tools.is_empty() { Value::Null } else { Value::Array(tools) },
            "temperature": 0.1,
        });
        let response = self
            .client
            .post(format!(
                "{}/chat/completions",
                self.api_base.trim_end_matches('/')
            ))
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await?;
        let status = response.status();
        let value: Value = response.json().await?;
        if !status.is_success() {
            return Err(anyhow::anyhow!("provider error {}: {}", status, value));
        }
        let choice = value
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .ok_or_else(|| anyhow::anyhow!("provider returned no choices"))?;
        let message = choice
            .get("message")
            .and_then(Value::as_object)
            .ok_or_else(|| anyhow::anyhow!("provider returned no message"))?;
        let content = message.get("content").and_then(normalize_content);
        let tool_calls = message
            .get("tool_calls")
            .and_then(Value::as_array)
            .map(|calls| {
                calls
                    .iter()
                    .filter_map(|call| {
                        let id = call.get("id")?.as_str()?.to_string();
                        let function = call.get("function")?;
                        let name = function.get("name")?.as_str()?.to_string();
                        let raw_args = function.get("arguments")?.as_str().unwrap_or("{}");
                        let arguments = serde_json::from_str(raw_args)
                            .unwrap_or_else(|_| json!({ "_raw": raw_args }));
                        Some(ToolCall {
                            id,
                            name,
                            arguments,
                        })
                    })
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let finish_reason = choice
            .get("finish_reason")
            .and_then(Value::as_str)
            .unwrap_or("stop")
            .to_string();
        Ok(LlmResponse {
            content,
            tool_calls,
            finish_reason,
        })
    }
}

fn normalize_content(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(text) => Some(text.clone()),
        Value::Array(items) => {
            let mut chunks = Vec::new();
            for item in items {
                if let Some(text) = item.get("text").and_then(Value::as_str) {
                    chunks.push(text.to_string());
                }
            }
            if chunks.is_empty() {
                None
            } else {
                Some(chunks.join("\n"))
            }
        }
        _ => Some(value.to_string()),
    }
}
