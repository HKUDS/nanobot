import copy
import logging
import warnings
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from slack_sdk.models import show_unknown_key_warning
from slack_sdk.models.basic_objects import JsonObject, JsonValidator

from ...errors import SlackObjectFormationError
from .basic_components import MarkdownTextObject, PlainTextObject, SlackFile, TextObject
from .block_elements import (
    BlockElement,
    FeedbackButtonsElement,
    IconButtonElement,
    ImageElement,
    InputInteractiveElement,
    InteractiveElement,
    RichTextElement,
    UrlSourceElement,
)

# -------------------------------------------------
# Base Classes
# -------------------------------------------------


class Block(JsonObject):
    """Blocks are a series of components that can be combined
    to create visually rich and compellingly interactive messages.
    https://docs.slack.dev/reference/block-kit/blocks
    """

    attributes = {"block_id", "type"}
    block_id_max_length = 255
    logger = logging.getLogger(__name__)

    def _subtype_warning(self):
        warnings.warn(
            "subtype is deprecated since slackclient 2.6.0, use type instead",
            DeprecationWarning,
        )

    @property
    def subtype(self) -> Optional[str]:
        return self.type

    def __init__(
        self,
        *,
        type: Optional[str] = None,
        subtype: Optional[str] = None,  # deprecated
        block_id: Optional[str] = None,
    ):
        if subtype:
            self._subtype_warning()
        self.type = type if type else subtype
        self.block_id = block_id
        self.color = None

    @JsonValidator(f"block_id cannot exceed {block_id_max_length} characters")
    def _validate_block_id_length(self):
        return self.block_id is None or len(self.block_id) <= self.block_id_max_length

    @classmethod
    def parse(cls, block: Union[dict, "Block"]) -> Optional["Block"]:
        if block is None:
            return None
        elif isinstance(block, Block):
            return block
        else:
            if "type" in block:
                type = block["type"]
                if type == SectionBlock.type:
                    return SectionBlock(**block)
                elif type == DividerBlock.type:
                    return DividerBlock(**block)
                elif type == ImageBlock.type:
                    return ImageBlock(**block)
                elif type == ActionsBlock.type:
                    return ActionsBlock(**block)
                elif type == ContextBlock.type:
                    return ContextBlock(**block)
                elif type == ContextActionsBlock.type:
                    return ContextActionsBlock(**block)
                elif type == InputBlock.type:
                    return InputBlock(**block)
                elif type == FileBlock.type:
                    return FileBlock(**block)
                elif type == CallBlock.type:
                    return CallBlock(**block)
                elif type == HeaderBlock.type:
                    return HeaderBlock(**block)
                elif type == MarkdownBlock.type:
                    return MarkdownBlock(**block)
                elif type == VideoBlock.type:
                    return VideoBlock(**block)
                elif type == RichTextBlock.type:
                    return RichTextBlock(**block)
                elif type == TableBlock.type:
                    return TableBlock(**block)
                elif type == TaskCardBlock.type:
                    return TaskCardBlock(**block)
                elif type == PlanBlock.type:
                    return PlanBlock(**block)
                else:
                    cls.logger.warning(f"Unknown block detected and skipped ({block})")
                    return None
            else:
                cls.logger.warning(f"Unknown block detected and skipped ({block})")
                return None

    @classmethod
    def parse_all(cls, blocks: Optional[Sequence[Union[dict, "Block"]]]) -> List["Block"]:
        return [cls.parse(b) for b in blocks or []]  # type: ignore[misc]


# -------------------------------------------------
# Block Classes
# -------------------------------------------------


