from slackify_markdown.slackify import SlackifyMarkdown


def slackify_markdown(markdown: str) -> str:
    """
    Convert markdown to Slack-compatible markdown.
    """
    return SlackifyMarkdown(markdown).slackify()
