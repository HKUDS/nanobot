use base64::Engine;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{
    Manager,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::TrayIconBuilder,
};
use tauri_plugin_global_shortcut::GlobalShortcutExt;

#[derive(Debug, Serialize)]
struct SkillInfo {
    id: String,
    name: String,
    description: String,
    source: String,
    path: String,
    deletable: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CreateSkillInput {
    workspace_path: String,
    name: String,
    description: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ImportSkillInput {
    workspace_path: String,
    source_path: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SkillPathInput {
    path: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UpdateSkillContentInput {
    path: String,
    content: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistClipboardImageInput {
    data_url: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InspectImagePathsInput {
    paths: Vec<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ImageFileInfo {
    path: String,
    name: String,
    size_bytes: u64,
    extension: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FilePathInput {
    path: String,
}

#[tauri::command]
fn get_gateway_url() -> String {
    std::env::var("NANOBOT_GATEWAY_URL").unwrap_or_else(|_| "ws://localhost:18790".to_string())
}

fn builtin_skills_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../nanobot/skills")
}

fn skill_description(skill_file: &Path) -> String {
    let Ok(content) = fs::read_to_string(skill_file) else {
        return "无描述".to_string();
    };

    if let Some(frontmatter) = content
        .strip_prefix("---\n")
        .and_then(|rest| rest.split("\n---").next())
    {
        for line in frontmatter.lines() {
            if let Some((key, value)) = line.split_once(':') {
                if key.trim() == "description" {
                    let parsed = value.trim().trim_matches('"').trim_matches('\'');
                    if !parsed.is_empty() {
                        return parsed.to_string();
                    }
                }
            }
        }
    }

    content
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty() && *line != "---")
        .unwrap_or("无描述")
        .to_string()
}

fn collect_skills_from_dir(dir: &Path, source: &str, deletable: bool) -> Vec<SkillInfo> {
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };

    let mut items = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }

        let skill_file = path.join("SKILL.md");
        if !skill_file.exists() {
            continue;
        }

        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };

        items.push(SkillInfo {
            id: format!("{source}:{name}"),
            name: name.to_string(),
            description: skill_description(&skill_file),
            source: source.to_string(),
            path: skill_file.to_string_lossy().into_owned(),
            deletable,
        });
    }

    items.sort_by(|a, b| a.name.cmp(&b.name));
    items
}

fn normalize_skill_name(name: &str) -> String {
    let mut result = String::new();
    let mut prev_dash = false;

    for ch in name.trim().chars() {
        let mapped = if ch.is_ascii_alphanumeric() {
            ch.to_ascii_lowercase()
        } else if ch == ' ' || ch == '_' || ch == '-' {
            '-'
        } else {
            continue;
        };

        if mapped == '-' {
            if !result.is_empty() && !prev_dash {
                result.push('-');
            }
            prev_dash = true;
        } else {
            result.push(mapped);
            prev_dash = false;
        }
    }

    result.trim_matches('-').to_string()
}

fn copy_dir_recursive(source: &Path, target: &Path) -> Result<(), String> {
    fs::create_dir_all(target).map_err(|err| err.to_string())?;

    for entry in fs::read_dir(source).map_err(|err| err.to_string())? {
        let entry = entry.map_err(|err| err.to_string())?;
        let entry_path = entry.path();
        let target_path = target.join(entry.file_name());

        if entry_path.is_dir() {
            copy_dir_recursive(&entry_path, &target_path)?;
        } else {
            fs::copy(&entry_path, &target_path).map_err(|err| err.to_string())?;
        }
    }

    Ok(())
}

fn resolve_skill_source(source_path: &Path) -> Result<PathBuf, String> {
    if source_path.is_dir() {
        let skill_file = source_path.join("SKILL.md");
        if skill_file.exists() {
            return Ok(source_path.to_path_buf());
        }
        return Err("导入目录中未找到 SKILL.md".to_string());
    }

    let is_skill_package = source_path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case("skill"))
        .unwrap_or(false);

    if !is_skill_package {
        return Err("仅支持导入 skill 目录或 .skill 包".to_string());
    }

    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|err| err.to_string())?
        .as_millis();
    let temp_dir = std::env::temp_dir().join(format!("nanobot-skill-import-{stamp}"));
    fs::create_dir_all(&temp_dir).map_err(|err| err.to_string())?;

    let unzip_output = Command::new("unzip")
        .arg("-q")
        .arg(source_path)
        .arg("-d")
        .arg(&temp_dir)
        .output()
        .map_err(|_| "系统缺少 unzip，暂时无法导入 .skill 包".to_string())?;

    if !unzip_output.status.success() {
        let stderr = String::from_utf8_lossy(&unzip_output.stderr);
        return Err(if stderr.trim().is_empty() {
            ".skill 包解压失败".to_string()
        } else {
            format!(".skill 包解压失败: {}", stderr.trim())
        });
    }

