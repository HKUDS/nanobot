use nanobot_rs::session::{Session, SessionMessage};
use serde_json::json;

fn tool_turn(prefix: &str, idx: usize) -> Vec<SessionMessage> {
    vec![
        SessionMessage {
            role: "assistant".to_string(),
            content: serde_json::Value::Null,
            timestamp: None,
            tool_calls: Some(vec![
                json!({"id": format!("{prefix}_{idx}_a"), "type": "function", "function": {"name": "x", "arguments": "{}"}}),
                json!({"id": format!("{prefix}_{idx}_b"), "type": "function", "function": {"name": "y", "arguments": "{}"}}),
            ]),
            tool_call_id: None,
            name: None,
        },
        SessionMessage {
            role: "tool".to_string(),
            content: json!("ok"),
            timestamp: None,
            tool_calls: None,
            tool_call_id: Some(format!("{prefix}_{idx}_a")),
            name: Some("x".to_string()),
        },
        SessionMessage {
            role: "tool".to_string(),
            content: json!("ok"),
            timestamp: None,
            tool_calls: None,
            tool_call_id: Some(format!("{prefix}_{idx}_b")),
            name: Some("y".to_string()),
        },
    ]
}

fn assert_no_orphans(history: &[serde_json::Value]) {
    let declared = history
        .iter()
        .filter(|message| message.get("role").and_then(|role| role.as_str()) == Some("assistant"))
        .flat_map(|message| {
            message
                .get("tool_calls")
                .and_then(|calls| calls.as_array())
                .cloned()
                .unwrap_or_default()
        })
        .filter_map(|call| {
            call.get("id")
                .and_then(|id| id.as_str())
                .map(str::to_string)
        })
        .collect::<std::collections::HashSet<_>>();
    for message in history {
        if message.get("role").and_then(|role| role.as_str()) == Some("tool") {
            let id = message
                .get("tool_call_id")
                .and_then(|id| id.as_str())
                .unwrap();
            assert!(declared.contains(id), "orphan tool result: {id}");
        }
    }
}

#[test]
fn get_history_drops_orphan_tool_results() {
    let mut session = Session::new("cli:test");
    session.messages.push(SessionMessage {
        role: "user".to_string(),
        content: json!("old"),
        timestamp: None,
        tool_calls: None,
        tool_call_id: None,
        name: None,
    });
    for index in 0..20 {
        session.messages.extend(tool_turn("old", index));
    }
    session.messages.push(SessionMessage {
        role: "user".to_string(),
        content: json!("new"),
        timestamp: None,
        tool_calls: None,
        tool_call_id: None,
        name: None,
    });
    for index in 0..25 {
        session.messages.extend(tool_turn("cur", index));
    }
    let history = session.get_history(100);
    assert_no_orphans(&history);
}

#[test]
fn history_keeps_legitimate_tool_pairs() {
    let mut session = Session::new("cli:ok");
    session.messages.push(SessionMessage {
        role: "user".to_string(),
        content: json!("hello"),
        timestamp: None,
        tool_calls: None,
        tool_call_id: None,
        name: None,
    });
    for index in 0..5 {
        session.messages.extend(tool_turn("ok", index));
    }
    let history = session.get_history(500);
    assert_eq!(
        history
            .iter()
            .filter(|message| message.get("role").and_then(|role| role.as_str()) == Some("tool"))
            .count(),
        10
    );
    assert_no_orphans(&history);
}
