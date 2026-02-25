"""Errors that can be raised by this SDK"""


class SlackClientError(Exception):
    """Base class for Client errors"""


class BotUserAccessError(SlackClientError):
    """Error raised when an 'xoxb-*' token is
    being used for a Slack API method that only accepts 'xoxp-*' tokens.
    """


class SlackRequestError(SlackClientError):
    """Error raised when there's a problem with the request that's being submitted."""


class SlackApiError(SlackClientError):
    """Error raised when Slack does not send the expected response.

    Attributes:
        response (SlackResponse): The SlackResponse object containing all of the data sent back from the API.

    Note:
        The message (str) passed into the exception is used when
        a user converts the exception to a str.
        i.e. str(SlackApiError("This text will be sent as a string."))
    """

    def __init__(self, message, response):
        msg = f"{message}\nThe server responded with: {response}"
        self.response = response
        super(SlackApiError, self).__init__(msg)


class SlackTokenRotationError(SlackClientError):
    """Error raised when the oauth.v2.access call for token rotation fails"""

    api_error: SlackApiError

    def __init__(self, api_error: SlackApiError):
        self.api_error = api_error


class SlackClientNotConnectedError(SlackClientError):
    """Error raised when attempting to send messages over the websocket when the
    connection is closed."""


class SlackObjectFormationError(SlackClientError):
    """Error raised when a constructed object is not valid/malformed"""


class SlackClientConfigurationError(SlackClientError):
    """Error raised because of invalid configuration on the client side:
    * when attempting to send messages over the websocket when the connection is closed.
    * when external system (e.g., Amazon S3) configuration / credentials are not correct
    """
