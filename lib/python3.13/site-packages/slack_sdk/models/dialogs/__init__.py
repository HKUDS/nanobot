from abc import ABCMeta, abstractmethod
from json import dumps
from typing import List, Optional, Union, Set, Sequence

from slack_sdk.models import extract_json
from slack_sdk.models.attachments import AbstractActionSelector
from slack_sdk.models.basic_objects import EnumValidator, JsonObject, JsonValidator
from slack_sdk.models.blocks import Option, OptionGroup, DynamicSelectElementTypes

TextElementSubtypes = {"email", "number", "tel", "url"}


class DialogTextComponent(JsonObject, metaclass=ABCMeta):
    attributes = {
        "hint",
        "label",
        "max_length",
        "min_length",
        "name",
        "optional",
        "placeholder",
        "subtype",
        "type",
        "value",
    }

    name_max_length = 300
    label_max_length = 48
    placeholder_max_length = 150
    hint_max_length = 150

    @property
    @abstractmethod
    def type(self):
        pass

    @property
    @abstractmethod
    def max_value_length(self):
        pass

    def __init__(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        placeholder: Optional[str] = None,
        hint: Optional[str] = None,
        value: Optional[str] = None,
        min_length: int = 0,
        max_length: Optional[int] = None,
        subtype: Optional[str] = None,
    ):
        self.name = name
        self.label = label
        self.optional = optional
        self.placeholder = placeholder
        self.hint = hint
        self.value = value
        self.min_length = min_length
        self.max_length = max_length or self.max_value_length
        self.subtype = subtype

    @JsonValidator(f"name attribute cannot exceed {name_max_length} characters")
    def name_length(self) -> bool:
        return len(self.name) < self.name_max_length

    @JsonValidator(f"label attribute cannot exceed {label_max_length} characters")
    def label_length(self) -> bool:
        return len(self.label) < self.label_max_length

    @JsonValidator(f"placeholder attribute cannot exceed {placeholder_max_length} characters")
    def placeholder_length(self) -> bool:
        return self.placeholder is None or len(self.placeholder) < self.placeholder_max_length

    @JsonValidator(f"hint attribute cannot exceed {hint_max_length} characters")
    def hint_length(self) -> bool:
        return self.hint is None or len(self.hint) < self.hint_max_length

    @JsonValidator("value attribute exceeded bounds")
    def value_length(self) -> bool:
        return self.value is None or len(self.value) < self.max_value_length

    @JsonValidator("min_length attribute must be greater than or equal to 0")
    def min_length_above_zero(self) -> bool:
        return self.min_length is None or self.min_length >= 0

    @JsonValidator("min_length attribute exceed bounds")
    def min_length_length(self) -> bool:
        return self.min_length is None or self.min_length <= self.max_value_length

    @JsonValidator("min_length attribute must be less than max value attribute")
    def min_length_below_max_length(self) -> bool:
        return self.min_length is None or self.min_length < self.max_length

    @JsonValidator("max_length attribute must be greater than or equal to 0")
    def max_length_above_zero(self) -> bool:
        return self.max_length is None or self.max_length > 0

    @JsonValidator("max_length attribute exceeded bounds")
    def max_length_length(self) -> bool:
        return self.max_length is None or self.max_length <= self.max_value_length

    @EnumValidator("subtype", TextElementSubtypes)
    def subtype_valid(self) -> bool:
        return self.subtype is None or self.subtype in TextElementSubtypes


class DialogTextField(DialogTextComponent):
    """
    Text elements are single-line plain text fields.

    https://docs.slack.dev/legacy/legacy-dialogs/#text_elements
    """

    type = "text"
    max_value_length = 150


class DialogTextArea(DialogTextComponent):
    """
    A textarea is a multi-line plain text editing control. You've likely encountered
    these on the world wide web. Use this element if you want a relatively long
    answer from users. The element UI provides a remaining character count to the
    max_length you have set or the default, 3000.

    https://docs.slack.dev/legacy/legacy-dialogs/#textarea_elements
    """

    type = "textarea"
    max_value_length = 3000


