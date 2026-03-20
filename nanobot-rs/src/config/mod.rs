use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct AgentDefaults {
    pub workspace: String,
    pub model: String,
    pub max_tool_iterations: usize,
}

impl Default for AgentDefaults {
    fn default() -> Self {
        Self {
            workspace: default_workspace_path().display().to_string(),
            model: "gpt-4.1-mini".to_string(),
            max_tool_iterations: 20,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct AgentsConfig {
    pub defaults: AgentDefaults,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ProviderConfig {
    pub api_key: String,
    pub api_base: String,
}

impl Default for ProviderConfig {
    fn default() -> Self {
        Self {
            api_key: String::new(),
            api_base: "https://api.openai.com/v1".to_string(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ProvidersConfig {
    pub openai: ProviderConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct TelegramConfig {
    pub enabled: bool,
    pub token: String,
    pub allow_from: Vec<String>,
    #[serde(default = "default_telegram_api_base")]
    pub api_base: String,
}

impl Default for TelegramConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            token: String::new(),
            allow_from: Vec::new(),
            api_base: default_telegram_api_base(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ChannelsConfig {
    pub send_progress: bool,
    pub send_tool_hints: bool,
    pub telegram: TelegramConfig,
}

impl Default for ChannelsConfig {
    fn default() -> Self {
        Self {
            send_progress: true,
            send_tool_hints: false,
            telegram: TelegramConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ExecToolConfig {
    pub timeout: u64,
}

impl Default for ExecToolConfig {
    fn default() -> Self {
        Self { timeout: 60 }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ToolsConfig {
    pub exec: ExecToolConfig,
    pub restrict_to_workspace: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Config {
    pub agents: AgentsConfig,
    pub providers: ProvidersConfig,
    pub channels: ChannelsConfig,
    pub tools: ToolsConfig,
}

impl Config {
    pub fn workspace_path(&self) -> PathBuf {
        expand_tilde(Path::new(&self.agents.defaults.workspace))
    }

    pub fn config_path(user_path: Option<&Path>) -> PathBuf {
        user_path
            .map(Path::to_path_buf)
            .unwrap_or_else(default_config_path)
    }
}

pub fn default_config_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".nanobot-rs")
        .join("config.json")
}

pub fn default_workspace_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".nanobot-rs")
        .join("workspace")
}

pub fn expand_tilde(path: &Path) -> PathBuf {
    let raw = path.to_string_lossy();
    if raw == "~" {
        return dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    }
    if let Some(stripped) = raw.strip_prefix("~/") {
        return dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(stripped);
    }
    path.to_path_buf()
}

pub fn load_config(path: Option<&Path>) -> Result<Config> {
    let config_path = Config::config_path(path);
    if !config_path.exists() {
        return Ok(Config::default());
    }
    let raw = std::fs::read_to_string(&config_path)
        .with_context(|| format!("failed to read config {}", config_path.display()))?;
    let config = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse config {}", config_path.display()))?;
    Ok(config)
}

pub fn save_config(config: &Config, path: Option<&Path>) -> Result<PathBuf> {
    let config_path = Config::config_path(path);
    if let Some(parent) = config_path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("failed to create {}", parent.display()))?;
    }
    let json = serde_json::to_string_pretty(config)?;
    std::fs::write(&config_path, json)
        .with_context(|| format!("failed to write config {}", config_path.display()))?;
    Ok(config_path)
}

fn default_telegram_api_base() -> String {
    "https://api.telegram.org".to_string()
}
