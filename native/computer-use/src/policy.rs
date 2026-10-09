//! The transport accepts only the same finite desktop surface as nanobot.
//! A window observation is required before input; desktop-wide calls are absent.
use anyhow::{bail, ensure, Result};
use serde_json::Value;

pub const OBSERVE: &[&str] = &["list_windows", "get_window_state", "get_accessibility_tree", "zoom"];
pub const CONTROL: &[&str] = &["click", "double_click", "right_click", "scroll", "drag", "move_cursor", "type_text", "press_key", "hotkey", "set_value", "bring_to_front"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Target {
    pub pid: i32,
    pub window: u32,
}

pub fn target(arguments: &Value) -> Result<Target> {
    let pid = arguments.get("pid").and_then(Value::as_i64).and_then(|v| i32::try_from(v).ok());
    let window = arguments.get("window_id").and_then(Value::as_u64).and_then(|v| u32::try_from(v).ok());
    match (pid, window) {
        (Some(pid), Some(window)) if pid > 0 && window > 0 => Ok(Target { pid, window }),
        _ => bail!("Choose a window from list_windows and pass its pid and window_id."),
    }
}

pub fn validate(name: &str, args: &mut Value, control: bool, paused: bool) -> Result<()> {
    ensure!(!paused, "Sharing was stopped. Ask the user to reconnect Computer Use in Apps; do not retry or use another desktop tool.");
    ensure!(OBSERVE.contains(&name) || (control && CONTROL.contains(&name)), "This tool is not allowed by the current desktop access.");
    let args = args.as_object_mut().ok_or_else(|| anyhow::anyhow!("Arguments must be an object."))?;
    // Session identities and host authority are never chosen by the model.
    args.retain(|key, _| !key.starts_with('_') && key != "session");
    ensure!(args.get("scope").is_none_or(|v| v == "window"), "Only window-scoped desktop access is supported.");
    ensure!(args.get("screenshot_out_file").is_none(), "Screenshots are returned in memory, not saved to disk.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn stop_and_observe_deny_input_before_dispatch() {
        for name in OBSERVE.iter().chain(CONTROL) {
            assert!(validate(name, &mut json!({}), true, true).is_err());
        }
        assert!(validate("click", &mut json!({}), false, false).is_err());
        assert!(validate("get_window_state", &mut json!({}), false, false).is_ok());
        assert!(validate("screenshot", &mut json!({}), true, false).is_err());
    }

    #[test]
    fn window_identity_and_transport_authority_cannot_be_substituted() {
        assert!(target(&json!({"pid": -1, "window_id": 2})).is_err());
        assert!(target(&json!({"pid": 10, "window_id": 4294967296_u64})).is_err());
        assert_eq!(target(&json!({"pid": 10, "window_id": 2})).unwrap(), Target { pid: 10, window: 2 });
        let mut args = json!({"session": "another", "_trusted": true, "pid": 10});
        validate("click", &mut args, true, false).unwrap();
        assert_eq!(args, json!({"pid": 10}));
        assert!(validate("click", &mut json!({"scope": "desktop"}), true, false).is_err());
        assert!(validate("get_window_state", &mut json!({"screenshot_out_file": "/tmp/shot.png"}), true, false).is_err());
    }
}