    let mut candidates = Vec::new();
    for entry in fs::read_dir(&temp_dir).map_err(|err| err.to_string())? {
        let entry = entry.map_err(|err| err.to_string())?;
        let entry_path = entry.path();
        if entry_path.is_dir() && entry_path.join("SKILL.md").exists() {
            candidates.push(entry_path);
        }
    }

    if let Some(first) = candidates.into_iter().next() {
        return Ok(first);
    }

    if temp_dir.join("SKILL.md").exists() {
        return Ok(temp_dir);
    }

    Err(".skill 包中未找到有效的 SKILL.md".to_string())
}

#[tauri::command]
fn list_skills(workspace_path: Option<String>) -> Result<Vec<SkillInfo>, String> {
    let builtin_dir = builtin_skills_dir();
    let mut skills = Vec::new();
    let mut workspace_names = std::collections::HashSet::new();

    if let Some(workspace_path) = workspace_path.filter(|value| !value.trim().is_empty()) {
        let workspace_dir = PathBuf::from(workspace_path).join("skills");
        let workspace_skills = collect_skills_from_dir(&workspace_dir, "workspace", true);
        for item in &workspace_skills {
            workspace_names.insert(item.name.clone());
        }
        skills.extend(workspace_skills);
    }

    for item in collect_skills_from_dir(&builtin_dir, "builtin", false) {
        if !workspace_names.contains(&item.name) {
            skills.push(item);
        }
    }

    skills.sort_by(|a, b| {
        a.source
            .cmp(&b.source)
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    Ok(skills)
}

#[tauri::command]
fn create_skill(input: CreateSkillInput) -> Result<SkillInfo, String> {
    let skill_name = normalize_skill_name(&input.name);
    if skill_name.is_empty() {
        return Err("Skill 名称不能为空".to_string());
    }

    let workspace_root = PathBuf::from(&input.workspace_path);
    if !workspace_root.exists() {
        return Err("当前 workspace 路径不存在".to_string());
    }

    let skills_dir = workspace_root.join("skills");
    let skill_dir = skills_dir.join(&skill_name);
    if skill_dir.exists() {
        return Err("同名 Skill 已存在".to_string());
    }

    fs::create_dir_all(&skill_dir).map_err(|err| err.to_string())?;

    let description = input.description.trim();
    let skill_content = format!(
        "---\nname: {skill_name}\ndescription: {}\n---\n\n# {}\n\nTODO: 在这里补充这个 Skill 的使用说明。\n",
        if description.is_empty() {
            "新建的 workspace skill"
        } else {
            description
        },
        skill_name
    );

    let skill_file = skill_dir.join("SKILL.md");
    fs::write(&skill_file, skill_content).map_err(|err| err.to_string())?;

    Ok(SkillInfo {
        id: format!("workspace:{skill_name}"),
        name: skill_name,
        description: if description.is_empty() {
            "新建的 workspace skill".to_string()
        } else {
            description.to_string()
        },
        source: "workspace".to_string(),
        path: skill_file.to_string_lossy().into_owned(),
        deletable: true,
    })
}

#[tauri::command]
fn delete_skill(workspace_path: String, name: String) -> Result<(), String> {
    let skill_name = normalize_skill_name(&name);
    if skill_name.is_empty() {
        return Err("无效的 Skill 名称".to_string());
    }

    let skill_dir = PathBuf::from(workspace_path).join("skills").join(&skill_name);
    if !skill_dir.exists() {
        return Err("Skill 不存在或已删除".to_string());
    }

    fs::remove_dir_all(skill_dir).map_err(|err| err.to_string())
}

#[tauri::command]
fn import_skill(input: ImportSkillInput) -> Result<SkillInfo, String> {
    let workspace_root = PathBuf::from(&input.workspace_path);
    if !workspace_root.exists() {
        return Err("当前 workspace 路径不存在".to_string());
    }

    let source_path = PathBuf::from(input.source_path.trim());
    if !source_path.exists() {
        return Err("导入路径不存在".to_string());
    }

    let skill_source_dir = resolve_skill_source(&source_path)?;
    let raw_name = skill_source_dir
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("imported-skill");
    let skill_name = normalize_skill_name(raw_name);
    if skill_name.is_empty() {
        return Err("无法识别导入 Skill 的名称".to_string());
    }

    let target_dir = workspace_root.join("skills").join(&skill_name);
    if target_dir.exists() {
        return Err("当前 workspace 中已存在同名 Skill".to_string());
    }

    copy_dir_recursive(&skill_source_dir, &target_dir)?;
    let target_skill = target_dir.join("SKILL.md");
    if !target_skill.exists() {
        let _ = fs::remove_dir_all(&target_dir);
        return Err("导入结果无效，缺少 SKILL.md".to_string());
    }

    Ok(SkillInfo {
        id: format!("workspace:{skill_name}"),
        name: skill_name,
        description: skill_description(&target_skill),
        source: "workspace".to_string(),
        path: target_skill.to_string_lossy().into_owned(),
        deletable: true,
    })
}

#[tauri::command]
fn read_skill_content(input: SkillPathInput) -> Result<String, String> {
    fs::read_to_string(PathBuf::from(input.path)).map_err(|err| err.to_string())
}

#[tauri::command]
fn update_skill_content(input: UpdateSkillContentInput) -> Result<(), String> {
    let target = PathBuf::from(&input.path);
    if !target.exists() {
        return Err("SKILL.md 文件不存在".to_string());
    }
    fs::write(target, input.content).map_err(|err| err.to_string())
}

#[tauri::command]
fn persist_clipboard_image(input: PersistClipboardImageInput) -> Result<String, String> {
    let Some((header, payload)) = input.data_url.split_once(',') else {
        return Err("无效的图片数据".to_string());
    };

    if !header.starts_with("data:image/") || !header.contains(";base64") {
        return Err("仅支持 base64 图片数据".to_string());
    }

    let ext = header
        .trim_start_matches("data:image/")
        .split(';')
        .next()
        .unwrap_or("png")
        .to_ascii_lowercase();

    let bytes = base64::engine::general_purpose::STANDARD
        .decode(payload)
        .map_err(|_| "图片解码失败".to_string())?;

    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|err| err.to_string())?
        .as_millis();
    let file_path = std::env::temp_dir().join(format!("nanobot-paste-{stamp}.{ext}"));
    fs::write(&file_path, bytes).map_err(|err| err.to_string())?;
    Ok(file_path.to_string_lossy().into_owned())
}

#[tauri::command]
fn inspect_image_paths(input: InspectImagePathsInput) -> Result<Vec<ImageFileInfo>, String> {
    let mut items = Vec::new();

    for raw_path in input.paths {
        let path = PathBuf::from(raw_path.trim());
        if !path.exists() || !path.is_file() {
            continue;
        }

        let metadata = fs::metadata(&path).map_err(|err| err.to_string())?;
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("image")
            .to_string();

        items.push(ImageFileInfo {
            path: path.to_string_lossy().into_owned(),
            name,
            size_bytes: metadata.len(),
            extension,
        });
    }

    Ok(items)
}

fn detect_image_mime(data: &[u8]) -> Option<&'static str> {
    if data.len() >= 8 && &data[..8] == b"\x89PNG\r\n\x1a\n" {
        return Some("image/png");
    }
    if data.len() >= 3 && &data[..3] == b"\xff\xd8\xff" {
        return Some("image/jpeg");
    }
    if data.len() >= 6 && (&data[..6] == b"GIF87a" || &data[..6] == b"GIF89a") {
        return Some("image/gif");
    }
    if data.len() >= 12 && &data[..4] == b"RIFF" && &data[8..12] == b"WEBP" {
        return Some("image/webp");
    }
    None
}