class AbstractDialogSelector(JsonObject, metaclass=ABCMeta):
    DataSourceTypes = DynamicSelectElementTypes.union({"external", "static"})

    attributes = {"data_source", "label", "name", "optional", "placeholder", "type"}

    name_max_length = 300
    label_max_length = 48
    placeholder_max_length = 150

    @property
    @abstractmethod
    def data_source(self) -> str:
        pass

    def __init__(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[Union[Option, str]] = None,
        placeholder: Optional[str] = None,
    ):
        self.name = name
        self.label = label
        self.optional = optional
        self.value = value
        self.placeholder = placeholder
        self.type = "select"

    @JsonValidator(f"name attribute cannot exceed {name_max_length} characters")
    def name_length(self) -> bool:
        return len(self.name) < self.name_max_length

    @JsonValidator(f"label attribute cannot exceed {label_max_length} characters")
    def label_length(self) -> bool:
        return len(self.label) < self.label_max_length

    @JsonValidator(f"placeholder attribute cannot exceed {placeholder_max_length} characters")
    def placeholder_length(self) -> bool:
        return self.placeholder is None or len(self.placeholder) < self.placeholder_max_length

    @EnumValidator("data_source", DataSourceTypes)
    def data_source_valid(self) -> bool:
        return self.data_source in self.DataSourceTypes

    def to_dict(self) -> dict:
        json = super().to_dict()
        if self.data_source == "external":
            if isinstance(self.value, Option):
                json["selected_options"] = extract_json([self.value], "dialog")
            elif self.value is not None:
                json["selected_options"] = Option.from_single_value(self.value)
        else:
            if isinstance(self.value, Option):
                json["value"] = self.value.value
            elif self.value is not None:
                json["value"] = self.value
        return json


class DialogStaticSelector(AbstractDialogSelector):
    """
    Use the select element for multiple choice selections allowing users to pick a
    single item from a list. True to web roots, this selection is displayed as a
    dropdown menu.

    https://docs.slack.dev/legacy/legacy-dialogs/#select_elements
    """

    data_source = "static"

    options_max_length = 100

    def __init__(
        self,
        *,
        name: str,
        label: str,
        options: Union[Sequence[Option], Sequence[OptionGroup]],
        optional: bool = False,
        value: Optional[Union[Option, str]] = None,
        placeholder: Optional[str] = None,
    ):
        """
        Use the select element for multiple choice selections allowing users to pick
        a single item from a list. True to web roots, this selection is displayed as
        a dropdown menu.

        A select element may contain up to 100 selections, provided as a list of
        Option or OptionGroup objects

        https://docs.slack.dev/legacy/legacy-dialogs/#attributes_select_elements

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            options: A list of up to 100 Option or OptionGroup objects. Object
                types cannot be mixed.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        super().__init__(
            name=name,
            label=label,
            optional=optional,
            value=value,
            placeholder=placeholder,
        )
        self.options = options

    @JsonValidator(f"options attribute cannot exceed {options_max_length} items")
    def options_length(self) -> bool:
        return len(self.options) < self.options_max_length

    def to_dict(self) -> dict:
        json = super().to_dict()
        if isinstance(self.options[0], OptionGroup):
            json["option_groups"] = extract_json(self.options, "dialog")
        else:
            json["options"] = extract_json(self.options, "dialog")
        return json


class DialogUserSelector(AbstractDialogSelector):
    data_source = "users"

    def __init__(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ):
        """
        Now you can easily populate a select menu with a list of users. For example,
        when you are creating a bug tracking app, you want to include a field for an
        assignee. Slack pre-populates the user list in client-side, so your app
        doesn't need access to a related OAuth scope.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_users

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        super().__init__(
            name=name,
            label=label,
            optional=optional,
            value=value,
            placeholder=placeholder,
        )


class DialogChannelSelector(AbstractDialogSelector):
    data_source = "channels"

    def __init__(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ):
        """
        You can also provide a select menu with a list of channels. Specify your
        data_source as channels to limit only to public channels

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_channels_conversations

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        super().__init__(
            name=name,
            label=label,
            optional=optional,
            value=value,
            placeholder=placeholder,
        )


class DialogConversationSelector(AbstractDialogSelector):
    data_source = "conversations"

    def __init__(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ):
        """
        You can also provide a select menu with a list of conversations - including
        private channels, direct messages, MPIMs, and whatever else we consider a
        conversation-like thing.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_channels_conversations

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        super().__init__(
            name=name,
            label=label,
            optional=optional,
            value=value,
            placeholder=placeholder,
        )


