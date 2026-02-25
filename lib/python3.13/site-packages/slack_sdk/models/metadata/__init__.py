from typing import Dict, Any, Union, Optional, List
from slack_sdk.models.basic_objects import JsonObject, EnumValidator


class Metadata(JsonObject):
    """Message metadata

    https://docs.slack.dev/messaging/message-metadata/
    """

    attributes = {
        "event_type",
        "event_payload",
    }

    def __init__(
        self,
        event_type: str,
        event_payload: Dict[str, Any],
        **kwargs,
    ):
        self.event_type = event_type
        self.event_payload = event_payload
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


#
# Work object entity metadata
# https://docs.slack.dev/messaging/work-objects/
#


"""Entity types"""
EntityType = {
    "slack#/entities/task",
    "slack#/entities/file",
    "slack#/entities/item",
    "slack#/entities/incident",
    "slack#/entities/content_item",
}


"""Custom field types"""
CustomFieldType = {
    "integer",
    "string",
    "array",
    "boolean",
    "slack#/types/date",
    "slack#/types/timestamp",
    "slack#/types/image",
    "slack#/types/channel_id",
    "slack#/types/user",
    "slack#/types/entity_ref",
    "slack#/types/link",
    "slack#/types/email",
}


class ExternalRef(JsonObject):
    """Reference (and optional type) used to identify an entity within the developer's system"""

    attributes = {
        "id",
        "type",
    }

    def __init__(
        self,
        id: str,
        type: Optional[str] = None,
        **kwargs,
    ):
        self.id = id
        self.type = type
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class FileEntitySlackFile(JsonObject):
    """Slack file reference for file entities"""

    attributes = {
        "id",
        "type",
    }

    def __init__(
        self,
        id: str,
        type: Optional[str] = None,
        **kwargs,
    ):
        self.id = id
        self.type = type
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityIconSlackFile(JsonObject):
    """Slack file reference for entity icon"""

    attributes = {
        "id",
        "url",
    }

    def __init__(
        self,
        id: Optional[str] = None,
        url: Optional[str] = None,
        **kwargs,
    ):
        self.id = id
        self.url = url
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityIconField(JsonObject):
    """Icon field for entity attributes"""

    attributes = {
        "alt_text",
        "url",
        "slack_file",
    }

    def __init__(
        self,
        alt_text: str,
        url: Optional[str] = None,
        slack_file: Optional[Union[Dict[str, Any], EntityIconSlackFile]] = None,
        **kwargs,
    ):
        self.alt_text = alt_text
        self.url = url
        self.slack_file = slack_file
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityEditSelectConfig(JsonObject):
    """Select configuration for entity edit support"""

    attributes = {
        "current_value",
        "current_values",
        "static_options",
        "fetch_options_dynamically",
        "min_query_length",
    }

    def __init__(
        self,
        current_value: Optional[str] = None,
        current_values: Optional[List[str]] = None,
        static_options: Optional[List[Dict[str, Any]]] = None,  # Option[]
        fetch_options_dynamically: Optional[bool] = None,
        min_query_length: Optional[int] = None,
        **kwargs,
    ):
        self.current_value = current_value
        self.current_values = current_values
        self.static_options = static_options
        self.fetch_options_dynamically = fetch_options_dynamically
        self.min_query_length = min_query_length
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityEditNumberConfig(JsonObject):
    """Number configuration for entity edit support"""

    attributes = {
        "is_decimal_allowed",
        "min_value",
        "max_value",
    }

    def __init__(
        self,
        is_decimal_allowed: Optional[bool] = None,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        **kwargs,
    ):
        self.is_decimal_allowed = is_decimal_allowed
        self.min_value = min_value
        self.max_value = max_value
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityEditTextConfig(JsonObject):
    """Text configuration for entity edit support"""

    attributes = {
        "min_length",
        "max_length",
    }

    def __init__(
        self,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        **kwargs,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityEditSupport(JsonObject):
    """Edit support configuration for entity fields"""

    attributes = {
        "enabled",
        "placeholder",
        "hint",
        "optional",
        "select",
        "number",
        "text",
    }

    def __init__(
        self,
        enabled: bool,
        placeholder: Optional[Dict[str, Any]] = None,  # PlainTextElement
        hint: Optional[Dict[str, Any]] = None,  # PlainTextElement
        optional: Optional[bool] = None,
        select: Optional[Union[Dict[str, Any], EntityEditSelectConfig]] = None,
        number: Optional[Union[Dict[str, Any], EntityEditNumberConfig]] = None,
        text: Optional[Union[Dict[str, Any], EntityEditTextConfig]] = None,
        **kwargs,
    ):
        self.enabled = enabled
        self.placeholder = placeholder
        self.hint = hint
        self.optional = optional
        self.select = select
        self.number = number
        self.text = text
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityFullSizePreviewError(JsonObject):
    """Error information for full-size preview"""

    attributes = {
        "code",
        "message",
    }

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        **kwargs,
    ):
        self.code = code
        self.message = message
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityFullSizePreview(JsonObject):
    """Full-size preview configuration for entity"""

    attributes = {
        "is_supported",
        "preview_url",
        "mime_type",
        "error",
    }

    def __init__(
        self,
        is_supported: bool,
        preview_url: Optional[str] = None,
        mime_type: Optional[str] = None,
        error: Optional[Union[Dict[str, Any], EntityFullSizePreviewError]] = None,
        **kwargs,
    ):
        self.is_supported = is_supported
        self.preview_url = preview_url
        self.mime_type = mime_type
        self.error = error
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityUserIDField(JsonObject):
    """User ID field for entity"""

    attributes = {
        "user_id",
    }

    def __init__(
        self,
        user_id: str,
        **kwargs,
    ):
        self.user_id = user_id
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityUserField(JsonObject):
    """User field for entity"""

    attributes = {
        "text",
        "url",
        "email",
        "icon",
    }

    def __init__(
        self,
        text: str,
        url: Optional[str] = None,
        email: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        **kwargs,
    ):
        self.text = text
        self.url = url
        self.email = email
        self.icon = icon
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityRefField(JsonObject):
    """Entity reference field"""

    attributes = {
        "entity_url",
        "external_ref",
        "title",
        "display_type",
        "icon",
    }

    def __init__(
        self,
        entity_url: str,
        external_ref: Union[Dict[str, Any], ExternalRef],
        title: str,
        display_type: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        **kwargs,
    ):
        self.entity_url = entity_url
        self.external_ref = external_ref
        self.title = title
        self.display_type = display_type
        self.icon = icon
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityTypedField(JsonObject):
    """Typed field for entity with various display options"""

    attributes = {
        "type",
        "label",
        "value",
        "link",
        "icon",
        "long",
        "format",
        "image_url",
        "slack_file",
        "alt_text",
        "edit",
        "tag_color",
        "user",
        "entity_ref",
    }

    def __init__(
        self,
        type: str,
        label: Optional[str] = None,
        value: Optional[Union[str, int]] = None,
        link: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        long: Optional[bool] = None,
        format: Optional[str] = None,
        image_url: Optional[str] = None,
        slack_file: Optional[Dict[str, Any]] = None,
        alt_text: Optional[str] = None,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        tag_color: Optional[str] = None,
        user: Optional[Union[Dict[str, Any], EntityUserIDField, EntityUserField]] = None,
        entity_ref: Optional[Union[Dict[str, Any], EntityRefField]] = None,
        **kwargs,
    ):
        self.type = type
        self.label = label
        self.value = value
        self.link = link
        self.icon = icon
        self.long = long
        self.format = format
        self.image_url = image_url
        self.slack_file = slack_file
        self.alt_text = alt_text
        self.edit = edit
        self.tag_color = tag_color
        self.user = user
        self.entity_ref = entity_ref
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityStringField(JsonObject):
    """String field for entity"""

    attributes = {
        "value",
        "label",
        "format",
        "link",
        "icon",
        "long",
        "type",
        "tag_color",
        "edit",
    }

    def __init__(
        self,
        value: str,
        label: Optional[str] = None,
        format: Optional[str] = None,
        link: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        long: Optional[bool] = None,
        type: Optional[str] = None,
        tag_color: Optional[str] = None,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        **kwargs,
    ):
        self.value = value
        self.label = label
        self.format = format
        self.link = link
        self.icon = icon
        self.long = long
        self.type = type
        self.tag_color = tag_color
        self.edit = edit
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityTimestampField(JsonObject):
    """Timestamp field for entity"""

    attributes = {
        "value",
        "label",
        "type",
        "edit",
    }

    def __init__(
        self,
        value: int,
        label: Optional[str] = None,
        type: Optional[str] = None,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        **kwargs,
    ):
        self.value = value
        self.label = label
        self.type = type
        self.edit = edit
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityImageField(JsonObject):
    """Image field for entity"""

    attributes = {
        "alt_text",
        "label",
        "image_url",
        "slack_file",
        "title",
        "type",
    }

    def __init__(
        self,
        alt_text: str,
        label: Optional[str] = None,
        image_url: Optional[str] = None,
        slack_file: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        type: Optional[str] = None,
        **kwargs,
    ):
        self.alt_text = alt_text
        self.label = label
        self.image_url = image_url
        self.slack_file = slack_file
        self.title = title
        self.type = type
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityBooleanCheckboxField(JsonObject):
    """Boolean checkbox properties"""

    attributes = {"type", "text", "description"}

    def __init__(
        self,
        type: str,
        text: str,
        description: Optional[str],
        **kwargs,
    ):
        self.type = type
        self.text = text
        self.description = description
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityBooleanTextField(JsonObject):
    """Boolean text properties"""

    attributes = {"type", "true_text", "false_text", "true_description", "false_description"}

    def __init__(
        self,
        type: str,
        true_text: str,
        false_text: str,
        true_description: Optional[str],
        false_description: Optional[str],
        **kwargs,
    ):
        self.type = type
        self.true_text = (true_text,)
        self.false_text = (false_text,)
        self.true_description = (true_description,)
        self.false_description = (false_description,)
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityArrayItemField(JsonObject):
    """Array item field for entity (similar to EntityTypedField but with optional type)"""

    attributes = {
        "type",
        "label",
        "value",
        "link",
        "icon",
        "long",
        "format",
        "image_url",
        "slack_file",
        "alt_text",
        "edit",
        "tag_color",
        "user",
        "entity_ref",
    }

    def __init__(
        self,
        type: Optional[str] = None,
        label: Optional[str] = None,
        value: Optional[Union[str, int]] = None,
        link: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        long: Optional[bool] = None,
        format: Optional[str] = None,
        image_url: Optional[str] = None,
        slack_file: Optional[Dict[str, Any]] = None,
        alt_text: Optional[str] = None,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        tag_color: Optional[str] = None,
        user: Optional[Union[Dict[str, Any], EntityUserIDField, EntityUserField]] = None,
        entity_ref: Optional[Union[Dict[str, Any], EntityRefField]] = None,
        **kwargs,
    ):
        self.type = type
        self.label = label
        self.value = value
        self.link = link
        self.icon = icon
        self.long = long
        self.format = format
        self.image_url = image_url
        self.slack_file = slack_file
        self.alt_text = alt_text
        self.edit = edit
        self.tag_color = tag_color
        self.user = user
        self.entity_ref = entity_ref
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityCustomField(JsonObject):
    """Custom field for entity with flexible types"""

    attributes = {
        "label",
        "key",
        "type",
        "value",
        "link",
        "icon",
        "long",
        "format",
        "image_url",
        "slack_file",
        "alt_text",
        "tag_color",
        "edit",
        "item_type",
        "user",
        "entity_ref",
        "boolean",
    }

    def __init__(
        self,
        label: str,
        key: str,
        type: str,
        value: Optional[Union[str, int, List[Union[Dict[str, Any], EntityArrayItemField]]]] = None,
        link: Optional[str] = None,
        icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        long: Optional[bool] = None,
        format: Optional[str] = None,
        image_url: Optional[str] = None,
        slack_file: Optional[Dict[str, Any]] = None,
        alt_text: Optional[str] = None,
        tag_color: Optional[str] = None,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        item_type: Optional[str] = None,
        user: Optional[Union[Dict[str, Any], EntityUserIDField, EntityUserField]] = None,
        entity_ref: Optional[Union[Dict[str, Any], EntityRefField]] = None,
        boolean: Optional[Union[Dict[str, Any], EntityBooleanCheckboxField, EntityBooleanTextField]] = None,
        **kwargs,
    ):
        self.label = label
        self.key = key
        self.type = type
        self.value = value
        self.link = link
        self.icon = icon
        self.long = long
        self.format = format
        self.image_url = image_url
        self.slack_file = slack_file
        self.alt_text = alt_text
        self.tag_color = tag_color
        self.edit = edit
        self.item_type = item_type
        self.user = user
        self.entity_ref = entity_ref
        self.boolean = boolean
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()

    @EnumValidator("type", CustomFieldType)
    def type_valid(self):
        return self.type is None or self.type in CustomFieldType


