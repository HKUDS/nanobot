import re
from abc import ABCMeta, abstractmethod
from typing import List, Optional, Set, Sequence

from slack_sdk.models import extract_json
from slack_sdk.models.basic_objects import (
    EnumValidator,
    JsonObject,
    JsonValidator,
)
from slack_sdk.models.blocks import (
    Block,
    Option,
    ConfirmObject,
    ButtonStyles,
    DynamicSelectElementTypes,
)


class Action(JsonObject):
    """Action in attachments
    https://docs.slack.dev/messaging/formatting-message-text/#rich-layouts
    https://docs.slack.dev/legacy/legacy-messaging/legacy-interactive-message-field-guide/#message_action_fields
    """

    attributes = {"name", "text", "url"}

    def __init__(
        self,
        *,
        text: str,
        subtype: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
    ):
        self.name = name
        self.url = url
        self.text = text
        self.subtype = subtype

    @JsonValidator("name or url attribute is required")
    def name_or_url_present(self):
        return self.name is not None or self.url is not None

    def to_dict(self) -> dict:
        json = super().to_dict()
        json["type"] = self.subtype
        return json


class ActionButton(Action):
    @property
    def attributes(self):
        return super().attributes.union({"style", "value"})

    value_max_length = 2000

    def __init__(
        self,
        *,
        name: str,
        text: str,
        value: str,
        confirm: Optional[ConfirmObject] = None,
        style: Optional[str] = None,
    ):
        """Simple button for use inside attachments

        https://docs.slack.dev/legacy/legacy-messaging/legacy-message-buttons/

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            value: Provide a string identifying this specific action. It will be
                sent to your Action URL along with the name and attachment's
                callback_id . If providing multiple actions with the same name, value
                can be strategically used to differentiate intent. Cannot exceed 2000
                characters.
            confirm: a ConfirmObject that will appear in a dialog to confirm
                user's choice.
            style: Leave blank to indicate that this is an ordinary button. Use
                "primary" or "danger" to mark important buttons.
        """
        super().__init__(name=name, text=text, subtype="button")
        self.value = value
        self.confirm = confirm
        self.style = style

    @JsonValidator(f"value attribute cannot exceed {value_max_length} characters")
    def value_length(self):
        return len(self.value) <= self.value_max_length

    @EnumValidator("style", ButtonStyles)
    def style_valid(self):
        return self.style is None or self.style in ButtonStyles

    def to_dict(self) -> dict:
        json = super().to_dict()
        if self.confirm is not None:
            json["confirm"] = extract_json(self.confirm, "action")
        return json


class ActionLinkButton(Action):
    def __init__(self, *, text: str, url: str):
        """A simple interactive button that just opens a URL

        https://docs.slack.dev/messaging/formatting-message-text/#rich-layouts

        Args:
          text: text to display on the button, eg 'Click Me!"
          url: the URL to open
        """
        super().__init__(text=text, url=url, subtype="button")


class AbstractActionSelector(Action, metaclass=ABCMeta):
    DataSourceTypes = DynamicSelectElementTypes.union({"external", "static"})

    attributes = {"data_source", "name", "text", "type"}

    @property
    @abstractmethod
    def data_source(self) -> str:
        pass

    def __init__(self, *, name: str, text: str, selected_option: Optional[Option] = None):
        super().__init__(text=text, name=name, subtype="select")
        self.selected_option = selected_option

    @EnumValidator("data_source", DataSourceTypes)
    def data_source_valid(self):
        return self.data_source in self.DataSourceTypes

    def to_dict(self) -> dict:
        json = super().to_dict()
        if self.selected_option is not None:
            # this is a special case for ExternalActionSelectElement - in that case,
            # you pass the initial value of the selector as a selected_options array
            json["selected_options"] = extract_json([self.selected_option], "action")
        return json


class ActionUserSelector(AbstractActionSelector):
    data_source = "users"

    def __init__(self, name: str, text: str, selected_user: Optional[Option] = None):
        """Automatically populate the selector with a list of users in the workspace.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-adding-menus-to-messages/#menu_team_members

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            selected_user: An Option object to pre-select as the default
                value.
        """
        super().__init__(name=name, text=text, selected_option=selected_user)


class ActionChannelSelector(AbstractActionSelector):
    data_source = "channels"

    def __init__(self, name: str, text: str, selected_channel: Optional[Option] = None):
        """
        Automatically populate the selector with a list of public channels in the
        workspace.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-adding-menus-to-messages/#menu_channels

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            selected_channel: An Option object to pre-select as the default
                value.
        """
        super().__init__(name=name, text=text, selected_option=selected_channel)