class SectionBlock(Block):
    type = "section"
    fields_max_length = 10
    text_max_length = 3000

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"text", "fields", "accessory", "expand"})

    def __init__(
        self,
        *,
        block_id: Optional[str] = None,
        text: Optional[Union[str, dict, TextObject]] = None,
        fields: Optional[Sequence[Union[str, dict, TextObject]]] = None,
        accessory: Optional[Union[dict, BlockElement]] = None,
        expand: Optional[bool] = None,
        **others: dict,
    ):
        """A section is one of the most flexible blocks available.
        https://docs.slack.dev/reference/block-kit/blocks/section-block

        Args:
            block_id (required): A string acting as a unique identifier for a block.
                If not specified, one will be generated.
                You can use this block_id when you receive an interaction payload to identify the source of the action.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            text (preferred): The text for the block, in the form of a text object.
                Maximum length for the text in this field is 3000 characters.
                This field is not required if a valid array of fields objects is provided instead.
            fields (required if no text is provided): Required if no text is provided.
                An array of text objects. Any text objects included with fields will be rendered
                in a compact format that allows for 2 columns of side-by-side text.
                Maximum number of items is 10. Maximum length for the text in each item is 2000 characters.
            accessory: One of the available element objects.
            expand: Whether or not this section block's text should always expand when rendered.
                If false or not provided, it may be rendered with a 'see more' option to expand and show the full text.
                For AI Assistant apps, this allows the app to post long messages without users needing
                to click 'see more' to expand the message.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.text = TextObject.parse(text)  # type: ignore[arg-type]
        field_objects = []
        for f in fields or []:
            if isinstance(f, str):
                field_objects.append(MarkdownTextObject.from_str(f))
            elif isinstance(f, TextObject):
                field_objects.append(f)  # type: ignore[arg-type]
            elif isinstance(f, dict) and "type" in f:
                d = copy.copy(f)
                t = d.pop("type")
                if t == MarkdownTextObject.type:
                    field_objects.append(MarkdownTextObject(**d))
                else:
                    field_objects.append(PlainTextObject(**d))  # type: ignore[arg-type]
            else:
                self.logger.warning(f"Unsupported filed detected and skipped {f}")
        self.fields = field_objects
        self.accessory = BlockElement.parse(accessory)  # type: ignore[arg-type]
        self.expand = expand

    @JsonValidator("text or fields attribute must be specified")
    def _validate_text_or_fields_populated(self):
        return self.text is not None or self.fields

    @JsonValidator(f"fields attribute cannot exceed {fields_max_length} items")
    def _validate_fields_length(self):
        return self.fields is None or len(self.fields) <= self.fields_max_length

    @JsonValidator(f"text attribute cannot exceed {text_max_length} characters")
    def _validate_alt_text_length(self):
        return self.text is None or len(self.text.text) <= self.text_max_length


class DividerBlock(Block):
    type = "divider"

    def __init__(
        self,
        *,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """A content divider, like an <hr>, to split up different blocks inside of a message.
        https://docs.slack.dev/reference/block-kit/blocks/divider-block

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                You can use this block_id when you receive an interaction payload to identify the source of the action.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)


