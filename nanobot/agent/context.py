"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.language import detect_language, detect_language_from_session


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace) if not isinstance(workspace, Path) else workspace
        self.memory = MemoryStore(self.workspace)
        self.skills = SkillsLoader(self.workspace)
    
    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        profile: str | None = None,
        memory_isolation: str = "shared",
        inherit_global_skills: bool = True,
        language: str = "en",
    ) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.
            profile: Optional profile name for profile-specific memory and skills.
            memory_isolation: Memory isolation mode ("shared", "isolated", "hierarchical").
            inherit_global_skills: Whether to also load workspace and built-in skills.
            language: Language code for localized identity ('vi', 'zh', 'ja', 'ko', 'es', 'fr', 'de', 'en').

        Returns:
            Complete system prompt.
        """
        parts = []

        # Core identity (with language support)
        parts.append(self._get_identity(profile=profile, language=language))

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory context (profile-aware)
        memory_store = MemoryStore(self.workspace, profile=profile)
        memory = memory_store.get_memory_context(
            isolation=memory_isolation,
            include_global=memory_isolation == "hierarchical",
        )
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Skills - progressive loading (profile-aware)
        profile_skills = SkillsLoader(
            self.workspace,
            profile=profile,
            inherit_global_skills=inherit_global_skills,
        )

        # 1. Always-loaded skills: include full content
        always_skills = profile_skills.get_always_skills()
        if always_skills:
            always_content = profile_skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = profile_skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self, profile: str | None = None, language: str = "en") -> str:
        """Get the core identity section with language support."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        profile_info = f"\n## Profile\n{profile}" if profile else ""
        memory_path = f"{workspace_path}/memory/profiles/{profile}/MEMORY.md" if profile else f"{workspace_path}/memory/MEMORY.md"
        history_path = f"{workspace_path}/memory/profiles/{profile}/HISTORY.md" if profile else f"{workspace_path}/memory/HISTORY.md"

        # Localized identity messages
        identity_messages = {
            'vi': """# nanobot 🐈

Bạn là nanobot, một trợ lý AI hữu ích. Bạn có quyền truy cập vào các công cụ cho phép bạn:
- Đọc, ghi và chỉnh sửa tệp
- Thực thi lệnh shell
- Tìm kiếm web và tải trang web
- Gửi tin nhắn cho người dùng trên các kênh chat
- Tạo tác nhân con cho các tác vụ phức tạp trong nền""",
            'zh': """# nanobot 🐈

你是 nanobot，一个有用的 AI 助手。你可以访问以下工具：
- 读取、写入和编辑文件
- 执行 shell 命令
- 搜索网页和获取网页内容
- 在聊天频道上向用户发送消息
- 为复杂的后台任务生成子代理""",
            'ja': """# nanobot 🐈

あなたは nanobot という、役立つ AI アシスタントです。以下のツールにアクセスできます：
- ファイルの読み取り、書き込み、編集
- シェルコマンドの実行
- Web 検索と Web ページの取得
- チャットチャネルでユーザーにメッセージを送信
- 複雑なバックグラウンドタスクのサブエージェントの生成""",
            'ko': """# nanobot 🐈

당신은 nanobot라는 유용한 AI 어시스턴트입니다. 다음 도구에 액세스할 수 있습니다:
- 파일 읽기, 쓰기 및 편집
- 셸 명령 실행
- 웹 검색 및 웹 페이지 가져오기
- 채팅 채널에서 사용자에게 메시지 보내기
- 복잡한 백그라운드 작업을 위한 하위 에이전트 생성""",
            'es': """# nanobot 🐈

Eres nanobot, un asistente de IA útil. Tienes acceso a herramientas que te permiten:
- Leer, escribir y editar archivos
- Ejecutar comandos de shell
- Buscar en la web y obtener páginas web
- Enviar mensajes a usuarios en canales de chat
- Generar subagentes para tareas complejas en segundo plano""",
            'fr': """# nanobot 🐈

Vous êtes nanobot, un assistant IA utile. Vous avez accès à des outils qui vous permettent de :
- Lire, écrire et modifier des fichiers
- Exécuter des commandes shell
- Rechercher sur le web et récupérer des pages web
- Envoyer des messages aux utilisateurs sur les canaux de chat
- Générer des sous-agents pour des tâches complexes en arrière-plan""",
            'de': """# nanobot 🐈

Sie sind nanobot, ein nützlicher KI-Assistent. Sie haben Zugriff auf Tools, mit denen Sie:
- Dateien lesen, schreiben und bearbeiten können
- Shell-Befehle ausführen können
- Im Web suchen und Webseiten abrufen können
- Benutzern in Chat-Kanälen Nachrichten senden können
- Subagenten für komplexe Hintergrundaufgaben generieren können""",
            'en': """# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks""",
        }

        # Localized tool instructions
        tool_instructions = {
            'vi': """
## Hướng dẫn quan trọng
- Khi trả lời câu hỏi trực tiếp hoặc trò chuyện, hãy trả lời trực tiếp bằng văn bản.
- Chỉ sử dụng công cụ 'message' khi bạn cần gửi tin nhắn đến kênh chat cụ thể (như WhatsApp).
- For normal conversation, just respond with text - do not call the message tool.
- Luôn hữu ích, chính xác và ngắn gọn. Trước khi gọi công cụ, hãy cho người dùng biết bạn sắp làm gì (một câu ngắn bằng ngôn ngữ của họ).
- Khi nhớ điều gì đó quan trọng, hãy ghi vào {workspace_path}/memory/MEMORY.md
- Để nhớ lại các sự kiện trong quá khứ, grep {workspace_path}/memory/HISTORY.md""",
            'zh': """
## 重要说明
- 回答直接问题或对话时，请直接用文本回复。
- 仅在需要向特定聊天频道（如 WhatsApp）发送消息时才使用 'message' 工具。
- 对于正常对话，只需用文本回复 - 不要调用消息工具。
- 始终保持乐于助人、准确和简洁。在调用工具之前，简要告诉用户您将要做什么（用用户语言的一个短句）。
- 记住重要事项时，请写入 {workspace_path}/memory/MEMORY.md
- 回忆过去的事件，请使用 grep {workspace_path}/memory/HISTORY.md""",
            'ja': """
## 重要な指示
- 直接的な質問や会話に答えるときは、テキストで直接返答してください。
- 特定のチャットチャネル（WhatsApp など）にメッセージを送信する必要がある場合にのみ、'message' ツールを使用してください。
- 通常の会話では、テキストで応答してください - メッセージツールを呼び出さないでください。
- 常に役に立ち、正確で簡潔に。ツールを呼び出す前に、何をするかをユーザーに簡潔に伝えてください（ユーザーの言語で短い一文で）。
- 重要なことを覚えるときは、{workspace_path}/memory/MEMORY.md に書き込んでください
- 過去のイベントを思い出すには、{workspace_path}/memory/HISTORY.md を grep してください""",
            'ko': """
## 중요 지침
- 직접적인 질문이나 대화에 답할 때는 텍스트로 직접 응답하세요.
- 특정 채팅 채널(WhatsApp 등)에 메시지를 보내야 할 때만 'message' 도구를 사용하세요.
- 일반 대화에서는 텍스트로 응닡하세요 - 메시지 도구를 호출하지 마세요.
- 항상 유용하고 정확하며 간결하게. 도구를 호출하기 전에 사용자에게 무엇을 할 것인지 간략히 알려주세요(사용자 언어로 짧은 문장 하나).
- 중요한 것을 기억할 때는 {workspace_path}/memory/MEMORY.md에 작성하세요
- 과거 이벤트를 기억하려면 {workspace_path}/memory/HISTORY.md을 grep 하세요""",
            'es': """
## Instrucciones importantes
- Al responder preguntas directas o conversaciones, responde directamente con tu respuesta de texto.
- Solo usa la herramienta 'message' cuando necesites enviar un mensaje a un canal de chat específico (como WhatsApp).
- Para conversación normal, solo responde con texto - no llames a la herramienta de mensaje.
- Sé siempre útil, preciso y conciso. Antes de llamar herramientas, dile brevemente al usuario lo que vas a hacer (una oración corta en el idioma del usuario).
- Al recordar algo importante, escribe en {workspace_path}/memory/MEMORY.md
- Para recordar eventos pasados, usa grep en {workspace_path}/memory/HISTORY.md""",
            'fr': """
## Instructions importantes
- Lorsque vous répondez à des questions directes ou des conversations, répondez directement avec votre réponse textuelle.
- N'utilisez l'outil 'message' que lorsque vous devez envoyer un message à un canal de chat spécifique (comme WhatsApp).
- Pour une conversation normale, répondez simplement avec du texte - n'appelez pas l'outil de message.
- Soyez toujours utile, précis et concis. Avant d'appeler des outils, dites brièvement à l'utilisateur ce que vous allez faire (une phrase courte dans la langue de l'utilisateur).
- En vous souvenant de quelque chose d'important, écrivez dans {workspace_path}/memory/MEMORY.md
- Pour rappeler des événements passés, utilisez grep sur {workspace_path}/memory/HISTORY.md""",
            'de': """
## Wichtige Anweisungen
- Wenn Sie auf direkte Fragen oder Gespräche antworten, antworten Sie direkt mit Ihrer Textantwort.
- Verwenden Sie das 'message'-Tool nur, wenn Sie eine Nachricht an einen spezifischen Chat-Kanal (wie WhatsApp) senden müssen.
- Für normale Unterhaltung antworten Sie einfach mit Text - rufen Sie nicht das Nachricht-Tool auf.
- Seien Sie immer hilfreich, genau und prägnant. Rufen Sie kurz vor dem Aufrufen von Tools dem Benutzer mitzuteilen, was Sie vorhaben (ein kurzer Satz in der Sprache des Benutzers).
- Wenn Sie etwas Wichtiges merken, schreiben Sie in {workspace_path}/memory/MEMORY.md
- Um vergangene Ereignisse abzurufen, verwenden Sie grep für {workspace_path}/memory/HISTORY.md""",
            'en': f"""
IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. Before calling tools, briefly tell the user what you're about to do (one short sentence in the user's language).
When remembering something important, write to {workspace_path}/memory/MEMORY.md
To recall past events, grep {workspace_path}/memory/HISTORY.md""",
        }

        identity = identity_messages.get(language, identity_messages['en'])
        instructions = tool_instructions.get(language, tool_instructions['en'])

        return f"""{identity}
{profile_info}
## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {memory_path}
- History log: {history_path} (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md
{instructions}"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        system_prompt: str | None = None,
        profile_inherit_base: bool = True,
        profile: str | None = None,
        memory_isolation: str = "shared",
        inherit_global_skills: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.
            system_prompt: Optional custom system prompt.
            profile_inherit_base: Whether to merge custom prompt with base prompt.
            profile: Optional profile name for profile-specific memory.
            memory_isolation: Memory isolation mode ("shared", "isolated", "hierarchical").
            inherit_global_skills: Whether to also load workspace and built-in skills.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # Detect user language early (before building system prompt)
        detected_lang = detect_language_from_session(history + [{"role": "user", "content": current_message}])

        # System prompt (with language support)
        base_system_prompt = self.build_system_prompt(
            skill_names=skill_names,
            profile=profile,
            memory_isolation=memory_isolation,
            inherit_global_skills=inherit_global_skills,
            language=detected_lang,
        )

        # Handle custom system prompt
        if system_prompt:
            if profile_inherit_base:
                # Merge: base prompt first, then custom additions
                final_system_prompt = f"{base_system_prompt}\n\n## Additional Instructions\n{system_prompt}"
            else:
                # Replace entirely
                final_system_prompt = system_prompt
        else:
            final_system_prompt = base_system_prompt

        if channel and chat_id:
            final_system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"

        messages.append({"role": "system", "content": final_system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text
        
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.
        
        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.
        
        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
            reasoning_content: Thinking output (Kimi, DeepSeek-R1, etc.).
        
        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant"}

        # Always include content — some providers (e.g. StepFun) reject
        # assistant messages that omit the key entirely.
        msg["content"] = content

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Include reasoning content when provided (required by some thinking models)
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content

        messages.append(msg)
        return messages
