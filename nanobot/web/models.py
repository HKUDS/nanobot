"""Pydantic request/response models for the web API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessageContent(BaseModel):
    """A content part within a message (text or other types)."""

    type: str = "text"
    text: str = ""
    # Fields for file/image content parts (Vercel AI SDK LanguageModelV2 format)
    data: str | None = None
    media_type: str | None = Field(default=None, alias="mediaType")


class ChatMessage(BaseModel):
    """A single message in a conversation (AI SDK format)."""

    role: str = Field(..., description="Message role: user, assistant, system, or tool")
    content: str | list[ChatMessageContent] = Field(
        ..., description="Message content (string or structured parts)"
    )

    def get_text(self) -> str:
        """Extract plain text from content, regardless of format."""
        if isinstance(self.content, str):
            return self.content
        return "".join(p.text for p in self.content if p.type == "text")


class ChatRequest(BaseModel):
    """Request body for the chat endpoint (AI SDK Data Stream Protocol)."""

    model_config = {"populate_by_name": True}

    messages: list[ChatMessage] = Field(..., description="Conversation messages")
    thread_id: str | None = Field(
        default=None, alias="threadId", description="Thread/conversation identifier"
    )
    system: str | None = Field(default=None, description="System prompt override")


class HistoryMessage(BaseModel):
    """A message from session history."""

    role: str
    content: str
    timestamp: str | None = None
    tool_calls: list[dict] | None = None


class HistoryResponse(BaseModel):
    """Response from the history endpoint."""

    session_id: str
    messages: list[HistoryMessage]


class ThreadInfo(BaseModel):
    """Thread metadata for the thread list."""

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    thread_id: str = Field(alias="threadId")
    title: str
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")


class ThreadListResponse(BaseModel):
    """Response from the thread list endpoint."""

    threads: list[ThreadInfo]