class FileEntityFields(JsonObject):
    """Fields specific to file entities"""

    attributes = {
        "preview",
        "created_by",
        "date_created",
        "date_updated",
        "last_modified_by",
        "file_size",
        "mime_type",
        "full_size_preview",
    }

    def __init__(
        self,
        preview: Optional[Union[Dict[str, Any], EntityImageField]] = None,
        created_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        date_created: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        date_updated: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        last_modified_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        file_size: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        mime_type: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        full_size_preview: Optional[Union[Dict[str, Any], EntityFullSizePreview]] = None,
        **kwargs,
    ):
        self.preview = preview
        self.created_by = created_by
        self.date_created = date_created
        self.date_updated = date_updated
        self.last_modified_by = last_modified_by
        self.file_size = file_size
        self.mime_type = mime_type
        self.full_size_preview = full_size_preview
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class TaskEntityFields(JsonObject):
    """Fields specific to task entities"""

    attributes = {
        "description",
        "created_by",
        "date_created",
        "date_updated",
        "assignee",
        "status",
        "due_date",
        "priority",
    }

    def __init__(
        self,
        description: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        created_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        date_created: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        date_updated: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        assignee: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        status: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        due_date: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        priority: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        **kwargs,
    ):
        self.description = description
        self.created_by = created_by
        self.date_created = date_created
        self.date_updated = date_updated
        self.assignee = assignee
        self.status = status
        self.due_date = due_date
        self.priority = priority
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class IncidentEntityFields(JsonObject):
    """Fields specific to incident entities"""

    attributes = {
        "status",
        "priority",
        "urgency",
        "created_by",
        "assigned_to",
        "date_created",
        "date_updated",
        "description",
        "service",
    }

    def __init__(
        self,
        status: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        priority: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        urgency: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        created_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        assigned_to: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        date_created: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        date_updated: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        description: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        service: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        **kwargs,
    ):
        self.status = status
        self.priority = priority
        self.urgency = urgency
        self.created_by = created_by
        self.assigned_to = assigned_to
        self.date_created = date_created
        self.date_updated = date_updated
        self.description = description
        self.service = service
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class ContentItemEntityFields(JsonObject):
    """Fields specific to content item entities"""

    attributes = {
        "preview",
        "description",
        "created_by",
        "date_created",
        "date_updated",
        "last_modified_by",
    }

    def __init__(
        self,
        preview: Optional[Union[Dict[str, Any], EntityImageField]] = None,
        description: Optional[Union[Dict[str, Any], EntityStringField]] = None,
        created_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        date_created: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        date_updated: Optional[Union[Dict[str, Any], EntityTimestampField]] = None,
        last_modified_by: Optional[Union[Dict[str, Any], EntityTypedField]] = None,
        **kwargs,
    ):
        self.preview = preview
        self.description = description
        self.created_by = created_by
        self.date_created = date_created
        self.date_updated = date_updated
        self.last_modified_by = last_modified_by
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityActionProcessingState(JsonObject):
    """Processing state configuration for entity action button"""

    attributes = {
        "enabled",
        "interstitial_text",
    }

    def __init__(
        self,
        enabled: bool,
        interstitial_text: Optional[str] = None,
        **kwargs,
    ):
        self.enabled = enabled
        self.interstitial_text = interstitial_text
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityActionButton(JsonObject):
    """Action button for entity"""

    attributes = {
        "text",
        "action_id",
        "value",
        "style",
        "url",
        "accessibility_label",
        "processing_state",
    }

    def __init__(
        self,
        text: str,
        action_id: str,
        value: Optional[str] = None,
        style: Optional[str] = None,
        url: Optional[str] = None,
        accessibility_label: Optional[str] = None,
        processing_state: Optional[Union[Dict[str, Any], EntityActionProcessingState]] = None,
        **kwargs,
    ):
        self.text = text
        self.action_id = action_id
        self.value = value
        self.style = style
        self.url = url
        self.accessibility_label = accessibility_label
        self.processing_state = processing_state
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityTitle(JsonObject):
    """Title for entity attributes"""

    attributes = {
        "text",
        "edit",
    }

    def __init__(
        self,
        text: str,
        edit: Optional[Union[Dict[str, Any], EntityEditSupport]] = None,
        **kwargs,
    ):
        self.text = text
        self.edit = edit
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityAttributes(JsonObject):
    """Attributes for an entity"""

    attributes = {
        "title",
        "display_type",
        "display_id",
        "product_icon",
        "product_name",
        "locale",
        "full_size_preview",
        "metadata_last_modified",
    }

    def __init__(
        self,
        title: Union[Dict[str, Any], EntityTitle],
        display_type: Optional[str] = None,
        display_id: Optional[str] = None,
        product_icon: Optional[Union[Dict[str, Any], EntityIconField]] = None,
        product_name: Optional[str] = None,
        locale: Optional[str] = None,
        full_size_preview: Optional[Union[Dict[str, Any], EntityFullSizePreview]] = None,
        metadata_last_modified: Optional[int] = None,
        **kwargs,
    ):
        self.title = title
        self.display_type = display_type
        self.display_id = display_id
        self.product_icon = product_icon
        self.product_name = product_name
        self.locale = locale
        self.full_size_preview = full_size_preview
        self.metadata_last_modified = metadata_last_modified
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityActions(JsonObject):
    """Actions configuration for entity"""

    attributes = {
        "primary_actions",
        "overflow_actions",
    }

    def __init__(
        self,
        primary_actions: Optional[List[Union[Dict[str, Any], EntityActionButton]]] = None,
        overflow_actions: Optional[List[Union[Dict[str, Any], EntityActionButton]]] = None,
        **kwargs,
    ):
        self.primary_actions = primary_actions
        self.overflow_actions = overflow_actions
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityPayload(JsonObject):
    """Payload schema for an entity"""

    attributes = {
        "attributes",
        "fields",
        "custom_fields",
        "slack_file",
        "display_order",
        "actions",
    }

    def __init__(
        self,
        attributes: Union[Dict[str, Any], EntityAttributes],
        fields: Optional[
            Union[Dict[str, Any], ContentItemEntityFields, FileEntityFields, IncidentEntityFields, TaskEntityFields]
        ] = None,
        custom_fields: Optional[List[Union[Dict[str, Any], EntityCustomField]]] = None,
        slack_file: Optional[Union[Dict[str, Any], FileEntitySlackFile]] = None,
        display_order: Optional[List[str]] = None,
        actions: Optional[Union[Dict[str, Any], EntityActions]] = None,
        **kwargs,
    ):
        # Store entity attributes data with a different internal name to avoid
        # shadowing the class-level 'attributes' set used for JSON serialization
        self._entity_attributes = attributes
        self.fields = fields
        self.custom_fields = custom_fields
        self.slack_file = slack_file
        self.display_order = display_order
        self.actions = actions
        self.additional_attributes = kwargs

    @property
    def entity_attributes(self) -> Union[Dict[str, Any], EntityAttributes]:
        """Get the entity attributes data.

        Note: Use this property to access the attributes data. The class-level
        'attributes' is reserved for the JSON serialization schema.
        """
        return self._entity_attributes

    @entity_attributes.setter
    def entity_attributes(self, value: Union[Dict[str, Any], EntityAttributes]):
        """Set the entity attributes data."""
        self._entity_attributes = value

    def get_object_attribute(self, key: str):
        if key == "attributes":
            return self._entity_attributes
        else:
            return getattr(self, key, None)

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()