class ActionConversationSelector(AbstractActionSelector):
    data_source = "conversations"

    def __init__(self, name: str, text: str, selected_conversation: Optional[Option] = None):
        """
        Automatically populate the selector with a list of conversations they have in
        the workspace.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-adding-menus-to-messages/#menu_conversations

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            selected_conversation: An Option object to pre-select as the default
                value.
        """
        super().__init__(name=name, text=text, selected_option=selected_conversation)


class ActionExternalSelector(AbstractActionSelector):
    data_source = "external"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"min_query_length"})

    def __init__(
        self,
        *,
        name: str,
        text: str,
        selected_option: Optional[Option] = None,
        min_query_length: Optional[int] = None,
    ):
        """
        Populate a message select menu from your own application dynamically.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-adding-menus-to-messages/#menu_dynamic

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            selected_option: An Option object to pre-select as the default
                value.
            min_query_length: Specify the number of characters that must be typed
                by a user into a dynamic select menu before dispatching to the app.
        """
        super().__init__(name=name, text=text, selected_option=selected_option)
        self.min_query_length = min_query_length


SeededColors = {"danger", "good", "warning"}


class AttachmentField(JsonObject):
    attributes = {"short", "title", "value"}

    def __init__(
        self,
        *,
        title: Optional[str] = None,
        value: Optional[str] = None,
        short: bool = True,
    ):
        self.title = title
        self.value = value
        self.short = short