class ImageBlock(Block):
    type = "image"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"alt_text", "image_url", "title", "slack_file"})

    image_url_max_length = 3000
    alt_text_max_length = 2000
    title_max_length = 2000

    def __init__(
        self,
        *,
        alt_text: str,
        image_url: Optional[str] = None,
        slack_file: Optional[Union[Dict[str, Any], SlackFile]] = None,
        title: Optional[Union[str, dict, PlainTextObject]] = None,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """A simple image block, designed to make those cat photos really pop.
        https://docs.slack.dev/reference/block-kit/blocks/image-block

        Args:
            alt_text (required): A plain-text summary of the image. This should not contain any markup.
                Maximum length for this field is 2000 characters.
            image_url: The URL of the image to be displayed.
                Maximum length for this field is 3000 characters.
            slack_file: A Slack image file object that defines the source of the image.
            title: An optional title for the image in the form of a text object that can only be of type: plain_text.
                Maximum length for the text in this field is 2000 characters.
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.image_url = image_url
        self.alt_text = alt_text
        parsed_title = None
        if title is not None:
            if isinstance(title, str):
                parsed_title = PlainTextObject(text=title)
            elif isinstance(title, dict):
                if title.get("type") != PlainTextObject.type:
                    raise SlackObjectFormationError(f"Unsupported type for title in an image block: {title.get('type')}")
                parsed_title = PlainTextObject(text=title.get("text"), emoji=title.get("emoji"))  # type: ignore[arg-type]
            elif isinstance(title, PlainTextObject):
                parsed_title = title
            else:
                raise SlackObjectFormationError(f"Unsupported type for title in an image block: {type(title)}")
        if slack_file is not None:
            self.slack_file = (
                slack_file if slack_file is None or isinstance(slack_file, SlackFile) else SlackFile(**slack_file)
            )
        self.title = parsed_title

    @JsonValidator(f"image_url attribute cannot exceed {image_url_max_length} characters")
    def _validate_image_url_length(self):
        return self.image_url is None or len(self.image_url) <= self.image_url_max_length

    @JsonValidator(f"alt_text attribute cannot exceed {alt_text_max_length} characters")
    def _validate_alt_text_length(self):
        return len(self.alt_text) <= self.alt_text_max_length

    @JsonValidator(f"title attribute cannot exceed {title_max_length} characters")
    def _validate_title_length(self):
        return self.title is None or self.title.text is None or len(self.title.text) <= self.title_max_length


class ActionsBlock(Block):
    type = "actions"
    elements_max_length = 25

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"elements"})

    def __init__(
        self,
        *,
        elements: Sequence[Union[dict, InteractiveElement]],
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """A block that is used to hold interactive elements.
        https://docs.slack.dev/reference/block-kit/blocks/actions-block

        Args:
            elements (required): An array of interactive element objects - buttons, select menus, overflow menus,
                or date pickers. There is a maximum of 25 elements in each action block.
            block_id: A string acting as a unique identifier for a block.
                If not specified, a block_id will be generated.
                You can use this block_id when you receive an interaction payload to identify the source of the action.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.elements = BlockElement.parse_all(elements)

    @JsonValidator(f"elements attribute cannot exceed {elements_max_length} elements")
    def _validate_elements_length(self):
        return self.elements is None or len(self.elements) <= self.elements_max_length


class ContextBlock(Block):
    type = "context"
    elements_max_length = 10

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"elements"})

    def __init__(
        self,
        *,
        elements: Sequence[Union[dict, ImageElement, TextObject]],
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays message context, which can include both images and text.
        https://docs.slack.dev/reference/block-kit/blocks/context-block

        Args:
            elements (required): An array of image elements and text objects. Maximum number of items is 10.
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.elements = BlockElement.parse_all(elements)

    @JsonValidator(f"elements attribute cannot exceed {elements_max_length} elements")
    def _validate_elements_length(self):
        return self.elements is None or len(self.elements) <= self.elements_max_length


class ContextActionsBlock(Block):
    type = "context_actions"
    elements_max_length = 5

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"elements"})

    def __init__(
        self,
        *,
        elements: Sequence[Union[dict, FeedbackButtonsElement, IconButtonElement]],
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays actions as contextual info, which can include both feedback buttons and icon buttons.
        https://docs.slack.dev/reference/block-kit/blocks/context-actions-block

        Args:
            elements (required): An array of feedback_buttons or icon_button block elements. Maximum number of items is 5.
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.elements = BlockElement.parse_all(elements)

    @JsonValidator("elements attribute must be specified")
    def _validate_elements(self):
        return self.elements is None or len(self.elements) > 0

    @JsonValidator(f"elements attribute cannot exceed {elements_max_length} elements")
    def _validate_elements_length(self):
        return self.elements is None or len(self.elements) <= self.elements_max_length


class InputBlock(Block):
    type = "input"
    label_max_length = 2000
    hint_max_length = 2000

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"label", "hint", "element", "optional", "dispatch_action"})

    def __init__(
        self,
        *,
        label: Union[str, dict, PlainTextObject],
        element: Union[str, dict, InputInteractiveElement],
        block_id: Optional[str] = None,
        hint: Optional[Union[str, dict, PlainTextObject]] = None,
        dispatch_action: Optional[bool] = None,
        optional: Optional[bool] = None,
        **others: dict,
    ):
        """A block that collects information from users - it can hold a plain-text input element,
        a select menu element, a multi-select menu element, or a datepicker.
        https://docs.slack.dev/reference/block-kit/blocks/input-block

        Args:
            label (required): A label that appears above an input element in the form of a text object
                that must have type of plain_text. Maximum length for the text in this field is 2000 characters.
            element (required): An plain-text input element, a checkbox element, a radio button element,
                a select menu element, a multi-select menu element, or a datepicker.
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message or view and each iteration of a message or view.
                If a message or view is updated, use a new block_id.
            hint: An optional hint that appears below an input element in a lighter grey.
                It must be a text object with a type of plain_text.
                Maximum length for the text in this field is 2000 characters.
            dispatch_action: A boolean that indicates whether or not the use of elements in this block
                should dispatch a block_actions payload. Defaults to false.
            optional: A boolean that indicates whether the input element may be empty when a user submits the modal.
                Defaults to false.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.label = TextObject.parse(label, default_type=PlainTextObject.type)
        self.element = BlockElement.parse(element)  # type: ignore[arg-type]
        self.hint = TextObject.parse(hint, default_type=PlainTextObject.type)  # type: ignore[arg-type]
        self.dispatch_action = dispatch_action
        self.optional = optional

    @JsonValidator(f"label attribute cannot exceed {label_max_length} characters")
    def _validate_label_length(self):
        return self.label is None or self.label.text is None or len(self.label.text) <= self.label_max_length

    @JsonValidator(f"hint attribute cannot exceed {hint_max_length} characters")
    def _validate_hint_length(self):
        return self.hint is None or self.hint.text is None or len(self.hint.text) <= self.label_max_length

    @JsonValidator(
        (
            "element attribute must be a string, select element, multi-select element, "
            "or a datepicker. (Sub-classes of InputInteractiveElement)"
        )
    )
    def _validate_element_type(self):
        return self.element is None or isinstance(self.element, (str, InputInteractiveElement))


class FileBlock(Block):
    type = "file"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"external_id", "source"})

    def __init__(
        self,
        *,
        external_id: str,
        source: str = "remote",
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays a remote file.
        https://docs.slack.dev/reference/block-kit/blocks/file-block

        Args:
            external_id (required): The external unique ID for this file.
            source (required): At the moment, source will always be remote for a remote file.
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.external_id = external_id
        self.source = source


class CallBlock(Block):
    type = "call"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"call_id", "api_decoration_available", "call"})

    def __init__(
        self,
        *,
        call_id: str,
        api_decoration_available: Optional[bool] = None,
        call: Optional[Dict[str, Dict[str, Any]]] = None,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays a call information
        https://docs.slack.dev/reference/block-kit/blocks#call
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.call_id = call_id
        self.api_decoration_available = api_decoration_available
        self.call = call


class HeaderBlock(Block):
    type = "header"
    text_max_length = 150

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"text"})

    def __init__(
        self,
        *,
        block_id: Optional[str] = None,
        text: Optional[Union[str, dict, TextObject]] = None,
        **others: dict,
    ):
        """A header is a plain-text block that displays in a larger, bold font.
        https://docs.slack.dev/reference/block-kit/blocks/header-block

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            text (required): The text for the block, in the form of a plain_text text object.
                Maximum length for the text in this field is 150 characters.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.text = TextObject.parse(text, default_type=PlainTextObject.type)  # type: ignore[arg-type]

    @JsonValidator("text attribute must be specified")
    def _validate_text(self):
        return self.text is not None

    @JsonValidator(f"text attribute cannot exceed {text_max_length} characters")
    def _validate_alt_text_length(self):
        return self.text is None or len(self.text.text) <= self.text_max_length


