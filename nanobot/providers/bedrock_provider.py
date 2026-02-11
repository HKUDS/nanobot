"""Native AWS Bedrock provider using boto3 Converse API."""

import asyncio
import base64
import json
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# Cross-region prefix to default region mapping.
_REGION_MAP = {
    "us": "us-east-1",
    "eu": "eu-west-1",
    "ap": "ap-northeast-1",
    "global": "us-east-1",
}

# Converse API stopReason to LLMResponse finish_reason mapping.
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
}

# Bedrock ClientError code to friendly message mapping.
_ERROR_MAP = {
    "ValidationException": "Invalid request",
    "ModelNotReadyException": "Model not enabled in Bedrock console",
    "ThrottlingException": "Rate limited",
    "AccessDeniedException": "Access denied - check IAM permissions or API key",
    "ModelTimeoutException": "Request timeout",
}


class BedrockProvider(LLMProvider):
    """
    LLM provider that calls AWS Bedrock Converse API directly via boto3.

    Supports IAM credential chain and Bedrock API Key authentication.
    Handles cross-region inference profile model IDs (us., eu., ap., global.).
    """

    def __init__(
        self,
        api_key: str | None = None,
        region: str = "us-east-1",
        model: str = "bedrock/anthropic.claude-opus-4-6-v1",
    ):
        super().__init__(api_key, None)
        self.default_model = model
        self._model_id = self._extract_model_id(model)
        self._region = self._infer_region(self._model_id) or region
        self.client = self._create_client()

    # ------------------------------------------------------------------
    # Client creation
    # ------------------------------------------------------------------

    def _create_client(self):
        """Create a boto3 bedrock-runtime client with appropriate auth."""
        if self.api_key is None:
            # IAM auth: standard credential chain
            import boto3
            return boto3.client("bedrock-runtime", region_name=self._region)

        # Bedrock API Key auth: disable SigV4, inject Bearer token
        import botocore.session
        from botocore.config import Config
        from botocore import UNSIGNED

        session = botocore.session.Session()
        client = session.create_client(
            "bedrock-runtime",
            region_name=self._region,
            config=Config(signature_version=UNSIGNED),
        )
        api_key = self.api_key

        def _inject_api_key(request, **kwargs):
            request.headers["Authorization"] = f"Bearer {api_key}"

        client.meta.events.register(
            "before-sign.bedrock-runtime.*", _inject_api_key
        )
        return client

    # ------------------------------------------------------------------
    # Model ID helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_model_id(model: str) -> str:
        """Strip the 'bedrock/' routing prefix from a model name."""
        if model.startswith("bedrock/"):
            return model[len("bedrock/"):]
        return model

    @staticmethod
    def _infer_region(model_id: str) -> str | None:
        """Infer region from a cross-region model ID prefix, or None."""
        prefix = model_id.split(".")[0]
        return _REGION_MAP.get(prefix)

    # ------------------------------------------------------------------
    # Message conversion (OpenAI format -> Converse API format)
    # ------------------------------------------------------------------

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict], list[dict]]:
        """Convert OpenAI-format messages to Converse API format.

        Returns (system_prompts, converse_messages).
        """
        system_prompts: list[dict] = []
        converse_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                system_prompts.append({"text": msg["content"]})
                continue

            if role == "tool":
                # Tool result -> user message with toolResult block
                block = {
                    "toolResult": {
                        "toolUseId": msg["tool_call_id"],
                        "content": [{"text": msg.get("content", "")}],
                    }
                }
                self._append_message(converse_messages, "user", [block])
                continue

            if role == "assistant":
                content_blocks = self._convert_assistant_message(msg)
                self._append_message(converse_messages, "assistant", content_blocks)
                continue

            if role == "user":
                content_blocks = self._convert_user_content(msg.get("content", ""))
                self._append_message(converse_messages, "user", content_blocks)
                continue

        return system_prompts, converse_messages

    @staticmethod
    def _append_message(
        messages: list[dict], role: str, content: list[dict]
    ) -> None:
        """Append content to messages, merging consecutive same-role messages."""
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": content})

    def _convert_user_content(self, content: Any) -> list[dict]:
        """Convert user message content (string or list of parts) to blocks."""
        if isinstance(content, str):
            return [{"text": content}]

        blocks: list[dict] = []
        if isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    blocks.append({"text": part})
                elif isinstance(part, dict):
                    part_type = part.get("type", "")
                    if part_type == "text":
                        blocks.append({"text": part["text"]})
                    elif part_type == "image_url":
                        blocks.append(self._convert_image(part["image_url"]["url"]))
        return blocks or [{"text": ""}]

    @staticmethod
    def _convert_image(data_url: str) -> dict:
        """Convert a data:image/... base64 URL to a Converse image block."""
        # Format: data:image/png;base64,<data>
        header, _, b64_data = data_url.partition(",")
        fmt = header.split("/", 1)[-1].split(";", 1)[0]  # e.g. "png"
        return {
            "image": {
                "format": fmt,
                "source": {"bytes": base64.b64decode(b64_data)},
            }
        }

    @staticmethod
    def _convert_assistant_message(msg: dict) -> list[dict]:
        """Convert an assistant message (possibly with tool calls) to blocks."""
        blocks: list[dict] = []

        # Text content
        text = msg.get("content")
        if text:
            blocks.append({"text": text})

        # Tool calls
        for tc in msg.get("tool_calls", []):
            fn = tc["function"]
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {"raw": args}

            blocks.append({
                "toolUse": {
                    "toolUseId": tc["id"],
                    "name": fn["name"],
                    "input": args,
                }
            })

        return blocks or [{"text": ""}]

    # ------------------------------------------------------------------
    # Tool definition conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict]:
        """Convert OpenAI-format tool definitions to Converse toolSpec format."""
        converted = []
        for tool in tools:
            fn = tool.get("function", {})
            spec: dict[str, Any] = {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "inputSchema": {"json": fn.get("parameters", {})},
            }
            converted.append({"toolSpec": spec})
        return converted

    # ------------------------------------------------------------------
    # Chat (main entry point)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request via Bedrock Converse API."""
        model_id = self._extract_model_id(model) if model else self._model_id

        system_prompts, converse_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": converse_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }

        if system_prompts:
            kwargs["system"] = system_prompts

        if tools:
            kwargs["toolConfig"] = {"tools": self._convert_tools(tools)}

        try:
            response = await asyncio.to_thread(self.client.converse, **kwargs)
            return self._parse_response(response)
        except Exception as e:
            return self._handle_error(e)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> LLMResponse:
        """Parse Converse API response into LLMResponse."""
        output_msg = response.get("output", {}).get("message", {})
        content_blocks = output_msg.get("content", [])

        # Extract text and tool calls
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    ToolCallRequest(
                        id=tu["toolUseId"],
                        name=tu["name"],
                        arguments=tu.get("input", {}),
                    )
                )

        # Map stop reason
        stop_reason = response.get("stopReason", "end_turn")
        finish_reason = _STOP_REASON_MAP.get(stop_reason, stop_reason)

        # Map usage
        usage_raw = response.get("usage", {})
        usage = {}
        if usage_raw:
            usage = {
                "prompt_tokens": usage_raw.get("inputTokens", 0),
                "completion_tokens": usage_raw.get("outputTokens", 0),
                "total_tokens": usage_raw.get("totalTokens", 0),
            }

        content = "\n".join(text_parts) if text_parts else None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        """Convert exceptions into error LLMResponse."""
        try:
            from botocore.exceptions import ClientError
            if isinstance(e, ClientError):
                code = e.response["Error"]["Code"]
                msg = e.response["Error"]["Message"]
                friendly = _ERROR_MAP.get(code, code)
                return LLMResponse(
                    content=f"Bedrock error ({friendly}): {msg}",
                    finish_reason="error",
                )
        except ImportError:
            pass

        return LLMResponse(
            content=f"Error calling Bedrock: {str(e)}",
            finish_reason="error",
        )

    # ------------------------------------------------------------------
    # Default model
    # ------------------------------------------------------------------

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self.default_model
