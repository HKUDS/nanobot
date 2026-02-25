import logging
from typing import Dict, Optional, Sequence, Set, Union

from slack_sdk.models import show_unknown_key_warning
from slack_sdk.models.basic_objects import JsonObject
from slack_sdk.models.blocks.block_elements import UrlSourceElement


class Chunk(JsonObject):
    """
    Chunk for streaming messages.

    https://docs.slack.dev/messaging/sending-and-scheduling-messages#text-streaming
    """

    attributes = {"type"}
    logger = logging.getLogger(__name__)

    def __init__(
        self,
        *,
        type: Optional[str] = None,
    ):
        self.type = type

    @classmethod
    def parse(cls, chunk: Union[Dict, "Chunk"]) -> Optional["Chunk"]:
        if chunk is None:
            return None
        elif isinstance(chunk, Chunk):
            return chunk
        else:
            if "type" in chunk:
                type = chunk["type"]
                if type == MarkdownTextChunk.type:
                    return MarkdownTextChunk(**chunk)
                elif type == PlanUpdateChunk.type:
                    return PlanUpdateChunk(**chunk)
                elif type == TaskUpdateChunk.type:
                    return TaskUpdateChunk(**chunk)
                else:
                    cls.logger.warning(f"Unknown chunk detected and skipped ({chunk})")
                    return None
            else:
                cls.logger.warning(f"Unknown chunk detected and skipped ({chunk})")
                return None


class MarkdownTextChunk(Chunk):
    type = "markdown_text"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"text"})

    def __init__(
        self,
        *,
        text: str,
        **others: Dict,
    ):
        """Used for streaming text content with markdown formatting support.

        https://docs.slack.dev/messaging/sending-and-scheduling-messages#text-streaming
        """
        super().__init__(type=self.type)
        show_unknown_key_warning(self, others)

        self.text = text


class PlanUpdateChunk(Chunk):
    type = "plan_update"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"title"})

    def __init__(
        self,
        *,
        title: str,
        **others: Dict,
    ):
        """Used for displaying an updated title of a plan.

        https://docs.slack.dev/messaging/sending-and-scheduling-messages#text-streaming
        """
        super().__init__(type=self.type)
        show_unknown_key_warning(self, others)

        self.title = title


class TaskUpdateChunk(Chunk):
    type = "task_update"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union(
            {
                "id",
                "title",
                "status",
                "details",
                "output",
                "sources",
            }
        )

    def __init__(
        self,
        *,
        id: str,
        title: str,
        status: str,  # "pending", "in_progress", "complete", "error"
        details: Optional[str] = None,
        output: Optional[str] = None,
        sources: Optional[Sequence[Union[Dict, UrlSourceElement]]] = None,
        **others: Dict,
    ):
        """Used for displaying task progress in a timeline-style UI.

        https://docs.slack.dev/messaging/sending-and-scheduling-messages#text-streaming
        """
        super().__init__(type=self.type)
        show_unknown_key_warning(self, others)

        self.id = id
        self.title = title
        self.status = status
        self.details = details
        self.output = output
        self.sources = sources
