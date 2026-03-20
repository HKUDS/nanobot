use nanobot_rs::tools::{EditFileTool, ExecTool, ListDirTool, ReadFileTool, Tool};
use serde_json::json;
use tempfile::tempdir;

#[tokio::test]
async fn read_file_supports_offset_and_limit() {
    let dir = tempdir().expect("tempdir");
    let file = dir.path().join("sample.txt");
    std::fs::write(
        &file,
        (1..=10)
            .map(|idx| format!("line {idx}"))
            .collect::<Vec<_>>()
            .join("\n"),
    )
    .expect("write sample");
    let tool = ReadFileTool::new(dir.path().to_path_buf(), false);
    let result = tool
        .execute(json!({"path": file.display().to_string(), "offset": 5, "limit": 2}))
        .await;
    assert!(result.contains("5| line 5"));
    assert!(result.contains("6| line 6"));
    assert!(result.contains("Use offset=7 to continue"));
}

#[tokio::test]
async fn edit_file_preserves_crlf_and_trimmed_matching() {
    let dir = tempdir().expect("tempdir");
    let file = dir.path().join("code.py");
    std::fs::write(&file, b"    def foo():\r\n        pass\r\n").expect("write code");
    let tool = EditFileTool::new(dir.path().to_path_buf(), false);
    let result = tool
        .execute(json!({
            "path": file.display().to_string(),
            "old_text": "def foo():\n    pass",
            "new_text": "def bar():\n    return 1"
        }))
        .await;
    assert!(result.contains("Successfully"));
    let raw = std::fs::read(&file).expect("read code");
    assert!(String::from_utf8_lossy(&raw).contains("bar"));
    assert!(raw.windows(2).any(|window| window == b"\r\n"));
}

#[tokio::test]
async fn list_dir_ignores_noise_directories() {
    let dir = tempdir().expect("tempdir");
    std::fs::create_dir_all(dir.path().join(".git")).expect("git");
    std::fs::create_dir_all(dir.path().join("node_modules")).expect("node_modules");
    std::fs::create_dir_all(dir.path().join("src")).expect("src");
    std::fs::write(dir.path().join("src").join("main.rs"), "fn main() {}").expect("write main");
    let tool = ListDirTool::new(dir.path().to_path_buf(), false);
    let result = tool
        .execute(json!({"path": dir.path().display().to_string(), "recursive": true}))
        .await;
    assert!(result.contains("src/main.rs"));
    assert!(!result.contains(".git"));
    assert!(!result.contains("node_modules"));
}

#[tokio::test]
async fn exec_blocks_internal_url() {
    let dir = tempdir().expect("tempdir");
    let tool = ExecTool::new(dir.path().to_path_buf(), 5, false);
    let result = tool
        .execute(json!({"command": "curl http://localhost:8080/secret"}))
        .await;
    assert!(result.contains("internal/private URL"));
}

#[tokio::test]
async fn exec_runs_safe_commands() {
    let dir = tempdir().expect("tempdir");
    let tool = ExecTool::new(dir.path().to_path_buf(), 5, false);
    let result = tool.execute(json!({"command": "echo hello"})).await;
    assert!(result.contains("hello"));
}
