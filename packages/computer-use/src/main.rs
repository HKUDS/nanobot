//! nanobot's native host for the pinned MIT Cua SDK; no agent/model execution.
mod policy;
mod sharing;

use std::{path::PathBuf, sync::{Arc, Weak, Mutex as StdMutex, atomic::{AtomicBool, Ordering}}, time::Duration};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use anyhow::{ensure, Result};
use cua_driver_sdk::{CuaDriver, CuaDriverSession, DriverHostOptions, TrustedSessionOptions, SessionPermissionMode};
use cursor_overlay::CursorConfig;
use platform_macos::permissions::status;
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::{io::{AsyncBufReadExt, AsyncWriteExt, BufReader}, net::{UnixListener, UnixStream}, sync::Mutex};

const APP_ID: &str = "io.nanobot.computer-use";
const MAX_REQUEST: usize = 1024 * 1024;

struct Revocation { paused: AtomicBool, path: PathBuf, session: StdMutex<Option<Weak<CuaDriverSession>>> }
impl Revocation {
    fn revoke(&self) {
        self.paused.store(true, Ordering::Release);
        // Do not wait for the async action mutex to cancel an in-flight action.
        if let Some(session) = self.session.lock().expect("session revocation").as_ref().and_then(Weak::upgrade) {
            session.close();
        }
        // Also survive a crash/restart. No model/tool call may remove this.
        let _ = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&self.path);
    }
}

struct Active {
    owner: String,
    sharing: sharing::Sharing,
    session: Arc<CuaDriverSession>,
    touched: std::time::Instant,
}
impl Drop for Active { fn drop(&mut self) { self.session.close(); } }

struct Host {
    driver: Arc<CuaDriver>,
    revocation: Arc<Revocation>,
    active: Mutex<Option<Active>>,
    control: bool,
    accessibility_requested: AtomicBool,
    recording_requested: AtomicBool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    method: String,
    #[serde(default)] name: String,
    #[serde(default = "empty_object")] arguments: Value,
}
fn empty_object() -> Value { json!({}) }

impl Host {
    fn session(&self) -> Result<Arc<CuaDriverSession>> {
        Ok(self.driver.create_trusted_session(TrustedSessionOptions {
            public_session: uuid::Uuid::new_v4().to_string(), mode: SessionPermissionMode::Standard,
            ttl_seconds: 3600, idle_ttl_seconds: 300,
            capability_manifest_path: None, bounded_manifest_path: None,
        })?)
    }

