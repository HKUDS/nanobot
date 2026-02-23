"""Language detection and dynamic response utilities."""

import re
from pathlib import Path


# Common Vietnamese words and patterns
VIETNAMESE_INDICATORS = {
    # Common words
    'bạn', 'chào', 'cảm', 'nhờ', 'giúp', 'hỏi', 'trả', 'lời',
    'xin', 'vui', 'lòng', 'có', 'không', 'được', 'không', 'ơi',
    'tôi', 'anh', 'chị', 'em', 'con', 'mình', 'ai', 'đâu',
    # Common verbs
    'làm', 'đi', 'đến', 'về', 'muốn', 'cần', 'thích', 'biết',
    'viết', 'đọc', 'tạo', 'tìm', 'xem', 'cho', 'nhận', 'gửi',
    # Characters with diacritics (nguyên âm có dấu)
    'á', 'à', 'ả', 'ã', 'ạ', 'ă', 'â', 'ấ', 'ầ', 'ẩ', 'ẫ', 'ậ',
    'é', 'è', 'ẻ', 'ẽ', 'ẹ', 'ê', 'ế', 'ề', 'ể', 'ễ', 'ệ',
    'í', 'ì', 'ỉ', 'ĩ', 'ị',
    'ó', 'ò', 'ỏ', 'õ', 'ọ', 'ô', 'ố', 'ồ', 'ổ', 'ỗ', 'ộ', 'ơ', 'ớ', 'ờ', 'ở', 'ỡ', 'ợ',
    'ú', 'ù', 'ủ', 'ũ', 'ụ', 'ư', 'ứ', 'ừ', 'ử', 'ữ', 'ự',
    'ý', 'ỳ', 'ỷ', 'ỹ', 'ỵ', 'đ',
}

# Other language indicators (can be expanded)
CHINESE_INDICATORS = {'你', '我', '他', '她', '是', '的', '吗', '啊', '哦', '嗯'}
JAPANESE_INDICATORS = {'です', 'ます', 'ありがとう', 'すみ', 'ください', 'な', 'の', 'は', 'を', 'が'}
KOREAN_INDICATORS = {'입니다', '합니', '세요', '아요', '어요', '안녕', '감사'}
SPANISH_INDICATORS = {'hola', 'gracias', 'por', 'favor', 'buenos', 'días', 'noches', 'adiós'}
FRENCH_INDICATORS = {'bonjour', 'merci', 's\'il', 'vous', 'plaît', 'au', 'revoir'}
GERMAN_INDICATORS = {'hallo', 'danke', 'bitte', 'guten', 'tag', 'tschüss'}


