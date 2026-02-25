from abc import ABCMeta, abstractmethod
from functools import wraps
from typing import Callable, Iterable, Set, Union, Any

from slack_sdk.errors import SlackObjectFormationError


class BaseObject:
    """The base class for all model objects in this module"""

    def __str__(self):
        return f"<slack_sdk.{self.__class__.__name__}>"


# Usually, Block Kit components do not allow an empty array for a property value, but there are some exceptions.
EMPTY_ALLOWED_TYPE_AND_PROPERTY_LIST = [
    {"type": "rich_text_section", "property": "elements"},
    {"type": "rich_text_list", "property": "elements"},
    {"type": "rich_text_preformatted", "property": "elements"},
    {"type": "rich_text_quote", "property": "elements"},
]


class JsonObject(BaseObject, metaclass=ABCMeta):
    """The base class for JSON serializable class objects"""

    @property
    @abstractmethod
    def attributes(self) -> Set[str]:
        """Provide a set of attributes of this object that will make up its JSON structure"""
        return set()

    def validate_json(self) -> None:
        """
        Raises:
          SlackObjectFormationError if the object was not valid
        """
        for attribute in (func for func in dir(self) if not func.startswith("__")):
            method = getattr(self, attribute, None)
            if callable(method) and hasattr(method, "validator"):
                method()

    def get_object_attribute(self, key: str):
        return getattr(self, key, None)

    def get_non_null_attributes(self) -> dict:
        """
        Construct a dictionary out of non-null keys (from attributes property)
        present on this object
        """

        def to_dict_compatible(value: Union[dict, list, object, tuple]) -> Union[dict, list, Any]:
            if isinstance(value, (list, tuple)):
                return [to_dict_compatible(v) for v in value]
            else:
                to_dict = getattr(value, "to_dict", None)
                if to_dict and callable(to_dict):
                    return {k: to_dict_compatible(v) for k, v in value.to_dict().items()}  # type: ignore[attr-defined]
                else:
                    return value

        def is_not_empty(self, key: str) -> bool:
            value = self.get_object_attribute(key)
            if value is None:
                return False

            # Usually, Block Kit components do not allow an empty array for a property value, but there are some exceptions.
            # The following code deals with these exceptions:
            type_value = getattr(self, "type", None)
            for empty_allowed in EMPTY_ALLOWED_TYPE_AND_PROPERTY_LIST:
                if type_value == empty_allowed["type"] and key == empty_allowed["property"]:
                    return True

            has_len = getattr(value, "__len__", None) is not None
            if has_len:
                return len(value) > 0
            else:
                return value is not None

        return {
            key: to_dict_compatible(value=self.get_object_attribute(key))
            for key in sorted(self.attributes)
            if is_not_empty(self, key)
        }

    def to_dict(self, *args) -> dict:
        """
        Extract this object as a JSON-compatible, Slack-API-valid dictionary

        Args:
          *args: Any specific formatting args (rare; generally not required)

        Raises:
          SlackObjectFormationError if the object was not valid
        """
        self.validate_json()
        return self.get_non_null_attributes()

    def __repr__(self):
        dict_value = self.get_non_null_attributes()
        if dict_value:
            return f"<slack_sdk.{self.__class__.__name__}: {dict_value}>"
        else:
            return self.__str__()

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, JsonObject):
            return False
        return self.to_dict() == other.to_dict()


class JsonValidator:
    def __init__(self, message: str):
        """
        Decorate a method on a class to mark it as a JSON validator. Validation
            functions should return true if valid, false if not.

        Args:
            message: Message to be attached to the thrown SlackObjectFormationError
        """
        self.message = message

    def __call__(self, func: Callable) -> Callable[..., None]:
        @wraps(func)
        def wrapped_f(*args, **kwargs):
            if not func(*args, **kwargs):
                raise SlackObjectFormationError(self.message)

        wrapped_f.validator = True  # type: ignore[attr-defined]
        return wrapped_f


class EnumValidator(JsonValidator):
    def __init__(self, attribute: str, enum: Iterable[str]):
        super().__init__(f"{attribute} attribute must be one of the following values: " f"{', '.join(enum)}")