    async fn request(&self, mut request: Request, owner: &str) -> Result<Value> {
        match request.method.as_str() {
            "status" => return Ok(json!({"protocol": 1, "connected": true,
                "accessibility": status::accessibility_granted(),
                "screen_recording": status::screen_recording_granted(),
                "capture_verified": false, "sharing_paused": self.revocation.paused.load(Ordering::Acquire),
                "permission_app": "nanobot Computer Use", "pid": std::process::id()})),
            "list" => {
                let mut list: Value = serde_json::from_str(&self.driver.list_tools_json().await?)?;
                if let Some(tools) = list.get_mut("tools").and_then(Value::as_array_mut) {
                    tools.retain(|t| t["name"].as_str().is_some_and(|n| policy::OBSERVE.contains(&n) || (self.control && policy::CONTROL.contains(&n))));
                    for tool in tools {
                        if let Some(properties) = tool["inputSchema"]["properties"].as_object_mut() {
                            properties.remove("session");
                            properties.remove("screenshot_out_file");
                            if let Some(scope) = properties.get_mut("scope") {
                                *scope = json!({"type": "string", "enum": ["window"], "default": "window"});
                            }
                        }
                        let description = tool["description"].as_str().unwrap_or("").to_owned();
                        tool["description"] = json!(format!("{description}\nNanobot: window-scoped only. First call get_window_state with pid and window_id; then operate that same window. Stop Sharing revokes access until the user reconnects in Apps. Never retry via another desktop tool after a stop."));
                    }
                }
                return Ok(list);
            }
            "stop" => {
                self.revocation.revoke();
                self.active.lock().await.take();
                self.driver.shutdown().await?;
                // Only the local administration client emits this method.
                tokio::spawn(async { tokio::time::sleep(Duration::from_millis(100)).await; std::process::exit(0); });
                return Ok(json!({"stopped": true}));
            }
            "request_permission" => {
                // One explicit step, never two simultaneous native dialogs.
                let prompted = match request.name.as_str() {
                    "accessibility" if !status::accessibility_granted() && !self.accessibility_requested.swap(true, Ordering::AcqRel) => { status::request_accessibility(); true }
                    "screen_recording" if !status::screen_recording_granted() && !self.recording_requested.swap(true, Ordering::AcqRel) => { status::request_screen_recording(); true }
                    "accessibility" | "screen_recording" => false,
                    _ => anyhow::bail!("Choose Accessibility or Screen Recording."),
                };
                return Ok(json!({"requested": true, "prompted": prompted}));
            }
            "call" => {}
            _ => anyhow::bail!("Unknown native host method."),
        }
        policy::validate(&request.name, &mut request.arguments, self.control, self.revocation.paused.load(Ordering::Acquire))?;
        ensure!(status::accessibility_granted() && status::screen_recording_granted(), "Finish macOS permissions for nanobot Computer Use in Apps.");
        if request.name == "list_windows" {
            let session = self.session()?;
            let result = session.call_tool(request.name, request.arguments.to_string()).await;
            session.close();
            return Ok(serde_json::from_str(&result?.raw_json)?);
        }
        // This lock serializes selection, observations and actions. A different
        // MCP connection cannot silently replace a window in an active task.
        let mut active = self.active.lock().await;
        if let Some(current) = active.as_ref() {
            ensure!(current.owner == owner, "Another Computer Use connection owns the window. Finish that task first.");
        }
        if request.name == "get_window_state" {
            let target = policy::target(&request.arguments)?;
            if active.as_ref().is_none_or(|a| a.sharing.target != target) {
                active.take();
                let session = self.session()?;
                *self.revocation.session.lock().expect("session revocation") = Some(Arc::downgrade(&session));
                let share = sharing::Sharing::start(target, session.clone(), self.revocation.clone())?;
                *active = Some(Active { owner: owner.into(), sharing: share, session, touched: std::time::Instant::now() });
            }
        }
        let current = active.as_mut().ok_or_else(|| anyhow::anyhow!("Call get_window_state for the target window before acting."))?;
        let args = request.arguments.as_object_mut().expect("validated object");
        args.entry("pid").or_insert(json!(current.sharing.target.pid));
        args.entry("window_id").or_insert(json!(current.sharing.target.window));
        ensure!(policy::target(&request.arguments)? == current.sharing.target, "Observe the new window with get_window_state before acting on it.");
        ensure!(!self.revocation.paused.load(Ordering::Acquire), "Sharing was stopped. Reconnect in Apps.");
        let result = current.session.call_tool(request.name, request.arguments.to_string()).await?;
        current.touched = std::time::Instant::now();
        // Never send observations obtained concurrently with a system stop.
        ensure!(!self.revocation.paused.load(Ordering::Acquire), "Sharing was stopped; the result was discarded.");
        Ok(serde_json::from_str(&result.raw_json)?)
    }
}

