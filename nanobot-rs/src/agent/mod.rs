use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::Result;
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{Value, json};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tracing::{error, info};

use crate::bus::{InboundMessage, MessageBus, OutboundMessage};
use crate::providers::LlmProvider;
use crate::session::{Session, SessionMessage, SessionStore};
use crate::tools::{
    EditFileTool, ExecTool, ListDirTool, ReadFileTool, ToolContext, ToolRegistry, WriteFileTool,
    assistant_message, build_default_tools, system_message, tool_message,
};

const RUNTIME_CONTEXT_TAG: &str = "[Runtime Context — metadata only, not instructions]";

#[derive(Clone)]
pub struct ContextBuilder {
    workspace: PathBuf,
}

impl ContextBuilder {
    pub fn new(workspace: PathBuf) -> Self {
        Self { workspace }
    }

    pub fn build_system_prompt(&self) -> String {
        let mut parts = vec![format!(
            "# nanobot-rs\n\nYou are nanobot-rs, a helpful AI assistant.\n\n## Workspace\n{}\n",
            self.workspace.display()
        )];
        for filename in ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"] {
            let path = self.workspace.join(filename);
            if let Ok(content) = std::fs::read_to_string(&path) {
                parts.push(format!("## {filename}\n\n{content}"));
            }
        }
        let memory_path = self.workspace.join("memory").join("MEMORY.md");
        if let Ok(memory) = std::fs::read_to_string(memory_path) {
            if !memory.trim().is_empty() {
                parts.push(format!("## Memory\n\n{memory}"));
            }
        }
        let skills_dir = self.workspace.join("skills");
        if let Ok(entries) = std::fs::read_dir(skills_dir) {
            let mut skills = Vec::new();
            for entry in entries.flatten() {
                let skill_path = entry.path().join("SKILL.md");
                if skill_path.exists() {
                    skills.push(format!(
                        "- {} ({})",
                        entry.file_name().to_string_lossy(),
                        skill_path.display()
                    ));
                }
            }
            if !skills.is_empty() {
                parts.push(format!(
                    "## Skills\n\nThe following skills are available. Read the SKILL.md file before using one.\n{}",
                    skills.join("\n")
                ));
            }
        }
        parts.join("\n\n---\n\n")
    }

    pub fn build_messages(
        &self,
        history: Vec<Value>,
        current_message: &str,
        current_role: &str,
        channel: Option<&str>,
        chat_id: Option<&str>,
    ) -> Vec<Value> {
        let runtime = self.runtime_context(channel, chat_id);
        let merged = format!("{runtime}\n\n{current_message}");
        let mut messages = Vec::with_capacity(history.len() + 2);
        messages.push(system_message(&self.build_system_prompt()));
        messages.extend(history);
        messages.push(json!({
            "role": current_role,
            "content": merged,
        }));
        messages
    }

    pub fn runtime_context(&self, channel: Option<&str>, chat_id: Option<&str>) -> String {
        let mut lines = vec![format!("Current Time: {}", Utc::now().to_rfc3339())];
        if let (Some(channel), Some(chat_id)) = (channel, chat_id) {
            lines.push(format!("Channel: {channel}"));
            lines.push(format!("Chat ID: {chat_id}"));
        }
        format!("{RUNTIME_CONTEXT_TAG}\n{}", lines.join("\n"))
    }

    pub fn strip_runtime_prefix(content: &str) -> Option<String> {
        if !content.starts_with(RUNTIME_CONTEXT_TAG) {
            return Some(content.to_string());
        }
        let parts = content.splitn(2, "\n\n").collect::<Vec<_>>();
        if parts.len() == 2 && !parts[1].trim().is_empty() {
            Some(parts[1].to_string())
        } else {
            None
        }
    }
}

fn truncate_chars(input: &str, max_chars: usize) -> String {
    input.chars().take(max_chars).collect()
}

#[async_trait]
trait ProgressReporter: Send + Sync {
    async fn report(&self, content: String, tool_hint: bool);
}

struct BusProgressReporter {
    bus: MessageBus,
    channel: String,
    chat_id: String,
    metadata: HashMap<String, Value>,
}