def detect_language(text: str, user_md_path: Path | None = None) -> str:
    """
    Detect the language of the user's message.

    Priority:
    1. Check USER.md for explicit language preference
    2. Detect from message content using language-specific indicators
    3. Default to English

    Args:
        text: The user's message text
        user_md_path: Optional path to USER.md file

    Returns:
        Language code: 'vi', 'zh', 'ja', 'ko', 'es', 'fr', 'de', or 'en' (default)
    """
    # First check USER.md for explicit language preference
    if user_md_path and user_md_path.exists():
        try:
            content = user_md_path.read_text(encoding='utf-8').lower()
            for line in content.splitlines():
                if 'language' in line or 'ngôn ngữ' in line:
                    # Extract language preference
                    if 'vietnamese' in line or 'tiếng việt' in line or 'việt nam' in line:
                        return 'vi'
                    elif 'chinese' in line or '中文' in line or 'tiếng trung' in line:
                        return 'zh'
                    elif 'japanese' in line or '日本語' in line or 'tiếng nhật' in line:
                        return 'ja'
                    elif 'korean' in line or '한국어' in line or 'tiếng hàn' in line:
                        return 'ko'
                    elif 'spanish' in line or 'español' in line or 'tiếng tây ban nha' in line:
                        return 'es'
                    elif 'french' in line or 'français' in line or 'tiếng pháp' in line:
                        return 'fr'
                    elif 'german' in line or 'deutsch' in line or 'tiếng đức' in line:
                        return 'de'
                    elif 'english' in line or 'tiếng anh' in line:
                        return 'en'
        except Exception:
            pass

    # Detect from message content
    text_lower = text.lower()

    # Check for Vietnamese (check for words with diacritics first)
    if any(char in text_lower for char in VIETNAMESE_INDICATORS if len(char) > 2):
        return 'vi'
    # Check for Vietnamese characters with diacritics
    if re.search(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', text_lower):
        return 'vi'

    # Check for Chinese
    if any(char in text for char in CHINESE_INDICATORS):
        return 'zh'

    # Check for Japanese
    if any(pattern in text for pattern in JAPANESE_INDICATORS):
        return 'ja'

    # Check for Korean
    if any(pattern in text for pattern in KOREAN_INDICATORS):
        return 'ko'

    # Check for Spanish
    if any(word in text_lower.split() for word in SPANISH_INDICATORS):
        return 'es'

    # Check for French
    if any(pattern in text_lower for pattern in FRENCH_INDICATORS):
        return 'fr'

    # Check for German
    if any(word in text_lower.split() for word in GERMAN_INDICATORS):
        return 'de'

    # Default to English
    return 'en'


def get_bot_message(key: str, language: str, bot_name: str = "nanobot", **kwargs) -> str:
    """
    Get a bot message in the specified language.

    Args:
        key: The message key (e.g., 'start', 'new_session', 'help')
        language: Language code ('vi', 'zh', 'ja', 'ko', 'es', 'fr', 'de', 'en')
        bot_name: The name of the bot (default: 'nanobot')
        **kwargs: Optional parameters for string formatting

    Returns:
        The translated message string
    """
    messages = {
        'start': {
            'vi': '👋 Xin chào {name}! Mình là {bot_name}.\n\nGửi tin nhắn và mình sẽ phản hồi!\nNhập /help để xem các lệnh có sẵn.',
            'zh': '👋 你好 {name}! 我是 {bot_name}。\n\n给我发消息，我会回复！\n输入 /help 查看可用命令。',
            'ja': '👋 こんにちは {name}! さんは {bot_name} です。\n\nメッセージを送ると返信します！\n/help で利用可能なコマンドを確認してください。',
            'ko': '👋 안녕하세요 {name}! 저는 {bot_name}입니다.\n\n메시지를 보내주시면 응답해 드립니다!\n/help로 사용 가능한 명령을 확인하세요.',
            'es': '👋 ¡Hola {name}! Soy {bot_name}.\n\n¡Envíame un mensaje y responderé!\nEscribe /help para ver los comandos disponibles.',
            'fr': '👋 Salut {name}! Je suis {bot_name}.\n\nEnvoyez-moi un message et je répondrai!\nTapez /help pour voir les commandes disponibles.',
            'de': '👋 Hallo {name}! Ich bin {bot_name}.\n\nSenden Sie mir eine Nachricht und ich antworte!\nGeben Sie /help ein, um die verfügbaren Befehle anzuzeigen.',
            'en': '👋 Hi {name}! I\'m {bot_name}.\n\nSend me a message and I\'ll respond!\nType /help to see available commands.',
        },
        'new_session': {
            'vi': 'Phiên làm việc mới đã bắt đầu. Đang tiến hành ghi nhớ ngữ cảnh...',
            'zh': '新会话已开始。正在进行记忆整合...',
            'ja': '新しいセッションが開始されました。記憶の統合中...',
            'ko': '새 세션이 시작되었습니다. 메모리 통합 진행 중...',
            'es': 'Nueva sesión iniciada. Consolidación de memoria en progreso.',
            'fr': 'Nouvelle session démarrée. Consolidation de la mémoire en cours.',
            'de': 'Neue Sitzung gestartet. Speicherkonsolidierung läuft.',
            'en': 'New session started. Memory consolidation in progress.',
        },
        'help': {
            'vi': '🐈 Các lệnh của {bot_name}:\n/new — Bắt đầu cuộc trò chuyện mới\n/help — Hiển thị các lệnh có sẵn',
            'zh': '🐈 {bot_name} 命令:\n/new — 开始新对话\n/help — 显示可用命令',
            'ja': '🐈 {bot_name} コマンド:\n/new — 新しい会話を開始\n/help — 利用可能なコマンドを表示',
            'ko': '🐈 {bot_name} 명령어:\n/new — 새 대화 시작\n/help — 사용 가능한 명령어 표시',
            'es': '🐈 Comandos de {bot_name}:\n/new — Iniciar una nueva conversación\n/help — Mostrar comandos disponibles',
            'fr': '🐈 Commandes {bot_name}:\n/new — Démarrer une nouvelle conversation\n/help — Afficher les commandes disponibles',
            'de': '🐈 {bot_name}-Befehle:\n/new — Neue Unterhaltung starten\n/help — Verfügbare Befehle anzeigen',
            'en': '🐈 {bot_name} commands:\n/new — Start a new conversation\n/help — Show available commands',
        },
    }

    lang_messages = messages.get(key, {})
    message = lang_messages.get(language, lang_messages.get('en', 'Message not found'))

    # Include bot_name in kwargs for formatting
    format_kwargs = {'bot_name': bot_name, **kwargs}
    return message.format(**format_kwargs) if format_kwargs else message


def detect_language_from_session(history: list[dict[str, str]]) -> str:
    """
    Detect language from conversation history.

    Args:
        history: List of message dictionaries with 'role' and 'content'

    Returns:
        Detected language code or 'en' as default
    """
    for msg in reversed(history):
        if msg.get('role') == 'user':
            content = msg.get('content', '')
            if content:
                return detect_language(content)
    return 'en'