async fn connection(host: Arc<Host>, stream: UnixStream) -> Result<()> {
    ensure!(stream.peer_cred()?.uid() == unsafe { libc::getuid() }, "Wrong socket owner.");
    let owner = uuid::Uuid::new_v4().to_string();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let outcome = async {
        loop {
            let mut line = Vec::new();
            // read_until is bounded manually via fill_buf, never an unbounded
            // allocation from a malformed local request.
            loop {
                let bytes = reader.fill_buf().await?;
                if bytes.is_empty() { break; }
                let count = bytes.iter().position(|b| *b == b'\n').map_or(bytes.len(), |n| n + 1);
                ensure!(line.len() + count <= MAX_REQUEST, "Native request is too large.");
                line.extend_from_slice(&bytes[..count]);
                reader.consume(count);
                if line.last() == Some(&b'\n') { break; }
            }
            if line.is_empty() { break; }
            let result = match serde_json::from_slice::<Request>(&line) {
                Ok(request) => tokio::select! {
                    response = host.request(request, &owner) => response,
                    disconnected = reader.fill_buf() => {
                        let _ = disconnected?;
                        // This private protocol is deliberately serial. EOF
                        // or pipelining cancels the action and closes its SDK
                        // session in the common cleanup below.
                        break;
                    }
                },
                Err(_) => Err(anyhow::anyhow!("Malformed native host request.")),
            };
            let response = match result {
                Ok(value) => json!({"ok": true, "result": value}),
                Err(error) => json!({"ok": false, "error": error.to_string()}),
            };
            writer.write_all(response.to_string().as_bytes()).await?;
            writer.write_all(b"\n").await?;
        }
        Ok::<(), anyhow::Error>(())
    }.await;
    let mut active = host.active.lock().await;
    if active.as_ref().is_some_and(|a| a.owner == owner) { active.take(); }
    outcome
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args == ["--version"] { println!("nanobot-computer-use 0.1.0"); return Ok(()); }
    ensure!(args.len() == 4 && args[0] == "--socket" && args[2] == "--mode" && ["observe", "control"].contains(&args[3].as_str()), "Launch through nanobot Apps to select a gateway and access mode.");
    let socket = PathBuf::from(&args[1]);
    let parent = socket.parent().ok_or_else(|| anyhow::anyhow!("Missing socket directory."))?;
    use std::os::unix::fs::MetadataExt;
    let meta = std::fs::symlink_metadata(parent)?;
    ensure!(meta.is_dir() && meta.uid() == unsafe { libc::getuid() } && meta.mode() & 0o077 == 0, "Socket directory must be private to this user.");
    let executable = std::env::current_exe()?;
    let themes = executable.parent().unwrap().parent().unwrap().join("Resources/cursor-themes");
    // Process-entry only; no worker exists yet. No global Cua settings change.
    std::env::set_var("CUA_DRIVER_CURSOR_THEME_DIR", themes);
    ensure!(cursor_overlay::load_installed_theme("io.nanobot.computer-use")?.is_some(), "Bundled cursor theme is missing.");
    let driver = CuaDriver::try_create_for_host(DriverHostOptions {
        cursor: CursorConfig { theme_id: "io.nanobot.computer-use".into(), ..CursorConfig::default() },
        host_owns_permission_ux: true, host_bundle_id: Some(APP_ID.into()),
        claude_code_compatibility: false, prepare_desktop_environment: false,
        register_host_tools: None, authorization_host: None, activity_observer: None,
    })?;
    let paused_path = socket.with_extension("paused");
    let host = Arc::new(Host { driver, control: args[3] == "control",
        revocation: Arc::new(Revocation { paused: AtomicBool::new(paused_path.exists()), path: paused_path, session: StdMutex::new(None) }), active: Mutex::new(None),
        accessibility_requested: AtomicBool::new(false), recording_requested: AtomicBool::new(false) });
    std::thread::spawn(move || {
        let runtime = tokio::runtime::Runtime::new().expect("native runtime");
        let outcome = runtime.block_on(async {
            if socket.exists() {
                ensure!(UnixStream::connect(&socket).await.is_err(), "A native host is already running.");
                std::fs::remove_file(&socket)?;
            }
            let listener = UnixListener::bind(&socket)?;
            std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
            let cleanup_host = host.clone();
            tokio::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    let mut active = cleanup_host.active.lock().await;
                    if active.as_ref().is_some_and(|a| a.touched.elapsed() > Duration::from_secs(60))
                        || cleanup_host.revocation.paused.load(Ordering::Acquire) { active.take(); }
                }
            });
            loop {
                let (stream, _) = listener.accept().await?;
                let host = host.clone();
                tokio::spawn(async move { let _ = connection(host, stream).await; });
            }
            #[allow(unreachable_code)] Ok::<(), anyhow::Error>(())
        });
        if let Err(error) = outcome { eprintln!("Computer Use: {error}"); }
        std::process::exit(1);
    });
    platform_macos::cursor::overlay::run_on_main_thread();
    Ok(())
}