#[tauri::command]
fn load_image_preview(input: FilePathInput) -> Result<String, String> {
    let path = PathBuf::from(input.path.trim());
    if !path.exists() || !path.is_file() {
        return Err("图片文件不存在".to_string());
    }

    let bytes = fs::read(&path).map_err(|err| err.to_string())?;
    let mime = detect_image_mime(&bytes).ok_or_else(|| "不支持的图片格式".to_string())?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(bytes);
    Ok(format!("data:{mime};base64,{encoded}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            get_gateway_url,
            list_skills,
            create_skill,
            delete_skill,
            import_skill,
            read_skill_content,
            update_skill_content,
            persist_clipboard_image,
            inspect_image_paths,
            load_image_preview
        ])
        .setup(|app| {
            // --- System Tray ---
            let show_item = MenuItemBuilder::with_id("show", "显示窗口").build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "退出").build(app)?;
            let menu = MenuBuilder::new(app)
                .item(&show_item)
                .separator()
                .item(&quit_item)
                .build()?;

            let _tray = TrayIconBuilder::new()
                .tooltip("nanobot Desktop")
                .menu(&menu)
                .on_menu_event(move |app, event| {
                    match event.id().as_ref() {
                        "show" => {
                            if let Some(w) = app.get_webview_window("main") {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click { .. } = event {
                        if let Some(w) = tray.app_handle().get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // --- Global Shortcut: Cmd/Ctrl+Shift+N to show window ---
            use tauri_plugin_global_shortcut::ShortcutState;
            app.global_shortcut().on_shortcut(
                "CmdOrCtrl+Shift+N",
                move |app_handle: &tauri::AppHandle, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        if let Some(w) = app_handle.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                },
            )?;

            // --- Set window title ---
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("nanobot Desktop");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            // Minimize to tray instead of closing
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running nanobot desktop");
}
