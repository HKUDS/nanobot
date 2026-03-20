use std::collections::VecDeque;
use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use nanobot_rs::agent::{AgentLoop, SubagentManager};
use nanobot_rs::bus::MessageBus;
use nanobot_rs::providers::{LlmProvider, LlmResponse, ToolCall};
use serde_json::json;
use tempfile::tempdir;
use tokio::sync::Mutex;

#[derive(Clone)]
struct MockProvider {
    model: String,
    responses: Arc<Mutex<VecDeque<LlmResponse>>>,
}

#[async_trait]
impl LlmProvider for MockProvider {
    fn default_model(&self) -> &str {
        &self.model
    }

    async fn chat(
        &self,
        _messages: Vec<serde_json::Value>,
        _tools: Vec<serde_json::Value>,
        _model: &str,
    ) -> Result<LlmResponse> {
        self.responses
            .lock()
            .await
            .pop_front()
            .ok_or_else(|| anyhow::anyhow!("no more responses"))
    }
}

fn mock_provider(responses: Vec<LlmResponse>) -> Arc<dyn LlmProvider> {
    Arc::new(MockProvider {
        model: "mock-model".to_string(),
        responses: Arc::new(Mutex::new(responses.into())),
    })
}

#[tokio::test]
async fn agent_executes_tool_loop() {
    let dir = tempdir().expect("tempdir");
    std::fs::write(dir.path().join("note.txt"), "hello from file").expect("write note");
    let provider = mock_provider(vec![
        LlmResponse {
            content: Some("looking".to_string()),
            tool_calls: vec![ToolCall {
                id: "call_1".to_string(),
                name: "read_file".to_string(),
                arguments: json!({"path": "note.txt"}),
            }],
            finish_reason: "tool_calls".to_string(),
        },
        LlmResponse {
            content: Some("done".to_string()),
            tool_calls: Vec::new(),
            finish_reason: "stop".to_string(),
        },
    ]);
    let bus = MessageBus::new(32);
    let agent = AgentLoop::new(
        bus,
        provider,
        dir.path().to_path_buf(),
        "mock-model".to_string(),
        5,
        10,
        false,
    )
    .await
    .expect("agent");
    let result = agent
        .process_direct("read note", "cli:test", "cli", "test")
        .await
        .expect("process");
    assert_eq!(result, "done");
}

#[tokio::test]
async fn agent_suppresses_final_reply_after_message_tool() {
    let dir = tempdir().expect("tempdir");
    let long_chinese =
        "请问您想查询哪个城市的天气？请提供城市名称或位置信息，这样我才能帮您查询天气情况。";
    let provider = mock_provider(vec![
        LlmResponse {
            content: Some("sending".to_string()),
            tool_calls: vec![ToolCall {
                id: "call_1".to_string(),
                name: "message".to_string(),
                arguments: json!({"content": long_chinese}),
            }],
            finish_reason: "tool_calls".to_string(),
        },
        LlmResponse {
            content: Some("done".to_string()),
            tool_calls: Vec::new(),
            finish_reason: "stop".to_string(),
        },
    ]);
    let bus = MessageBus::new(32);
    let agent = AgentLoop::new(
        bus.clone(),
        provider,
        dir.path().to_path_buf(),
        "mock-model".to_string(),
        5,
        10,
        false,
    )
    .await
    .expect("agent");
    let result = agent
        .process_direct("say hi", "cli:test", "cli", "test")
        .await
        .expect("process");
    assert!(result.is_empty());
    let outbound = loop {
        let outbound = bus.consume_outbound().await.expect("message tool outbound");
        let is_progress = outbound
            .metadata
            .get("_progress")
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        if !is_progress {
            break outbound;
        }
    };
    assert_eq!(outbound.content, long_chinese);
}

#[tokio::test]
async fn agent_returns_iteration_limit_message() {
    let dir = tempdir().expect("tempdir");
    let provider = mock_provider(vec![
        LlmResponse {
            content: None,
            tool_calls: vec![ToolCall {
                id: "call_1".to_string(),
                name: "list_dir".to_string(),
                arguments: json!({"path": "."}),
            }],
            finish_reason: "tool_calls".to_string(),
        },
        LlmResponse {
            content: None,
            tool_calls: vec![ToolCall {
                id: "call_2".to_string(),
                name: "list_dir".to_string(),
                arguments: json!({"path": "."}),
            }],
            finish_reason: "tool_calls".to_string(),
        },
    ]);
    let bus = MessageBus::new(32);
    let agent = AgentLoop::new(
        bus,
        provider,
        dir.path().to_path_buf(),
        "mock-model".to_string(),
        1,
        10,
        false,
    )
    .await
    .expect("agent");
    let result = agent
        .process_direct("loop", "cli:test", "cli", "test")
        .await
        .expect("process");
    assert!(result.contains("maximum number of tool call iterations (1)"));
}

#[tokio::test]
async fn subagent_reports_back_via_bus() {
    let dir = tempdir().expect("tempdir");
    let provider = mock_provider(vec![LlmResponse {
        content: Some("background result".to_string()),
        tool_calls: Vec::new(),
        finish_reason: "stop".to_string(),
    }]);
    let bus = MessageBus::new(32);
    let manager = SubagentManager::new(
        provider,
        dir.path().to_path_buf(),
        bus.clone(),
        "mock-model".to_string(),
        5,
        10,
        false,
    );
    let status = manager
        .spawn(
            "do background work".to_string(),
            Some("job".to_string()),
            "cli".to_string(),
            "test".to_string(),
        )
        .await;
    assert!(status.contains("Subagent [job] started"));
    let inbound = tokio::time::timeout(std::time::Duration::from_secs(2), bus.consume_inbound())
        .await
        .expect("timely inbound")
        .expect("inbound message");
    assert_eq!(inbound.channel, "system");
    assert!(inbound.content.contains("background result"));
}
