# WebUI Follow-Up Suggestions

Follow-up suggestions offer up to three possible next messages after a
successful WebUI reply. They are disabled by default and are available only in
the WebUI; enabling them does not add buttons or messages to other chat
channels.

## Enable Suggestions

1. Open **Settings → System**.
2. Turn on **Follow-up suggestions**.
3. Return to a chat and send a regular message.

The setting is saved immediately and does not require a gateway restart.

To manage the setting in `~/.nanobot/config.json` instead, merge this partial
configuration into the file:

```json
{
  "followUpSuggestions": {
    "enabled": true
  }
}
```

Restart the gateway after editing the configuration file directly.

## Use a Suggestion

Suggestions appear above the composer after a successful reply.

| Composer state | What happens when you select a suggestion |
|---|---|
| Empty | Nanobot sends the suggestion immediately. |
| Contains a draft | A dialog lets you **Cancel**, **Append and send**, or **Replace and send**. |

**Append and send** keeps the draft, adds the suggestion on a new line, and
sends the combined message. **Replace and send** discards the draft and sends
only the suggestion. Use the close button beside the suggestions to dismiss
them without sending anything.

The suggestion list is temporary UI state. Sending a message, dismissing the
list, switching chats, disabling the setting, or reloading the page clears it.
Unsent suggestions are not written to topic history or long-term memory. After
you send a suggestion, the resulting user message follows the normal history
and memory behavior for that chat.

## When Suggestions Are Generated

Nanobot requests suggestions only after a successful regular WebUI message. It
does not request them for slash commands, cancelled turns, failed turns, or
replies in other channels. A generation error or timeout leaves the completed
reply unchanged and shows no suggestions.

The result is limited to three distinct suggestions. Command-like suggestions
and empty results are discarded.

## Model Usage and Privacy

Generating suggestions makes an additional request with the primary provider
and model configured for the completed turn. If a fallback chain is configured,
the suggestion request still uses only the primary provider; it does not retry
fallback models. The request:

- includes up to the six most recent non-empty user and assistant text messages;
- uses the selected model without tools or model reasoning;
- is recorded in WebUI token usage and may add provider cost.

Disable the feature when recent conversation text should not be sent in a
second provider request.

## Troubleshooting

If no suggestions appear:

1. Confirm **Settings → System → Follow-up suggestions** is enabled.
2. Send a regular message rather than a slash command.
3. Confirm the original turn completed successfully.
4. Check that the selected provider is available and inspect the output from
   `nanobot gateway logs` for a follow-up generation warning.

Invalid, empty, or timed-out provider output is intentionally ignored so it
does not interrupt the chat.

## Related Documentation

- [WebUI](./webui.md)
- [Providers and Models](./providers.md)
- [Configuration Reference](./configuration.md)
- [Troubleshooting](./troubleshooting.md)
