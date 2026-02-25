from datetime import datetime
from typing import Type, TypeVar, Union


def _from_iso_format_to_datetime(iso_datetime_str: str) -> datetime:
    if "+" not in iso_datetime_str:
        iso_datetime_str += "+00:00"
    return datetime.fromisoformat(iso_datetime_str)


def _from_iso_format_to_unix_timestamp(iso_datetime_str: str) -> float:
    return _from_iso_format_to_datetime(iso_datetime_str).timestamp()


TimestampType = TypeVar("TimestampType", float, int)


def _timestamp_to_type(ts: Union[TimestampType, datetime, str], target_type: Type[TimestampType]) -> TimestampType:
    result: TimestampType

    if isinstance(ts, target_type):
        # unnecessary type casting makes pytype happy
        result = target_type(ts)

        # although a type of the timestamp is just checked,
        # pytype doesn't consider the following line valid:
        # result = ts
        # see https://github.com/google/pytype/issues/1012

    elif isinstance(ts, datetime):
        result = target_type(ts.timestamp())
    elif isinstance(ts, str):
        try:
            result = target_type(ts)
        except ValueError:
            result = target_type(_from_iso_format_to_unix_timestamp(ts))
    else:
        raise ValueError(f"Unsupported data format for timestamp {ts}")

    return result
