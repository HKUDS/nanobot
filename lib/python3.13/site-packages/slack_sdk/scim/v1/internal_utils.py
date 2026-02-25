import copy
import logging
import re
from typing import Dict, Callable
from typing import Union, Optional, Any
from urllib.parse import quote

from .default_arg import DefaultArg, NotGiven
from slack_sdk.web.internal_utils import get_user_agent


def _build_query(params: Optional[Dict[str, Any]]) -> str:
    if params is not None and len(params) > 0:
        return "&".join({f"{quote(str(k))}={quote(str(v))}" for k, v in params.items() if v is not None})
    return ""


def _is_iterable(obj: Union[Optional[Any], DefaultArg]) -> bool:
    return obj is not None and obj is not NotGiven


def _to_dict_without_not_given(obj: Any) -> dict:
    dict_value = {}
    given_dict = obj if isinstance(obj, dict) else vars(obj)
    for key, value in given_dict.items():
        if key == "unknown_fields":
            if value is not None:
                converted = _to_dict_without_not_given(value)
                dict_value.update(converted)
            continue

        dict_key = _to_camel_case_key(key)
        if value is NotGiven:
            continue
        if isinstance(value, list):
            dict_value[dict_key] = [elem.to_dict() if hasattr(elem, "to_dict") else elem for elem in value]
        elif isinstance(value, dict):
            dict_value[dict_key] = _to_dict_without_not_given(value)
        else:
            dict_value[dict_key] = value.to_dict() if hasattr(value, "to_dict") else value
    return dict_value


def _create_copy(original: Any) -> Any:
    return copy.deepcopy(original)


def _to_camel_case_key(key: str) -> str:
    next_to_capital = False
    result = ""
    for c in key:
        if c == "_":
            next_to_capital = True
        elif next_to_capital:
            result += c.upper()
            next_to_capital = False
        else:
            result += c
    return result


def _to_snake_cased(original: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _convert_dict_keys(
        original,
        {},
        lambda s: re.sub(
            "^_",
            "",
            "".join(["_" + c.lower() if c.isupper() else c for c in s]),
        ),
    )


def _to_camel_cased(original: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _convert_dict_keys(
        original,
        {},
        _to_camel_case_key,
    )


def _convert_dict_keys(
    original_dict: Optional[Dict[str, Any]],
    result_dict: Dict[str, Any],
    convert: Callable[[str], str],
) -> Optional[Dict[str, Any]]:
    if original_dict is None:
        return result_dict

    for original_key, original_value in original_dict.items():
        new_key = convert(original_key)
        if isinstance(original_value, dict):
            result_dict[new_key] = {}
            new_value = _convert_dict_keys(original_value, result_dict[new_key], convert)
            result_dict[new_key] = new_value
        elif isinstance(original_value, list):
            result_dict[new_key] = []
            is_dict = len(original_value) > 0 and isinstance(original_value[0], dict)
            for element in original_value:
                if is_dict:
                    if isinstance(element, dict):
                        new_element = {}
                        for elem_key, elem_value in element.items():
                            new_element[convert(elem_key)] = (
                                _convert_dict_keys(elem_value, {}, convert)
                                if isinstance(elem_value, dict)
                                else _create_copy(elem_value)
                            )
                        result_dict[new_key].append(new_element)
                else:
                    result_dict[new_key].append(_create_copy(original_value))
        else:
            result_dict[new_key] = _create_copy(original_value)
    return result_dict


def _build_request_headers(
    token: str,
    default_headers: Dict[str, str],
    additional_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    request_headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": f"Bearer {token}",
    }
    if default_headers is None or "User-Agent" not in default_headers:
        request_headers["User-Agent"] = get_user_agent()
    if default_headers is not None:
        request_headers.update(default_headers)
    if additional_headers is not None:
        request_headers.update(additional_headers)
    return request_headers


def _debug_log_response(
    logger,
    resp: "SCIMResponse",  # noqa: F821
) -> None:
    if logger.level <= logging.DEBUG:
        logger.debug(
            "Received the following response - "
            f"status: {resp.status_code}, "
            f"headers: {(dict(resp.headers))}, "
            f"body: {resp.raw_body}"
        )