#[async_trait]
impl ProgressReporter for BusProgressReporter {
    async fn report(&self, content: String, tool_hint: bool) {
        if content.trim().is_empty() {
            return;
        }
        let mut metadata = self.metadata.clone();
        metadata.insert("_progress".to_string(), json!(true));
        metadata.insert("_tool_hint".to_string(), json!(tool_hint));
        let _ = self
            .bus
            .publish_outbound(OutboundMessage {
                channel: self.channel.clone(),
                chat_id: self.chat_id.clone(),
                content,
                metadata,
            })
            .await;
    }
}

#[derive(Clone)]
pub struct SubagentManager {
    provider: Arc<dyn LlmProvider>,
    workspace: PathBuf,
    bus: MessageBus,
    model: String,
    max_iterations: usize,
    exec_timeout: u64,
    restrict_to_workspace: bool,
    running_tasks: Arc<Mutex<HashMap<String, JoinHandle<()>>>>,
    session_tasks: Arc<Mutex<HashMap<String, Vec<String>>>>,
}

impl SubagentManager {
    pub fn new(
        provider: Arc<dyn LlmProvider>,
        workspace: PathBuf,
        bus: MessageBus,
        model: String,
        max_iterations: usize,
        exec_timeout: u64,
        restrict_to_workspace: bool,
    ) -> Self {
        Self {
            provider,
            workspace,
            bus,
            model,
            max_iterations,
            exec_timeout,
            restrict_to_workspace,
            running_tasks: Arc::new(Mutex::new(HashMap::new())),
            session_tasks: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub async fn spawn(
        &self,
        task: String,
        label: Option<String>,
        origin_channel: String,
        origin_chat_id: String,
    ) -> String {
        let task_id = truncate_chars(&uuid::Uuid::new_v4().to_string(), 8);
        let label = label.unwrap_or_else(|| {
            if task.chars().count() > 30 {
                format!("{}...", truncate_chars(&task, 30))
            } else {
                task.clone()
            }
        });
        let session_key = format!("{origin_channel}:{origin_chat_id}");
        let manager = self.clone();
        let task_id_for_handle = task_id.clone();
        let session_key_for_handle = session_key.clone();
        let label_for_handle = label.clone();
        let handle = tokio::spawn(async move {
            manager
                .run_subagent(
                    task_id_for_handle.clone(),
                    task.clone(),
                    label_for_handle.clone(),
                    origin_channel.clone(),
                    origin_chat_id.clone(),
                )
                .await;
            manager
                .running_tasks
                .lock()
                .await
                .remove(&task_id_for_handle);
            if let Some(ids) = manager
                .session_tasks
                .lock()
                .await
                .get_mut(&session_key_for_handle)
            {
                ids.retain(|id| id != &task_id_for_handle);
            }
        });
        self.running_tasks
            .lock()
            .await
            .insert(task_id.clone(), handle);
        self.session_tasks
            .lock()
            .await
            .entry(session_key)
            .or_default()
            .push(task_id.clone());
        format!("Subagent [{label}] started (id: {task_id}). I'll notify you when it completes.")
    }

    async fn run_subagent(
        &self,
        task_id: String,
        task: String,
        label: String,
        origin_channel: String,
        origin_chat_id: String,
    ) {
        let tools = ToolRegistry::new();
        tools
            .register(ReadFileTool::new(
                self.workspace.clone(),
                self.restrict_to_workspace,
            ))
            .await;
        tools
            .register(WriteFileTool::new(
                self.workspace.clone(),
                self.restrict_to_workspace,
            ))
            .await;
        tools
            .register(EditFileTool::new(
                self.workspace.clone(),
                self.restrict_to_workspace,
            ))
            .await;
        tools
            .register(ListDirTool::new(
                self.workspace.clone(),
                self.restrict_to_workspace,
            ))
            .await;
        tools
            .register(ExecTool::new(
                self.workspace.clone(),
                self.exec_timeout,
                self.restrict_to_workspace,
            ))
            .await;
        let system_prompt = format!(
            "# Subagent\n\nYou are a background subagent. Focus only on the assigned task.\nWorkspace: {}",
            self.workspace.display()
        );
        let mut messages = vec![
            system_message(&system_prompt),
            json!({"role": "user", "content": task}),
        ];
        let mut final_content = None;
        for _ in 0..self.max_iterations.min(15) {
            let defs = tools.definitions().await;
            match self
                .provider
                .chat_with_retry(messages.clone(), defs, &self.model)
                .await
            {
                Ok(response) => {
                    if response.has_tool_calls() {
                        let tool_calls = response
                            .tool_calls
                            .iter()
                            .map(|call| call.to_openai_tool_call())
                            .collect::<Vec<_>>();
                        messages.push(assistant_message(response.content.clone(), tool_calls));
                        for tool_call in response.tool_calls {
                            let result = tools.execute(&tool_call.name, tool_call.arguments).await;
                            messages.push(tool_message(&tool_call.id, &tool_call.name, &result));
                        }
                    } else {
                        final_content = response.content;
                        break;
                    }
                }
                Err(error) => {
                    final_content = Some(format!("Error: {error}"));
                    break;
                }
            }
        }
        let final_content = final_content
            .unwrap_or_else(|| "Task completed but no final response was generated.".to_string());
        let content = format!(
            "[Subagent '{label}' completed]\n\nTask: {task}\n\nResult:\n{final_content}\n\nSummarize this naturally for the user. Keep it brief and do not mention internal task IDs."
        );
        let _ = self
            .bus
            .publish_inbound(InboundMessage {
                channel: "system".to_string(),
                sender_id: "subagent".to_string(),
                chat_id: format!("{origin_channel}:{origin_chat_id}"),
                content,
                timestamp: Utc::now(),
                metadata: HashMap::new(),
                session_key_override: None,
            })
            .await;
        info!("subagent {task_id} finished");
    }

    pub async fn cancel_by_session(&self, session_key: &str) -> usize {
        let ids = self
            .session_tasks
            .lock()
            .await
            .get(session_key)
            .cloned()
            .unwrap_or_default();
        let mut cancelled = 0;
        let mut running = self.running_tasks.lock().await;
        for id in ids {
            if let Some(handle) = running.remove(&id) {
                handle.abort();
                cancelled += 1;
            }
        }
        cancelled
    }
}

pub struct AgentLoop {
    bus: MessageBus,
    provider: Arc<dyn LlmProvider>,
    workspace: PathBuf,
    model: String,
    max_iterations: usize,
    tools: ToolRegistry,
    sessions: SessionStore,
    context: ContextBuilder,
    subagents: SubagentManager,
    processing_lock: Arc<Mutex<()>>,
    active_tasks: Arc<Mutex<HashMap<String, Vec<JoinHandle<()>>>>>,
    running: Arc<AtomicBool>,
}

impl AgentLoop {
    pub async fn new(
        bus: MessageBus,
        provider: Arc<dyn LlmProvider>,
        workspace: PathBuf,
        model: String,
        max_iterations: usize,
        exec_timeout: u64,
        restrict_to_workspace: bool,
    ) -> Result<Self> {
        let sessions = SessionStore::new(&workspace)?;
        let context = ContextBuilder::new(workspace.clone());
        let subagents = SubagentManager::new(
            provider.clone(),
            workspace.clone(),
            bus.clone(),
            model.clone(),
            max_iterations,
            exec_timeout,
            restrict_to_workspace,
        );
        let tools = build_default_tools(
            workspace.clone(),
            bus.clone(),
            exec_timeout,
            restrict_to_workspace,
            subagents.clone(),
        )
        .await;
        Ok(Self {
            bus,
            provider,
            workspace,
            model,
            max_iterations,
            tools,
            sessions,
            context,
            subagents,
            processing_lock: Arc::new(Mutex::new(())),
            active_tasks: Arc::new(Mutex::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(false)),
        })
    }

    pub async fn run(&self) {
        self.running.store(true, Ordering::SeqCst);
        while self.running.load(Ordering::SeqCst) {
            let Some(msg) = self.bus.consume_inbound().await else {
                continue;
            };
            let session_key = msg.session_key();
            if msg.content.trim().eq_ignore_ascii_case("/stop") {
                self.handle_stop(&msg).await;
                continue;
            }
            let this = self.clone();
            let handle = tokio::spawn(async move {
                if let Err(error) = this.dispatch(msg).await {
                    error!("agent dispatch failed: {error}");
                }
            });
            self.active_tasks
                .lock()
                .await
                .entry(session_key)
                .or_default()
                .push(handle);
        }
    }

    async fn dispatch(&self, msg: InboundMessage) -> Result<()> {
        let _guard = self.processing_lock.lock().await;
        if let Some(outbound) = self.process_message(msg).await? {
            self.bus.publish_outbound(outbound).await?;
        }
        Ok(())
    }

    async fn handle_stop(&self, msg: &InboundMessage) {
        let session_key = msg.session_key();
        let tasks = self
            .active_tasks
            .lock()
            .await
            .remove(&session_key)
            .unwrap_or_default();
        let mut cancelled = 0usize;
        for handle in tasks {
            handle.abort();
            cancelled += 1;
        }
        cancelled += self.subagents.cancel_by_session(&session_key).await;
        let content = if cancelled == 0 {
            "No active task to stop.".to_string()
        } else {
            format!("Stopped {cancelled} task(s).")
        };
        let _ = self
            .bus
            .publish_outbound(OutboundMessage {
                channel: msg.channel.clone(),
                chat_id: msg.chat_id.clone(),
                content,
                metadata: HashMap::new(),
            })
            .await;
    }

    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
    }

    pub async fn process_direct(
        &self,
        content: &str,
        session_key: &str,
        channel: &str,
        chat_id: &str,
    ) -> Result<String> {
        let msg = InboundMessage {
            channel: channel.to_string(),
            sender_id: "user".to_string(),
            chat_id: chat_id.to_string(),
            content: content.to_string(),
            timestamp: Utc::now(),
            metadata: HashMap::new(),
            session_key_override: Some(session_key.to_string()),
        };
        let outbound = self.process_message(msg).await?;
        Ok(outbound.map(|msg| msg.content).unwrap_or_default())
    }

    async fn process_message(&self, msg: InboundMessage) -> Result<Option<OutboundMessage>> {
        if msg.channel == "system" {
            let (channel, chat_id) = msg
                .chat_id
                .split_once(':')
                .map(|(channel, chat_id)| (channel.to_string(), chat_id.to_string()))
                .unwrap_or_else(|| ("cli".to_string(), msg.chat_id.clone()));
            let mut session = self
                .sessions
                .get_or_create(&format!("{channel}:{chat_id}"))?;
            self.tools
                .set_context(ToolContext {
                    channel: channel.clone(),
                    chat_id: chat_id.clone(),
                    message_id: None,
                })
                .await;
            let history = session.get_history(0);
            let messages = self.context.build_messages(
                history,
                &msg.content,
                if msg.sender_id == "subagent" {
                    "assistant"
                } else {
                    "user"
                },
                Some(&channel),
                Some(&chat_id),
            );
            let (final_content, all_messages) = self.run_agent_loop(messages, None).await?;
            self.save_turn(&mut session, all_messages, 1)?;
            self.sessions.save(&session)?;
            return Ok(Some(OutboundMessage {
                channel,
                chat_id,
                content: final_content.unwrap_or_else(|| "Background task completed.".to_string()),
                metadata: HashMap::new(),
            }));
        }

        let session_key = msg.session_key();
        let mut session = self.sessions.get_or_create(&session_key)?;
        match msg.content.trim() {
            "/new" => {
                session.clear();
                self.sessions.save(&session)?;
                return Ok(Some(OutboundMessage {
                    channel: msg.channel,
                    chat_id: msg.chat_id,
                    content: "New session started.".to_string(),
                    metadata: HashMap::new(),
                }));
            }
            "/help" => {
                return Ok(Some(OutboundMessage {
                    channel: msg.channel,
                    chat_id: msg.chat_id,
                    content: "nanobot-rs commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands".to_string(),
                    metadata: HashMap::new(),
                }));
            }
            _ => {}
        }

        self.tools
            .set_context(ToolContext {
                channel: msg.channel.clone(),
                chat_id: msg.chat_id.clone(),
                message_id: msg
                    .metadata
                    .get("message_id")
                    .and_then(Value::as_str)
                    .map(str::to_string),
            })
            .await;
        self.tools.start_turn().await;

        let history = session.get_history(0);
        let messages = self.context.build_messages(
            history.clone(),
            &msg.content,
            "user",
            Some(&msg.channel),
            Some(&msg.chat_id),
        );
        let reporter = Arc::new(BusProgressReporter {
            bus: self.bus.clone(),
            channel: msg.channel.clone(),
            chat_id: msg.chat_id.clone(),
            metadata: msg.metadata.clone(),
        });
        let (final_content, all_messages) = self.run_agent_loop(messages, Some(reporter)).await?;
        self.save_turn(&mut session, all_messages, 1 + history.len())?;
        self.sessions.save(&session)?;

        if self.tools.sent_message_this_turn().await {
            return Ok(None);
        }

        Ok(Some(OutboundMessage {
            channel: msg.channel,
            chat_id: msg.chat_id,
            content: final_content.unwrap_or_else(|| {
                "I've completed processing but have no response to give.".to_string()
            }),
            metadata: msg.metadata,
        }))
    }

    async fn run_agent_loop(
        &self,
        initial_messages: Vec<Value>,
        reporter: Option<Arc<dyn ProgressReporter>>,
    ) -> Result<(Option<String>, Vec<Value>)> {
        let mut messages = initial_messages;
        let mut final_content = None;
        for _ in 0..self.max_iterations {
            let defs = self.tools.definitions().await;
            let response = self
                .provider
                .chat_with_retry(messages.clone(), defs, &self.model)
                .await?;
            if response.has_tool_calls() {
                if let Some(reporter) = &reporter {
                    if let Some(content) = response.content.clone() {
                        reporter.report(content, false).await;
                    }
                    let hint = response
                        .tool_calls
                        .iter()
                        .map(tool_hint)
                        .collect::<Vec<_>>()
                        .join(", ");
                    if !hint.is_empty() {
                        reporter.report(hint, true).await;
                    }
                }
                let tool_calls = response
                    .tool_calls
                    .iter()
                    .map(|call| call.to_openai_tool_call())
                    .collect::<Vec<_>>();
                messages.push(assistant_message(response.content.clone(), tool_calls));
                for tool_call in response.tool_calls {
                    let result = self
                        .tools
                        .execute(&tool_call.name, tool_call.arguments)
                        .await;
                    messages.push(tool_message(&tool_call.id, &tool_call.name, &result));
                }
            } else {
                final_content = response.content.clone();
                messages.push(assistant_message(response.content, Vec::new()));
                break;
            }
        }
        if final_content.is_none() {
            final_content = Some(format!(
                "I reached the maximum number of tool call iterations ({}) without completing the task.",
                self.max_iterations
            ));
        }
        Ok((final_content, messages))
    }

    fn save_turn(&self, session: &mut Session, messages: Vec<Value>, skip: usize) -> Result<()> {
        for value in messages.into_iter().skip(skip) {
            let mut message: SessionMessage = serde_json::from_value(value)?;
            if message.role == "assistant"
                && message.content.is_null()
                && message.tool_calls.is_none()
            {
                continue;
            }
            if message.role == "user" {
                if let Some(content) = message.content.as_str() {
                    match ContextBuilder::strip_runtime_prefix(content) {
                        Some(stripped) => message.content = json!(stripped),
                        None => continue,
                    }
                }
            }
            message.timestamp.get_or_insert_with(Utc::now);
            session.messages.push(message);
        }
        session.updated_at = Utc::now();
        Ok(())
    }
}

impl Clone for AgentLoop {
    fn clone(&self) -> Self {
        Self {
            bus: self.bus.clone(),
            provider: self.provider.clone(),
            workspace: self.workspace.clone(),
            model: self.model.clone(),
            max_iterations: self.max_iterations,
            tools: self.tools.clone(),
            sessions: self.sessions.clone(),
            context: self.context.clone(),
            subagents: self.subagents.clone(),
            processing_lock: self.processing_lock.clone(),
            active_tasks: self.active_tasks.clone(),
            running: self.running.clone(),
        }
    }
}

fn tool_hint(call: &crate::providers::ToolCall) -> String {
    if let Some(object) = call.arguments.as_object() {
        if let Some(value) = object.values().find_map(Value::as_str) {
            if value.chars().count() > 40 {
                return format!("{}(\"{}…\")", call.name, truncate_chars(value, 40));
            }
            return format!("{}(\"{}\")", call.name, value);
        }
    }
    call.name.clone()
}
