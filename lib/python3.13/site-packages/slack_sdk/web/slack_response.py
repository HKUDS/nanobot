"""A Python module for interacting and consuming responses from Slack."""

import logging
from typing import Any, Optional, TypeVar, Union, overload

import slack_sdk.errors as e
from .internal_utils import _next_cursor_is_present

T = TypeVar("T")


class SlackResponse:
    """An iterable container of response data.

    Attributes:
        data (dict): The json-encoded content of the response. Along
            with the headers and status code information.

    Methods:
        validate: Check if the response from Slack was successful.
        get: Retrieves any key from the response data.
        next: Retrieves the next portion of results,
            if 'next_cursor' is present.

    Example:
    ```python
    import os
    import slack

    client = slack.WebClient(token=os.environ['SLACK_API_TOKEN'])

    response1 = client.auth_revoke(test='true')
    assert not response1['revoked']

    response2 = client.auth_test()
    assert response2.get('ok', False)

    users = []
    for page in client.users_list(limit=2):
        users = users + page['members']
    ```

    Note:
        Some responses return collections of information
        like channel and user lists. If they do it's likely
        that you'll only receive a portion of results. This
        object allows you to iterate over the response which
        makes subsequent API requests until your code hits
        'break' or there are no more results to be found.

        Any attributes or methods prefixed with _underscores are
        intended to be "private" internal use only. They may be changed or
        removed at anytime.
    """

    def __init__(
        self,
        *,
        client,
        http_verb: str,
        api_url: str,
        req_args: dict,
        data: Union[dict, bytes],  # data can be binary data
        headers: dict,
        status_code: int,
    ):
        self.http_verb = http_verb
        self.api_url = api_url
        self.req_args = req_args
        self.data = data
        self.headers = headers
        self.status_code = status_code
        self._initial_data = data
        self._iteration = None  # for __iter__ & __next__
        self._client = client
        self._logger = logging.getLogger(__name__)

    def __str__(self):
        """Return the Response data if object is converted to a string."""
        if isinstance(self.data, bytes):
            raise ValueError("As the response.data is binary data, this operation is unsupported")
        return f"{self.data}"

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key):
        """Retrieves any key from the data store.

        Note:
            This is implemented so users can reference the
            SlackResponse object like a dictionary.
            e.g. response["ok"]

        Returns:
            The value from data or None.
        """
        if isinstance(self.data, bytes):
            raise ValueError("As the response.data is binary data, this operation is unsupported")
        if self.data is None:
            raise ValueError("As the response.data is empty, this operation is unsupported")
        return self.data.get(key, None)

    def __iter__(self):
        """Enables the ability to iterate over the response.
        It's required for the iterator protocol.

        Note:
            This enables Slack cursor-based pagination.

        Returns:
            (SlackResponse) self
        """
        self._iteration = 0
        self.data = self._initial_data
        return self

    def __next__(self):
        """Retrieves the next portion of results, if 'next_cursor' is present.

        Note:
            Some responses return collections of information
            like channel and user lists. If they do it's likely
            that you'll only receive a portion of results. This
            method allows you to iterate over the response until
            your code hits 'break' or there are no more results
            to be found.

        Returns:
            (SlackResponse) self
                With the new response data now attached to this object.

        Raises:
            SlackApiError: If the request to the Slack API failed.
            StopIteration: If 'next_cursor' is not present or empty.
        """
        if isinstance(self.data, bytes):
            raise ValueError("As the response.data is binary data, this operation is unsupported")
        self._iteration += 1
        if self._iteration == 1:
            return self
        if _next_cursor_is_present(self.data):
            params = self.req_args.get("params", {})
            if params is None:
                params = {}
            next_cursor = self.data.get("response_metadata", {}).get("next_cursor") or self.data.get("next_cursor")
            params.update({"cursor": next_cursor})
            self.req_args.update({"params": params})

            # This method sends a request in a synchronous way
            response = self._client._request_for_pagination(api_url=self.api_url, req_args=self.req_args)
            self.data = response["data"]
            self.headers = response["headers"]
            self.status_code = response["status_code"]
            return self.validate()
        else:
            raise StopIteration

    @overload
    def get(self, key: str, default: None = None) -> Optional[Any]:
        ...

    @overload
    def get(self, key: str, default: T) -> T:
        ...

    def get(self, key, default=None):
        """Retrieves any key from the response data.

        Note:
            This is implemented so users can reference the
            SlackResponse object like a dictionary.
            e.g. response.get("ok", False)

        Returns:
            The value from data or the specified default.
        """
        if isinstance(self.data, bytes):
            raise ValueError("As the response.data is binary data, this operation is unsupported")
        if self.data is None:
            return None
        return self.data.get(key, default)

    def validate(self):
        """Check if the response from Slack was successful.

        Returns:
            (SlackResponse)
                This method returns it's own object. e.g. 'self'

        Raises:
            SlackApiError: The request to the Slack API failed.
        """
        if self.status_code == 200 and self.data and (isinstance(self.data, bytes) or self.data.get("ok", False)):
            return self
        msg = f"The request to the Slack API failed. (url: {self.api_url})"
        raise e.SlackApiError(message=msg, response=self)
