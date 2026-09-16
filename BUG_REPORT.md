# Bug Report: Cross-Session Response Delivery in Agent Loop

## Summary
When a user sends a message in Session A, then quickly switches to Session B and sends another message, the response for Session A can appear in Session B instead of Session A.

## Root Cause
The agent loop's `_dispatch` method creates a `TurnDelivery` with the originating session's `chat_id`, but concurrent processing of multiple sessions can cause the delivery route to be overwritten or the response to be delivered to the currently focused session instead of the originating session.

## Reproduction Steps
1. Start a new chat session (Session A)
2. Send a message in Session A
3. While waiting for response, switch to a different chat session (Session B)
4. Send a message in Session B
5. Observe: Response for Session A appears in Session B's chat view

## Expected Behavior
Responses should always be delivered to the session that originated the request, regardless of which session is currently focused.

## Fix Applied
Modified `/Users/user/.nanobot/venv/lib/python3.14/site-packages/nanobot/agent/loop.py`:
1. Capture originating `chat_id` and `session_key` at message receipt time
2. Verify delivery route matches originating session at completion time
3. Force route correction if mismatch detected

## Files Changed
- `nanobot/agent/loop.py` - Added cross-session delivery guard in `_dispatch` method

## Testing
- Verified patch applies cleanly
- Manual testing: send message in Session A, switch to Session B, send message, verify responses route correctly

## Related
- WebSocket channel routing in `nanobot/channels/websocket/runtime.py`
- Turn delivery in `nanobot/agent/turn_delivery.py`