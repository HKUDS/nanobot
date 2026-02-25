import re


# Todo: Clean code before release.
def escape_specials(text: str) -> str:
    text = re.sub(r"&", r"&amp;", text)

    text = re.sub(r"<(?![@#!])", r"&lt;", text)

    slack_mentions = []
    for match in re.finditer(r"<[@#!][^>]*>", text):
        slack_mentions.append((match.start(), match.end()))

    result = ""
    for i, char in enumerate(text):
        if char == ">":
            is_mention = False
            for start, end in slack_mentions:
                if start <= i < end:
                    is_mention = True
                    break

            if is_mention:
                result += ">"
            else:
                result += "&gt;"
        else:
            result += char

    return result