class DialogExternalSelector(AbstractDialogSelector):
    data_source = "external"

    @property
    def attributes(self) -> Set[str]:  # type: ignore[override]
        return super().attributes.union({"min_query_length"})

    def __init__(
        self,
        *,
        name: str,
        label: str,
        value: Optional[Option] = None,
        min_query_length: Optional[int] = None,
        optional: Optional[bool] = False,
        placeholder: Optional[str] = None,
    ):
        """
        Use the select element for multiple choice selections allowing users to pick
        a single item from a list. True to web roots, this selection is displayed as
        a dropdown menu.

        A list of options can be loaded from an external URL and used in your dialog
        menus.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_external

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            min_query_length: Specify the number of characters that must be typed
                by a user into a dynamic select menu before dispatching to the app.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value. This should be a single
                Option or OptionGroup that exactly matches one that will be returned
                from your external endpoint.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        super().__init__(
            name=name,
            label=label,
            value=value,
            optional=optional,  # type: ignore[arg-type]
            placeholder=placeholder,
        )
        self.min_query_length = min_query_length


class DialogBuilder(JsonObject):
    attributes: Set[str] = set()

    _callback_id: Optional[str]
    _elements: List[Union[DialogTextComponent, AbstractDialogSelector]]
    _submit_label: Optional[str]
    _notify_on_cancel: bool
    _state: Optional[str]

    title_max_length = 24
    submit_label_max_length = 24
    elements_max_length = 10
    state_max_length = 3000

    def __init__(self):
        """
        Create a DialogBuilder to more easily construct the JSON required to submit a
        dialog to Slack
        """
        self._title = None
        self._callback_id = None
        self._elements = []
        self._submit_label = None
        self._notify_on_cancel = False
        self._state = None

    def title(self, title: str) -> "DialogBuilder":
        """
        Specify a title for this dialog

        Args:
          title: must not exceed 24 characters
        """
        self._title = title
        return self

    def state(self, state: Union[dict, str]) -> "DialogBuilder":
        """
        Pass state into this dialog - dictionaries will be automatically formatted to
        JSON

        Args:
            state: Extra state information that you need to pass from this dialog
                back to your application on submission
        """
        if isinstance(state, dict):
            self._state = dumps(state)
        else:
            self._state = state
        return self

    def callback_id(self, callback_id: str) -> "DialogBuilder":
        """
        Specify a callback ID for this dialog, which your application will then
        receive upon dialog submission

        Args:
          callback_id: a string identifying this particular dialog
        """
        self._callback_id = callback_id
        return self

    def submit_label(self, label: str) -> "DialogBuilder":
        """
        The label to use on the 'Submit' button on the dialog. Defaults to 'Submit'
        if not specified.

        Args:
            label: must not exceed 24 characters, and must be a single word (no
                spaces)
        """
        self._submit_label = label
        return self

    def notify_on_cancel(self, notify: bool) -> "DialogBuilder":
        """
        Whether this dialog should send a request to your application even if the
        user cancels their interaction. Defaults to False.

        Args:
            notify: Set to True to indicate that your application should receive a
                request even if the user cancels interaction with the dialog.
        """
        self._notify_on_cancel = notify
        return self

    def text_field(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        placeholder: Optional[str] = None,
        hint: Optional[str] = None,
        value: Optional[str] = None,
        min_length: int = 0,
        max_length: int = 150,
        subtype: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        Text elements are single-line plain text fields.

        https://docs.slack.dev/legacy/legacy-dialogs/#attributes_text_elements

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. 48 character maximum.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
            hint: Helpful text provided to assist users in answering a question.
                Up to 150 characters.
            value: A default value for this field. Up to 150 characters.
            min_length: Minimum input length allowed for element. Up to 150
                characters. Defaults to 0.
            max_length: Maximum input length allowed for element. Up to 150
                characters. Defaults to 150.
            subtype: A subtype for this text input. Accepts email, number, tel,
                    or url. In some form factors, optimized input is provided for this
                    subtype.
        """
        self._elements.append(
            DialogTextField(
                name=name,
                label=label,
                optional=optional,
                placeholder=placeholder,
                hint=hint,
                value=value,
                min_length=min_length,
                max_length=max_length,
                subtype=subtype,
            )
        )
        return self

    def text_area(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        placeholder: Optional[str] = None,
        hint: Optional[str] = None,
        value: Optional[str] = None,
        min_length: int = 0,
        max_length: int = 3000,
        subtype: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        A textarea is a multi-line plain text editing control. You've likely
        encountered these on the world wide web. Use this element if you want a
        relatively long answer from users. The element UI provides a remaining
        character count to the max_length you have set or the default,
        3000.

        https://docs.slack.dev/legacy/legacy-dialogs/#attributes_textarea_elements

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. 48 character maximum.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
            hint: Helpful text provided to assist users in answering a question.
                Up to 150 characters.
            value: A default value for this field. Up to 3000 characters.
            min_length: Minimum input length allowed for element. 1-3000
                characters. Defaults to 0.
            max_length: Maximum input length allowed for element. 0-3000
                characters. Defaults to 3000.
            subtype: A subtype for this text input. Accepts email, number, tel,
                or url. In some form factors, optimized input is provided for this
                subtype.
        """
        self._elements.append(
            DialogTextArea(
                name=name,
                label=label,
                optional=optional,
                placeholder=placeholder,
                hint=hint,
                value=value,
                min_length=min_length,
                max_length=max_length,
                subtype=subtype,
            )
        )
        return self

    def static_selector(
        self,
        *,
        name: str,
        label: str,
        options: Union[Sequence[Option], Sequence[OptionGroup]],
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        Use the select element for multiple choice selections allowing users to pick
        a single item from a list. True to web roots, this selection is displayed as
        a dropdown menu.

        A select element may contain up to 100 selections, provided as a list of
        Option or OptionGroup objects

        https://docs.slack.dev/legacy/legacy-dialogs/#attributes_select_elements

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            options: A list of up to 100 Option or OptionGroup objects. Object
                types cannot be mixed.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        self._elements.append(
            DialogStaticSelector(
                name=name,
                label=label,
                options=options,
                optional=optional,
                value=value,
                placeholder=placeholder,
            )
        )
        return self

    def external_selector(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[Option] = None,
        placeholder: Optional[str] = None,
        min_query_length: Optional[int] = None,
    ) -> "DialogBuilder":
        """
        Use the select element for multiple choice selections allowing users to pick
        a single item from a list. True to web roots, this selection is displayed as
        a dropdown menu.

        A list of options can be loaded from an external URL and used in your dialog
        menus.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_external

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            min_query_length: Specify the number of characters that must be
                typed by a user into a dynamic select menu before dispatching to your
                application.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value. This should be a single
                Option or OptionGroup that exactly matches one that will be returned
                from your external endpoint.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        self._elements.append(
            DialogExternalSelector(
                name=name,
                label=label,
                optional=optional,
                value=value,
                placeholder=placeholder,
                min_query_length=min_query_length,
            )
        )
        return self

    def user_selector(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        Now you can easily populate a select menu with a list of users. For example,
        when you are creating a bug tracking app, you want to include a field for an
        assignee. Slack pre-populates the user list in client-side, so your app
        doesn't need access to a related OAuth scope.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_users

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        self._elements.append(
            DialogUserSelector(
                name=name,
                label=label,
                optional=optional,
                value=value,
                placeholder=placeholder,
            )
        )
        return self

    def channel_selector(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        You can also provide a select menu with a list of channels. Specify your
        data_source as channels to limit only to public channels

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_channels_conversations

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        self._elements.append(
            DialogChannelSelector(
                name=name,
                label=label,
                optional=optional,
                value=value,
                placeholder=placeholder,
            )
        )
        return self

    def conversation_selector(
        self,
        *,
        name: str,
        label: str,
        optional: bool = False,
        value: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> "DialogBuilder":
        """
        You can also provide a select menu with a list of conversations - including
        private channels, direct messages, MPIMs, and whatever else we consider a
        conversation-like thing.

        https://docs.slack.dev/legacy/legacy-dialogs/#dynamic_select_elements_channels_conversations

        Args:
            name: Name of form element. Required. No more than 300 characters.
            label: Label displayed to user. Required. No more than 48 characters.
            optional: Provide true when the form element is not required. By
                default, form elements are required.
            value: Provide a default selected value.
            placeholder: A string displayed as needed to help guide users in
                completing the element. 150 character maximum.
        """
        self._elements.append(
            DialogConversationSelector(
                name=name,
                label=label,
                optional=optional,
                value=value,
                placeholder=placeholder,
            )
        )
        return self

    @JsonValidator("title attribute is required")
    def title_present(self) -> bool:
        return self._title is not None

    @JsonValidator(f"title attribute cannot exceed {title_max_length} characters")
    def title_length(self) -> bool:
        return self._title is not None and len(self._title) <= self.title_max_length

    @JsonValidator("callback_id attribute is required")
    def callback_id_present(self) -> bool:
        return self._callback_id is not None

    @JsonValidator(f"dialogs must contain between 1 and {elements_max_length} elements")
    def elements_length(self) -> bool:
        return 0 < len(self._elements) <= self.elements_max_length

    @JsonValidator(f"submit_label cannot exceed {submit_label_max_length} characters")
    def submit_label_length(self) -> bool:
        return self._submit_label is None or len(self._submit_label) <= self.submit_label_max_length

    @JsonValidator("submit_label can only be one word")
    def submit_label_valid(self) -> bool:
        return self._submit_label is None or " " not in self._submit_label

    @JsonValidator(f"state cannot exceed {state_max_length} characters")
    def state_length(self) -> bool:
        return not self._state or len(self._state) <= self.state_max_length

    def to_dict(self) -> dict:
        self.validate_json()
        json = {
            "title": self._title,
            "callback_id": self._callback_id,
            "elements": extract_json(self._elements),
            "notify_on_cancel": self._notify_on_cancel,
        }
        if self._submit_label is not None:
            json["submit_label"] = self._submit_label
        if self._state is not None:
            json["state"] = self._state
        return json


class ActionStaticSelector(AbstractActionSelector):
    """
    Use the select element for multiple choice selections allowing users to pick a
    single item from a list. True to web roots, this selection is displayed as a
    dropdown menu.

    https://docs.slack.dev/legacy/legacy-dialogs/#select_elements
    """

    data_source = "static"

    options_max_length = 100

    def __init__(
        self,
        *,
        name: str,
        text: str,
        options: Sequence[Union[Option, OptionGroup]],
        selected_option: Optional[Option] = None,
    ):
        """
        Help users make clear, concise decisions by providing a menu of options
        within messages.

        https://docs.slack.dev/legacy/legacy-messaging/legacy-adding-menus-to-messages/

        Args:
            name: Name this specific action. The name will be returned to your
                Action URL along with the message's callback_id when this action is
                invoked. Use it to identify this particular response path.
            text: The user-facing label for the message button or menu
                representing this action. Cannot contain markup.
            options: A list of no mre than 100 Option or OptionGroup objects
            selected_option: An Option object to pre-select as the default
                value.
        """
        super().__init__(name=name, text=text, selected_option=selected_option)
        self.options = options

    @JsonValidator(f"options attribute cannot exceed {options_max_length} items")
    def options_length(self) -> bool:
        return len(self.options) < self.options_max_length

    def to_dict(self) -> dict:
        json = super().to_dict()
        if isinstance(self.options[0], OptionGroup):
            json["option_groups"] = extract_json(self.options, "action")
        else:
            json["options"] = extract_json(self.options, "action")
        return json


__all__ = [
    "TextElementSubtypes",
    "AbstractDialogSelector",
    "DialogChannelSelector",
    "DialogConversationSelector",
    "DialogExternalSelector",
    "DialogStaticSelector",
    "DialogTextArea",
    "DialogTextComponent",
    "DialogTextField",
    "DialogUserSelector",
    "TextElementSubtypes",
    "DialogBuilder",
]