class Attachment(JsonObject):
    attributes = {
        "author_icon",
        "author_link",
        "author_name",
        "author_subname",
        "color",
        "fallback",
        "fields",
        "footer",
        "footer_icon",
        "image_url",
        "pretext",
        "text",
        "thumb_url",
        "title",
        "title_link",
        "ts",
    }

    fields: Sequence[AttachmentField]

    MarkdownFields = {"fields", "pretext", "text"}

    footer_max_length = 300

    def __init__(
        self,
        *,
        text: str,
        fallback: Optional[str] = None,
        fields: Optional[Sequence[AttachmentField]] = None,
        color: Optional[str] = None,
        markdown_in: Optional[Sequence[str]] = None,
        title: Optional[str] = None,
        title_link: Optional[str] = None,
        pretext: Optional[str] = None,
        author_name: Optional[str] = None,
        author_subname: Optional[str] = None,
        author_link: Optional[str] = None,
        author_icon: Optional[str] = None,
        image_url: Optional[str] = None,
        thumb_url: Optional[str] = None,
        footer: Optional[str] = None,
        footer_icon: Optional[str] = None,
        ts: Optional[int] = None,
    ):
        """
        A supplemental object that will display after the rest of the message.
        Considered legacy - recommended replacement is to use message blocks instead.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-secondary-message-attachments#fields

        Args:
            text: The main body text of the attachment. It can be formatted as
                plain text, or with markdown by including it in the markdown_in
                parameter. The content will automatically collapse if it contains 700+
                characters or 5+ linebreaks, and will display a "Show more..." link to
                expand the content.
            fallback: A plain text summary of the attachment used in clients that
                don't show formatted text (eg. IRC, mobile notifications).
            fields: An array of AttachmentField objects that get displayed in a
                table-like way. For best results, include no more than 2-3 field
                objects.
            color: Changes the color of the border on the left side of this attachment
                from the default gray. Can be any hex color code (eg. #439FE0)
            markdown_in: An array of field names that should be formatted by
                markdown syntax - allowed values: "pretext", "text", "fields"
            title: Large title text near the top of the attachment.
            title_link: A valid URL that turns the title text into a hyperlink.
            pretext: Text that appears above the message attachment block. It can
                be formatted as plain text, or with markdown by including it in the
                markdown_in parameter.
            author_name: Small text used to display the author's name.
            author_subname: Small text used to display the author's sub name.
            author_link: A valid URL that will hyperlink the author_name text.
                Will only work if author_name is present.
            author_icon: A valid URL that displays a small 16px by 16px image to
                the left of the author_name text. Will only work if author_name is
                present.
            image_url: A valid URL to an image file that will be displayed at the
                bottom of the attachment. We support GIF, JPEG, PNG, and BMP formats.
                Large images will be resized to a maximum width of 360px or a maximum
                height of 500px, while still maintaining the original aspect ratio.
                Cannot be used with thumb_url.
            thumb_url: A valid URL to an image file that will be displayed as a
                thumbnail on the right side of a message attachment. We currently
                support the following formats: GIF, JPEG, PNG, and BMP. The thumbnail's
                longest dimension will be scaled down to 75px while maintaining the
                aspect ratio of the image. The filesize of the image must also be less
                than 500 KB. For best results, please use images that are already 75px
                by 75px.
            footer: Some brief text to help contextualize and identify an
                attachment. Limited to 300 characters, and may be truncated further when
                displayed to users in environments with limited screen real estate.
            footer_icon: A valid URL to an image file that will be displayed
                beside the footer text. Will only work if footer is present. We'll
                render what you provide at 16px by 16px. It's best to use an image that
                is similarly sized.
            ts: An integer Unix timestamp that is used to related your attachment
                to a specific time. The attachment will display the additional timestamp
                value as part of the attachment's footer. Your message's timestamp will
                be displayed in varying ways, depending on how far in the past or future
                 it is, relative to the present. Form factors, like mobile versus
                 desktop may also transform its rendered appearance.
        """
        self.text = text
        self.title = title
        self.fallback = fallback
        self.pretext = pretext
        self.title_link = title_link
        self.color = color
        self.author_name = author_name
        self.author_subname = author_subname
        self.author_link = author_link
        self.author_icon = author_icon
        self.image_url = image_url
        self.thumb_url = thumb_url
        self.footer = footer
        self.footer_icon = footer_icon
        self.ts = ts
        self.fields = fields or []
        self.markdown_in = markdown_in or []

    @JsonValidator(f"footer attribute cannot exceed {footer_max_length} characters")
    def footer_length(self) -> bool:
        return self.footer is None or len(self.footer) <= self.footer_max_length

    @JsonValidator("ts attribute cannot be present if footer attribute is absent")
    def ts_without_footer(self) -> bool:
        return self.ts is None or self.footer is not None

    @EnumValidator("markdown_in", MarkdownFields)
    def markdown_in_valid(self):
        return not self.markdown_in or all(e in self.MarkdownFields for e in self.markdown_in)

    @JsonValidator("color attribute must be 'good', 'warning', 'danger', or a hex color code")
    def color_valid(self) -> bool:
        return (
            self.color is None
            or self.color in SeededColors
            or re.match("^#(?:[0-9A-F]{2}){3}$", self.color, re.IGNORECASE) is not None
        )

    @JsonValidator("image_url attribute cannot be present if thumb_url is populated")
    def image_url_and_thumb_url_populated(self) -> bool:
        return self.image_url is None or self.thumb_url is None

    @JsonValidator("name must be present if link is present")
    def author_link_without_author_name(self) -> bool:
        return self.author_link is None or self.author_name is not None

    @JsonValidator("icon must be present if link is present")
    def author_link_without_author_icon(self) -> bool:
        return self.author_link is None or self.author_icon is not None

    def to_dict(self) -> dict:
        json = super().to_dict()
        if self.fields is not None:
            json["fields"] = extract_json(self.fields)
        if self.markdown_in:
            json["mrkdwn_in"] = self.markdown_in
        return json


class BlockAttachment(Attachment):
    blocks: List[Block]

    @property
    def attributes(self):
        return super().attributes.union({"blocks", "color"})

    def __init__(
        self,
        *,
        blocks: Sequence[Block],
        color: Optional[str] = None,
        fallback: Optional[str] = None,
    ):
        """
        A bridge between legacy attachments and Block Kit formatting - pass a list of
        Block objects directly to this attachment.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-secondary-message-attachments#fields

        Args:
            blocks: a sequence of Block objects
            color: Changes the color of the border on the left side of this
                attachment from the default gray. Can either be one of "good" (green),
                "warning" (yellow), "danger" (red), or any hex color code (eg. #439FE0)
            fallback: fallback text
        """
        super().__init__(text="", fallback=fallback, color=color)
        self.blocks = list(blocks)

    @JsonValidator("fields attribute cannot be populated on BlockAttachment")
    def fields_attribute_absent(self) -> bool:
        return not self.fields

    def to_dict(self) -> dict:
        json = super().to_dict()
        json.update({"blocks": extract_json(self.blocks)})
        del json["fields"]  # cannot supply fields and blocks at the same time
        return json