class MarkdownBlock(Block):
    type = "markdown"
    text_max_length = 12000

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"text"})

    def __init__(
        self,
        *,
        text: str,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays formatted markdown.
        https://docs.slack.dev/reference/block-kit/blocks/markdown-block/

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            text (required): The standard markdown-formatted text. Limit 12,000 characters max.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.text = text

    @JsonValidator("text attribute must be specified")
    def _validate_text(self):
        return self.text != ""

    @JsonValidator(f"text attribute cannot exceed {text_max_length} characters")
    def _validate_alt_text_length(self):
        return len(self.text) <= self.text_max_length


class VideoBlock(Block):
    type = "video"
    title_max_length = 200
    author_name_max_length = 50

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union(
            {
                "alt_text",
                "video_url",
                "thumbnail_url",
                "title",
                "title_url",
                "description",
                "provider_icon_url",
                "provider_name",
                "author_name",
            }
        )

    def __init__(
        self,
        *,
        block_id: Optional[str] = None,
        alt_text: Optional[str] = None,
        video_url: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        title: Optional[Union[str, dict, PlainTextObject]] = None,
        title_url: Optional[str] = None,
        description: Optional[Union[str, dict, PlainTextObject]] = None,
        provider_icon_url: Optional[str] = None,
        provider_name: Optional[str] = None,
        author_name: Optional[str] = None,
        **others: dict,
    ):
        """A video block is designed to embed videos in all app surfaces
        (e.g. link unfurls, messages, modals, App Home) —
        anywhere you can put blocks! To use the video block within your app,
        you must have the links.embed:write scope.
        https://docs.slack.dev/reference/block-kit/blocks/video-block

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            alt_text (required): A tooltip for the video. Required for accessibility
            video_url (required): The URL to be embedded. Must match any existing unfurl domains within the app
                and point to a HTTPS URL.
            thumbnail_url (required): The thumbnail image URL
            title (required): Video title in plain text format. Must be less than 200 characters.
            title_url: Hyperlink for the title text. Must correspond to the non-embeddable URL for the video.
                Must go to an HTTPS URL.
            description: Description for video in plain text format.
            provider_icon_url: Icon for the video provider - ex. Youtube icon
            provider_name: The originating application or domain of the video ex. Youtube
            author_name: Author name to be displayed. Must be less than 50 characters.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.alt_text = alt_text
        self.video_url = video_url
        self.thumbnail_url = thumbnail_url
        self.title = TextObject.parse(title, default_type=PlainTextObject.type)  # type: ignore[arg-type]
        self.title_url = title_url
        self.description = TextObject.parse(description, default_type=PlainTextObject.type)  # type: ignore[arg-type]
        self.provider_icon_url = provider_icon_url
        self.provider_name = provider_name
        self.author_name = author_name

    @JsonValidator("alt_text attribute must be specified")
    def _validate_alt_text(self):
        return self.alt_text is not None

    @JsonValidator("video_url attribute must be specified")
    def _validate_video_url(self):
        return self.video_url is not None

    @JsonValidator("thumbnail_url attribute must be specified")
    def _validate_thumbnail_url(self):
        return self.thumbnail_url is not None

    @JsonValidator("title attribute must be specified")
    def _validate_title(self):
        return self.title is not None

    @JsonValidator(f"title attribute cannot exceed {title_max_length} characters")
    def _validate_title_length(self):
        return self.title is None or len(self.title.text) < self.title_max_length

    @JsonValidator(f"author_name attribute cannot exceed {author_name_max_length} characters")
    def _validate_author_name_length(self):
        return self.author_name is None or len(self.author_name) < self.author_name_max_length


class RichTextBlock(Block):
    type = "rich_text"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"elements"})

    def __init__(
        self,
        *,
        elements: Sequence[Union[dict, RichTextElement]],
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """A block that is used to hold interactive elements.
        https://docs.slack.dev/reference/block-kit/blocks/rich-text-block

        Args:
            elements (required): An array of rich text objects -
                rich_text_section, rich_text_list, rich_text_quote, rich_text_preformatted
            block_id: A unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message or view and each iteration of a message or view.
                If a message or view is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.elements = BlockElement.parse_all(elements)


class TableBlock(Block):
    type = "table"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"rows", "column_settings"})

    def __init__(
        self,
        *,
        rows: Sequence[Sequence[Dict[str, Any]]],
        column_settings: Optional[Sequence[Optional[Dict[str, Any]]]] = None,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays structured information in a table.
        https://docs.slack.dev/reference/block-kit/blocks/table-block

        Args:
            rows (required): An array consisting of table rows. Maximum 100 rows.
                Each row object is an array with a max of 20 table cells.
                Table cells can have a type of raw_text or rich_text.
            column_settings: An array describing column behavior. If there are fewer items in the column_settings array
                than there are columns in the table, then the items in the the column_settings array will describe
                the same number of columns in the table as there are in the array itself.
                Any additional columns will have the default behavior. Maximum 20 items.
                See below for column settings schema.
            block_id: A unique identifier for a block. If not specified, a block_id will be generated.
                You can use this block_id when you receive an interaction payload to identify the source of the action.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.rows = rows
        self.column_settings = column_settings

    @JsonValidator("rows attribute must be specified")
    def _validate_rows(self):
        return self.rows is not None and len(self.rows) > 0


class TaskCardBlock(Block):
    type = "task_card"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union(
            {
                "task_id",
                "title",
                "details",
                "output",
                "sources",
                "status",
            }
        )

    def __init__(
        self,
        *,
        task_id: str,
        title: str,
        details: Optional[Union[RichTextBlock, dict]] = None,
        output: Optional[Union[RichTextBlock, dict]] = None,
        sources: Optional[Sequence[Union[UrlSourceElement, dict]]] = None,
        status: str,  # pending, in_progress, complete, error
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays a single task, representing a single action.
        https://docs.slack.dev/reference/block-kit/blocks/task-card-block/

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            task_id (required): ID for the task
            title (required): Title of the task in plain text
            details: Details of the task in the form of a single "rich_text" entity.
            output: Output of the task in the form of a single "rich_text" entity.
            sources: Array of URL source elements used to generate a response.
            status: The state of a task. Either "pending", "in_progress", "complete", or "error".
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.task_id = task_id
        self.title = title
        self.details = details
        self.output = output
        self.sources = sources
        self.status = status

    @JsonValidator("status must be an expected value (pending, in_progress, complete, or error)")
    def _validate_rows(self):
        return self.status in ["pending", "in_progress", "complete", "error"]


class PlanBlock(Block):
    type = "plan"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union(
            {
                "title",
                "tasks",
            }
        )

    def __init__(
        self,
        *,
        title: str,
        tasks: Optional[Sequence[Union[Dict, TaskCardBlock]]] = None,
        block_id: Optional[str] = None,
        **others: dict,
    ):
        """Displays a collection of related tasks.
        https://docs.slack.dev/reference/block-kit/blocks/plan-block/

        Args:
            block_id: A string acting as a unique identifier for a block. If not specified, one will be generated.
                Maximum length for this field is 255 characters.
                block_id should be unique for each message and each iteration of a message.
                If a message is updated, use a new block_id.
            title (required): Title of the plan in plain text
            tasks: A sequence of task card blocks. Each task represents a single action within the plan.
        """
        super().__init__(type=self.type, block_id=block_id)
        show_unknown_key_warning(self, others)

        self.title = title
        self.tasks = tasks
