[Setup]
AppName=Lumina
AppVersion=2.5.0
DefaultDirName={autopf}\LuminaC2
DefaultGroupName=Lumina C2
OutputDir=installers
OutputBaseFilename=LuminaC2_Installer_v2.5.0
Compression=lzma2
SolidCompression=yes
SetupIconFile=windows\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\lumina_c2.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkablealone

[Files]
; --- Flutter GUI ---
Source: "build\windows\x64\runner\Release\lumina_c2.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Python backend services ---
Source: "c2_server.py";                DestDir: "{app}\backend"; Flags: ignoreversion
Source: "bitnet_server_windows.py";    DestDir: "{app}\backend"; Flags: ignoreversion
Source: "bitnet_client.py";            DestDir: "{app}\backend"; Flags: ignoreversion
Source: "perplexica_compat_server.py"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "perplexica_client.py";        DestDir: "{app}\backend"; Flags: ignoreversion
Source: "perplexity_client.py";        DestDir: "{app}\backend"; Flags: ignoreversion
Source: "orchestrator.py";             DestDir: "{app}\backend"; Flags: ignoreversion
Source: "memory_manager.py";           DestDir: "{app}\backend"; Flags: ignoreversion
Source: "model_router.py";             DestDir: "{app}\backend"; Flags: ignoreversion
Source: "nvidia_client.py";            DestDir: "{app}\backend"; Flags: ignoreversion
Source: "obsidian_client.py";          DestDir: "{app}\backend"; Flags: ignoreversion
Source: "secrets_client.py";           DestDir: "{app}\backend"; Flags: ignoreversion
Source: "situational_awareness.py";    DestDir: "{app}\backend"; Flags: ignoreversion
Source: "task_manager.py";             DestDir: "{app}\backend"; Flags: ignoreversion
Source: "trigger_engine.py";           DestDir: "{app}\backend"; Flags: ignoreversion
Source: "local_agent.py";              DestDir: "{app}\backend"; Flags: ignoreversion
Source: "requirements.txt";            DestDir: "{app}\backend"; Flags: ignoreversion
Source: "identity_config.py";          DestDir: "{app}\backend"; Flags: ignoreversion

; --- Local LLM models (Qwen GGUF) ---
Source: "models\qwen\qwen2.5-0.5b-instruct-q4_k_m.gguf"; DestDir: "{app}\models\qwen"; Flags: ignoreversion
Source: "models\qwen\qwen2.5-1.5b-instruct-q4_k_m.gguf"; DestDir: "{app}\models\qwen"; Flags: ignoreversion

; --- PowerShell management scripts ---
Source: "start_local_stack_qwen.ps1";  DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "stop_local_stack_qwen.ps1";   DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "check_local_stack_qwen.ps1";  DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "smoke_test_install.ps1";      DestDir: "{app}\scripts"; Flags: ignoreversion

; --- Vendor libraries ---
Source: "vendor\speech_to_text_windows\*"; DestDir: "{app}\vendor\speech_to_text_windows"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Lumina C2"; Filename: "{app}\lumina_c2.exe"
Name: "{autodesktop}\Lumina C2"; Filename: "{app}\lumina_c2.exe"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\start_local_stack_qwen.ps1"""; Description: "Start local Lumina backend stack"; Flags: runhidden nowait postinstall skipifsilent
Filename: "{app}\lumina_c2.exe"; Description: "{cm:LaunchProgram,Lumina C2}"; Flags: nowait postinstall skipifsilent