class InteractiveAttachment(Attachment):
    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"callback_id"})

    actions_max_length = 5

    def __init__(
        self,
        *,
        actions: Sequence[Action],
        callback_id: str,
        text: str,
        fallback: Optional[str] = None,
        fields: Optional[Sequence[AttachmentField]] = None,
        color: Optional[str] = None,
        markdown_in: Optional[Sequence[str]] = None,
        title: Optional[str] = None,
        title_link: Optional[str] = None,
        pretext: Optional[str] = None,
        author_name: Optional[str] = None,
        author_subname: Optional[str] = None,
        author_link: Optional[str] = None,
        author_icon: Optional[str] = None,
        image_url: Optional[str] = None,
        thumb_url: Optional[str] = None,
        footer: Optional[str] = None,
        footer_icon: Optional[str] = None,
        ts: Optional[int] = None,
    ):
        """
        An Attachment, but designed to contain interactive Actions
        Considered legacy - recommended replacement is to use message blocks instead.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-interactive-message-field-guide/#attachment_fields
        https://docs.slack.dev/legacy/legacy-messaging/legacy-secondary-message-attachments#fields

        Args:
            actions: A collection of Action objects to include in the attachment.
                Cannot exceed 5 elements.
            callback_id: The ID used to identify this attachment. Will be part of the
                payload sent back to your application.
            text: The main body text of the attachment. It can be formatted as
                plain text, or with markdown by including it in the markdown_in
                parameter. The content will automatically collapse if it contains 700+
                characters or 5+ linebreaks, and will display a "Show more..." link to
                expand the content.
            fallback: A plain text summary of the attachment used in clients that
                don't show formatted text (eg. IRC, mobile notifications).
            fields: An array of AttachmentField objects that get displayed in a
                table-like way. For best results, include no more than 2-3 field
                objects.
            color: Changes the color of the border on the left side of this attachment
                from the default gray. Can either be one of "good" (green), "warning"
                (yellow), "danger" (red), or any hex color code (eg. #439FE0)
            markdown_in: An array of field names that should be formatted by
                markdown syntax - allowed values: "pretext", "text", "fields"
            title: Large title text near the top of the attachment.
            title_link: A valid URL that turns the title text into a hyperlink.
            pretext: Text that appears above the message attachment block. It can
                be formatted as plain text, or with markdown by including it in the
                markdown_in parameter.
            author_name: Small text used to display the author's name.
            author_subname: Small text used to display the author's sub name.
            author_link: A valid URL that will hyperlink the author_name text.
                Will only work if author_name is present.
            author_icon: A valid URL that displays a small 16px by 16px image to
                the left of the author_name text. Will only work if author_name is
                present.
            image_url: A valid URL to an image file that will be displayed at the
                bottom of the attachment. We support GIF, JPEG, PNG, and BMP formats.
                Large images will be resized to a maximum width of 360px or a maximum
                height of 500px, while still maintaining the original aspect ratio.
                Cannot be used with thumb_url.
            thumb_url: A valid URL to an image file that will be displayed as a
                thumbnail on the right side of a message attachment. We currently
                support the following formats: GIF, JPEG, PNG, and BMP. The thumbnail's
                longest dimension will be scaled down to 75px while maintaining the
                aspect ratio of the image. The filesize of the image must also be less
                than 500 KB. For best results, please use images that are already 75px
                by 75px.
            footer: Some brief text to help contextualize and identify an
                attachment. Limited to 300 characters, and may be truncated further when
                displayed to users in environments with limited screen real estate.
            footer_icon: A valid URL to an image file that will be displayed
                beside the footer text. Will only work if footer is present. We'll
                render what you provide at 16px by 16px. It's best to use an image that
                is similarly sized.
            ts: An integer Unix timestamp that is used to related your attachment
                to a specific time. The attachment will display the additional timestamp
                value as part of the attachment's footer. Your message's timestamp will
                be displayed in varying ways, depending on how far in the past or future
                 it is, relative to the present. Form factors, like mobile versus
                 desktop may also transform its rendered appearance.
        """
        super().__init__(
            text=text,
            title=title,
            fallback=fallback,
            fields=fields,
            pretext=pretext,
            title_link=title_link,
            color=color,
            author_name=author_name,
            author_subname=author_subname,
            author_link=author_link,
            author_icon=author_icon,
            image_url=image_url,
            thumb_url=thumb_url,
            footer=footer,
            footer_icon=footer_icon,
            ts=ts,
            markdown_in=markdown_in,
        )
        self.callback_id = callback_id
        self.actions = actions or []

    @JsonValidator(f"actions attribute cannot exceed {actions_max_length} elements")
    def actions_length(self) -> bool:
        return len(self.actions) <= self.actions_max_length

    def to_dict(self) -> dict:
        json = super().to_dict()
        json["actions"] = extract_json(self.actions)
        return json
