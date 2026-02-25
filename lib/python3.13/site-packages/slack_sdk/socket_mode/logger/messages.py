import re


def debug_redacted_message_string(message: str) -> str:
    xwfp_token_pattern = re.compile(r"\"xwfp-[A-Za-z0-9\-]+\"")  # ex: "xwfp-abc-ABC-1234"
    return re.sub(xwfp_token_pattern, "[[REDACTED]]", message)
