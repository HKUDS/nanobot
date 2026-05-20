# Fix: WeCom WebSocket client initialization and event handlers

## Problem

The WeCom channel fails to start due to three issues in `nanobot/channels/wecom.py`:

1. **WSClient initialization**: The SDK's `WSClient` expects keyword arguments, but nanobot passes a dict, causing `TypeError: __init__() takes 1 positional argument`

2. **connect_async vs connect**: The code uses `connect_async()` but the SDK only provides `connect()`

3. **Event handler signature mismatch**: All event handlers define `frame: Any` as required, but some SDK events (like `connected`, `authenticated`) don't pass a frame argument, causing `TypeError`

## Solution

1. Change `WSClient({...})` to `WSClient(bot_id=..., secret=..., ...)`

2. Change `connect_async()` to `connect()`

3. Make all event handler `frame` parameters optional: `frame: Any = None`

## Changes

- `nanobot/channels/wecom.py`:
  - Line ~120: WSClient instantiation (dict → keyword args)
  - Line ~144: connect_async() → connect()
  - Lines ~157-194: All `_on_*` methods: `frame: Any` → `frame: Any = None`

## Testing

After this fix, WeCom channel connects successfully:
```
WeCom WebSocket connected
WeCom authenticated successfully
```