class EntityMetadata(JsonObject):
    """Work object entity metadata

    https://docs.slack.dev/messaging/work-objects/
    """

    attributes = {
        "entity_type",
        "entity_payload",
        "external_ref",
        "url",
        "app_unfurl_url",
    }

    def __init__(
        self,
        entity_type: str,
        entity_payload: Union[Dict[str, Any], EntityPayload],
        external_ref: Union[Dict[str, Any], ExternalRef],
        url: str,
        app_unfurl_url: Optional[str] = None,
        **kwargs,
    ):
        self.entity_type = entity_type
        self.entity_payload = entity_payload
        self.external_ref = external_ref
        self.url = url
        self.app_unfurl_url = app_unfurl_url
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()

    @EnumValidator("entity_type", EntityType)
    def entity_type_valid(self):
        return self.entity_type is None or self.entity_type in EntityType


class EventAndEntityMetadata(JsonObject):
    """Message metadata with entities

    https://docs.slack.dev/messaging/message-metadata/
    https://docs.slack.dev/messaging/work-objects/
    """

    attributes = {"event_type", "event_payload", "entities"}

    def __init__(
        self,
        event_type: Optional[str] = None,
        event_payload: Optional[Dict[str, Any]] = None,
        entities: Optional[List[Union[Dict[str, Any], EntityMetadata]]] = None,
        **kwargs,
    ):
        self.event_type = event_type
        self.event_payload = event_payload
        self.entities = entities
        self.additional_attributes = kwargs

    def __str__(self):
        return str(self.get_non_null_attributes())

    def __repr__(self):
        return self.__str__()
