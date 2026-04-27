use serde::Serialize;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use url::Url;

type GatewayChild = Arc<Mutex<Option<CommandChild>>>;
struct GatewayState(GatewayChild);

const GATEWAY_PORT: u16 = 18790;
const DESKTOP_WS_PORT: u16 = 18791;

#[derive(Serialize)]
struct GatewayBootstrap {
    ws_url: String,
}

// ──────────────────────────────────────────
// IPC Commands
// ──────────────────────────────────────────

#[tauri::command]
fn check_onboarding_needed() -> bool {
    let path = config_path();
    if !path.exists() {
        return true;
    }
    match std::fs::read_to_string(&path) {
        Ok(s) => {
            // Check if config has any provider API key or Ollama configured
            let parsed: Result<serde_json::Value, _> = serde_json::from_str(&s);
            match parsed {
                Ok(v) => {
                    let providers = &v["providers"];
                    if !providers.is_object() {
                        return true;
                    }
                    // Check if any provider has an apiKey set, or ollama has apiBase
                    let obj = providers.as_object().unwrap();
                    !obj.iter().any(|(_, pv)| {
                        let has_key = pv["apiKey"]
                            .as_str()
                            .is_some_and(|k| !k.is_empty());
                        let has_base = pv["apiBase"]
                            .as_str()
                            .is_some_and(|b| !b.is_empty());
                        has_key || has_base
                    })
                }
                Err(_) => true,
            }
        }
        Err(_) => true,
    }
}

#[tauri::command]
fn write_config(json: String) -> Result<(), String> {
    let path = config_path();
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p).map_err(|e| e.to_string())?;
    }
    let new_val: serde_json::Value =
        serde_json::from_str(&json).map_err(|e| format!("Invalid JSON: {e}"))?;
    let merged = if path.exists() {
        let existing: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap_or_default())
                .unwrap_or(serde_json::json!({}));
        let mut m = existing;
        json_merge(&mut m, new_val);
        m
    } else {
        new_val
    };
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&merged).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}

#[tauri::command]
fn open_control_ui(window: tauri::WebviewWindow) -> Result<(), String> {
    navigate_window(&window, "index.html")
}

#[tauri::command]
fn bootstrap_gateway(
    app: tauri::AppHandle,
    state: tauri::State<'_, GatewayState>,
) -> Result<GatewayBootstrap, String> {
    ensure_gateway_running(&app, state.inner().0.clone())?;
    Ok(GatewayBootstrap {
        ws_url: desktop_ws_url(),
    })
}

// ──────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────

fn config_path() -> PathBuf {
    let home = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .unwrap_or_else(|_| "C:\\Users\\Default".to_string());
    PathBuf::from(home).join(".nanobot").join("config.json")
}

fn desktop_runtime_config_path() -> PathBuf {
    config_path()
        .parent()
        .unwrap_or_else(|| std::path::Path::new("."))
        .join("desktop-runtime.json")
}

fn desktop_ws_url() -> String {
    format!("ws://127.0.0.1:{DESKTOP_WS_PORT}")
}

fn app_url(path: &str) -> String {
    #[cfg(any(target_os = "windows", target_os = "android"))]
    {
        format!("http://tauri.localhost/{path}")
    }

    #[cfg(not(any(target_os = "windows", target_os = "android")))]
    {
        format!("tauri://localhost/{path}")
    }
}

fn navigate_window(window: &tauri::WebviewWindow, path: &str) -> Result<(), String> {
    let url = Url::parse(&app_url(path)).map_err(|e| e.to_string())?;
    window.navigate(url).map_err(|e| e.to_string())
}

fn write_desktop_runtime_config() -> Result<PathBuf, String> {
    let source_path = config_path();
    let runtime_path = desktop_runtime_config_path();

    let mut config = if source_path.exists() {
        std::fs::read_to_string(&source_path)
            .ok()
            .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
            .unwrap_or_else(|| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    let root = config
        .as_object_mut()
        .ok_or_else(|| "Desktop runtime config must be a JSON object".to_string())?;
    let channels = root
        .entry("channels")
        .or_insert_with(|| serde_json::json!({}))
        .as_object_mut()
        .ok_or_else(|| "channels must be a JSON object".to_string())?;
    channels.insert(
        "desktop".to_string(),
        serde_json::json!({
            "enabled": true,
            "host": "127.0.0.1",
            "port": DESKTOP_WS_PORT,
            "allowFrom": ["*"]
        }),
    );

    if let Some(parent) = runtime_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(
        &runtime_path,
        serde_json::to_string_pretty(&config).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;

    Ok(runtime_path)
}

fn json_merge(dst: &mut serde_json::Value, src: serde_json::Value) {
    match (dst, src) {
        (serde_json::Value::Object(d), serde_json::Value::Object(s)) => {
            for (k, v) in s {
                json_merge(d.entry(k).or_insert(serde_json::Value::Null), v);
            }
        }
        (dst, src) => *dst = src,
    }
}

fn ensure_gateway_running(app: &tauri::AppHandle, child_arc: GatewayChild) -> Result<(), String> {
    if child_arc.lock().map_err(|e| e.to_string())?.is_some() {
        return Ok(());
    }

    let runtime_config = write_desktop_runtime_config()?;
    let runtime_config_arg = runtime_config.to_string_lossy().to_string();
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        match handle
            .shell()
            .sidecar("nanobot-gateway")
            .expect("nanobot-gateway sidecar not found")
            .args([
                "gateway",
                "--config",
                &runtime_config_arg,
                "--port",
                &GATEWAY_PORT.to_string(),
            ])
            .spawn()
        {
            Ok((_rx, proc)) => {
                log::info!("nanobot gateway started, pid={}", proc.pid());
                if let Ok(mut guard) = child_arc.lock() {
                    *guard = Some(proc);
                }
            }
            Err(e) => log::error!("nanobot gateway start failed: {e}"),
        }
    });
    Ok(())
}

// ──────────────────────────────────────────
// Entry point
// ──────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let child: GatewayChild = Arc::new(Mutex::new(None));
    let child_for_event = child.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .manage(GatewayState(child))
        .invoke_handler(tauri::generate_handler![
            check_onboarding_needed,
            write_config,
            open_control_ui,
            bootstrap_gateway,
        ])
        .setup(|app| {
            let needs_onboard = check_onboarding_needed();

            if needs_onboard {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = navigate_window(&win, "onboard.html");
                }
            } else {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = navigate_window(&win, "index.html");
                }
            }

            // Start gateway sidecar
            if let Err(err) =
                ensure_gateway_running(app.handle(), app.state::<GatewayState>().inner().0.clone())
            {
                log::warn!("Gateway startup skipped: {err}");
            }
            Ok(())
        })
        .on_page_load(move |window, _payload| {
            // Inject WebSocket URL into sessionStorage for chat UI
            let js = format!(
                "(() => {{
                    try {{
                        sessionStorage.setItem('nanobot.desktop.ws_url', '{url}');
                    }} catch (_e) {{}}
                }})();",
                url = desktop_ws_url()
            );
            let _ = window.eval(js);
        })
        .on_window_event(move |_win, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Ok(mut g) = child_for_event.lock() {
                    if let Some(proc) = g.take() {
                        log::info!("Stopping nanobot gateway...");
                        let _ = proc.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error running nanobot");
}
