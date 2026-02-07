"""
Onboarding Service for nanobot

This module handles the automatic setup message sending when the gateway
is first initialized. It collects basic identity information for both the
bot (SOUL.md) and the user (USER.md).
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional


class OnboardingService:
    """
    Service for managing the initial onboarding process.
    
    This service handles:
    - Detecting first-run initialization
    - Sending setup welcome messages
    - Parsing user responses
    - Updating USER.md and SOUL.md files
    - Marking onboarding as complete
    """
    
    # Setup message template
    SETUP_MESSAGE = """👋 Welcome to nanobot! Let's get to know each other.

Before we start, I need to learn a bit about you:

**About You:**
1. What's your name?
2. What's your timezone?
3. What's your preferred language?
4. What's your primary role or what do you do?

**About Me (nanobot):**
5. What would you like to call me?
6. How should I address you - formally or casually?

Please answer these questions, and I'll remember them for future conversations! 😊"""
    
    # Placeholder patterns to detect unfilled files
    PLACEHOLDER_PATTERNS = {
        "name": r"\(your name\)",
        "timezone": r"\(your timezone",
        "language": r"\(preferred language\)",
        "role": r"\(your role",
    }
    
    def __init__(self, data_dir: str = "workspace"):
        """
        Initialize the onboarding service.
        
        Args:
            data_dir: Base directory for data files (default: "workspace")
        """
        self.data_dir = Path(data_dir)
        self.user_file = self.data_dir / "USER.md"
        self.soul_file = self.data_dir / "SOUL.md"
        self.marker_file = self.data_dir / ".nanobot_initialized"
    
    def is_first_run(self) -> bool:
        """
        Detect if this is the first time the gateway is initializing.
        
        Returns:
            bool: True if this is a first run, False otherwise
        """
        # Check if marker file exists
        if self.marker_file.exists():
            return False
        
        # Check if USER.md/SOUL.md contain placeholder values
        if self._has_placeholders(self.user_file):
            return True
        
        # If USER.md doesn't exist, it's also a first run
        if not self.user_file.exists():
            return True
        
        return False
    
    def _has_placeholders(self, file_path: Path) -> bool:
        """
        Check if a file contains placeholder values.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            bool: True if placeholders are found, False otherwise
        """
        if not file_path.exists():
            return True
        
        try:
            content = file_path.read_text(encoding="utf-8")
            # Check for common placeholder patterns
            placeholders = [
                "(your name)",
                "(your timezone",
                "(preferred language)",
                "(your role",
                "(what you're working on)",
                "(IDEs, languages, frameworks)",
            ]
            return any(p.lower() in content.lower() for p in placeholders)
        except (IOError, OSError):
            # If we can't read the file, assume it's unfilled
            return True
    
    def check_and_notify(
        self,
        channel_name: str,
        chat_id: str,
        send_message_callback: Callable[[str, str, str], None]
    ) -> bool:
        """
        Send setup message if this is the first run.
        
        Args:
            channel_name: Name of the channel to send to
            chat_id: Chat/room ID to send to
            send_message_callback: Callable that takes (channel_name, chat_id, message)
            
        Returns:
            bool: True if message was sent, False otherwise
        """
        if not self.is_first_run():
            return False
        
        send_message_callback(channel_name, chat_id, self.SETUP_MESSAGE)
        return True
    
    def parse_response(self, response: str) -> Dict[str, str]:
        """
        Parse natural language response to extract user information.
        
        Args:
            response: The user's response text
            
        Returns:
            dict: Dictionary containing extracted information
        """
        result = {
            "name": "",
            "timezone": "",
            "language": "",
            "role": "",
            "bot_name": "",
            "formality": "",
        }
        
        response_lower = response.lower()
        lines = response.split('\n')
        
        # Extract name patterns
        name_patterns = [
            r"my name is\s+(\w+(?:\s+\w+)*)",
            r"i'?m\s+(\w+(?:\s+\w+)*)",
            r"i am\s+(\w+(?:\s+\w+)*)",
            r"name[:\s]+(\w+(?:\s+\w+)*)",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, response_lower)
            if match:
                result["name"] = match.group(1).title()
                break
        
        # Extract timezone patterns
        timezone_patterns = [
            r"(utc[+-]?\d+)",
            r"(gmt[+-]?\d+)",
            r"(eastern|central|mountain|pacific)\s*(time)?",
            r"(europe/london|europe/paris|europe/berlin|asia/tokyo|asia/shanghai|australia/sydney)",
            r"timezone[:\s]*([^\n,]+)",
        ]
        for pattern in timezone_patterns:
            match = re.search(pattern, response_lower)
            if match:
                tz = match.group(1).strip()
                # Clean up and format
                tz = tz.replace("time", "").strip()
                result["timezone"] = tz.title() if "/" not in tz else tz
                break
        
        # Extract language patterns
        languages = [
            "english", "spanish", "french", "german", "chinese", "japanese",
            "korean", "portuguese", "russian", "arabic", "hindi", "dutch",
            "italian", "polish", "turkish", "vietnamese", "thai"
        ]
        for lang in languages:
            if lang in response_lower:
                result["language"] = lang.title()
                break
        # Also check for "language: X" pattern
        lang_match = re.search(r"language[:\s]+(\w+)", response_lower)
        if lang_match and not result["language"]:
            potential_lang = lang_match.group(1).title()
            if potential_lang.lower() in [l.lower() for l in languages]:
                result["language"] = potential_lang
        
        # Extract role patterns
        roles = [
            "developer", "engineer", "designer", "manager", "researcher",
            "student", "teacher", "analyst", "consultant", "admin",
            "product manager", "project manager", "data scientist", "devops",
            "frontend", "backend", "fullstack", "software architect", "cto",
            "ceo", "founder", "entrepreneur", "freelancer", "contractor"
        ]
        for role in roles:
            if role in response_lower:
                result["role"] = role.title()
                break
        # Also check for "role: X" pattern
        role_match = re.search(r"(?:role|occupation|job)[:\s]+([^\n,]+)", response_lower)
        if role_match and not result["role"]:
            result["role"] = role_match.group(1).strip().title()
        
        # Extract bot name patterns
        bot_name_patterns = [
            r"call you\s+(\w+)",
            r"my bot[:\s]+(\w+)",
            r"bot name[:\s]+(\w+)",
            r"name.*[:\s]+(\w+)",
        ]
        # Look in the last few lines for bot name (usually question 5)
        last_part = "\n".join(lines[-3:])
        for pattern in bot_name_patterns:
            match = re.search(pattern, last_part, re.IGNORECASE)
            if match:
                result["bot_name"] = match.group(1)
                break
        
        # Extract formality patterns
        if any(word in response_lower for word in ["formal", "professionally", "mr", "ms", "dr"]):
            result["formality"] = "Formal"
        elif any(word in response_lower for word in ["casual", "informal", "friendly", "just", "first name"]):
            result["formality"] = "Casual"
        
        # Check for specific answer patterns (Q5 and Q6 often have numbers)
        numbered_match = re.search(r"5\.\s*([^\n]+)", response)
        if numbered_match:
            line5 = numbered_match.group(1).lower()
            if not result["bot_name"]:
                # Extract bot name from "call me X" or similar
                call_match = re.search(r"(?:call|called|name is)\s+(\w+)", line5)
                if call_match:
                    result["bot_name"] = call_match.group(1)
        
        numbered_match = re.search(r"6\.\s*([^\n]+)", response)
        if numbered_match:
            line6 = numbered_match.group(1).lower()
            if any(word in line6 for word in ["formal", "professionally"]):
                result["formality"] = "Formal"
            elif any(word in line6 for word in ["casual", "informal", "friendly"]):
                result["formality"] = "Casual"
        
        return result
    
    def update_user_file(self, data: Dict[str, str]) -> bool:
        """
        Update USER.md with the parsed user information.
        
        Args:
            data: Dictionary containing user information
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            # Read existing file or create new content
            if self.user_file.exists():
                content = self.user_file.read_text(encoding="utf-8")
            else:
                content = self._get_default_user_content()
            
            # Update placeholders with actual values
            if data.get("name"):
                content = re.sub(
                    r"- \*\*Name\*\*:.*",
                    f"- **Name**: {data['name']}",
                    content
                )
            
            if data.get("timezone"):
                content = re.sub(
                    r"- \*\*Timezone\*\*:.*",
                    f"- **Timezone**: {data['timezone']}",
                    content
                )
            
            if data.get("language"):
                content = re.sub(
                    r"- \*\*Language\*\*:.*",
                    f"- **Language**: {data['language']}",
                    content
                )
            
            if data.get("role"):
                content = re.sub(
                    r"- \*\*Primary Role\*\*:.*",
                    f"- **Primary Role**: {data['role']}",
                    content
                )
            
            # Write updated content
            self.user_file.write_text(content, encoding="utf-8")
            return True
            
        except (IOError, OSError) as e:
            print(f"Error updating USER.md: {e}")
            return False
    
    def update_soul_file(self, data: Dict[str, str]) -> bool:
        """
        Update SOUL.md with the bot configuration.
        
        Args:
            data: Dictionary containing bot configuration
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            # Read existing file or create new content
            if self.soul_file.exists():
                content = self.soul_file.read_text(encoding="utf-8")
            else:
                content = self._get_default_soul_content()
            
            # Update bot name
            if data.get("bot_name"):
                content = re.sub(
                    r"I am nanobot",
                    f"I am {data['bot_name']}",
                    content
                )
            
            # Update communication style based on formality
            if data.get("formality") == "Formal":
                content = re.sub(
                    r"- \*\*Communication Style\*\*.*\n.*\n.*\n.*\n.*",
                    "- **Communication Style**\n- Formal and respectful\n- Use titles when appropriate\n- Professional tone",
                    content
                )
            elif data.get("formality") == "Casual":
                content = re.sub(
                    r"- \*\*Communication Style\*\*.*\n.*\n.*\n.*\n.*",
                    "- **Communication Style**\n- Friendly and casual\n- First-name basis\n- Relaxed tone",
                    content
                )
            
            # Write updated content
            self.soul_file.write_text(content, encoding="utf-8")
            return True
            
        except (IOError, OSError) as e:
            print(f"Error updating SOUL.md: {e}")
            return False
    
    def mark_complete(self) -> bool:
        """
        Create marker file after successful onboarding.
        
        Returns:
            bool: True if marker was created successfully, False otherwise
        """
        try:
            timestamp = datetime.now().isoformat()
            content = f"""# Nanobot Initialization Marker

This file indicates that the onboarding process has been completed.

Timestamp: {timestamp}
Status: Initialized

For more information, see the onboarding documentation.
"""
            self.marker_file.write_text(content, encoding="utf-8")
            return True
            
        except (IOError, OSError) as e:
            print(f"Error creating marker file: {e}")
            return False
    
    def _get_default_user_content(self) -> str:
        """
        Get default content for USER.md if it doesn't exist.
        
        Returns:
            str: Default USER.md content
        """
        return """# User Profile

Information about the user to help personalize interactions.

## Basic Information

- **Name**: (your name)
- **Timezone**: (your timezone, e.g., UTC+8)
- **Language**: (preferred language)

## Preferences

### Communication Style

- [ ] Casual
- [ ] Professional
- [ ] Technical

### Response Length

- [ ] Brief and concise
- [ ] Detailed explanations
- [ ] Adaptive based on question

### Technical Level

- [ ] Beginner
- [ ] Intermediate
- [ ] Expert

## Work Context

- **Primary Role**: (your role, e.g., developer, researcher)
- **Main Projects**: (what you're working on)
- **Tools You Use**: (IDEs, languages, frameworks)

## Topics of Interest

- 
- 
- 

## Special Instructions

(Any specific instructions for how the assistant should behave)

---

*Edit this file to customize nanobot's behavior for your needs.*
"""
    
    def _get_default_soul_content(self) -> str:
        """
        Get default content for SOUL.md if it doesn't exist.
        
        Returns:
            str: Default SOUL.md content
        """
        return """# Soul

I am nanobot 🐈, a personal AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions

## Communication Style

- Be clear and direct
- Explain reasoning when helpful
- Ask clarifying questions when needed
"""
