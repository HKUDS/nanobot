# im reactions

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

This reference is the shared annotation target for the IM reaction APIs:

- `im.reactions.create`
- `im.reactions.list`
- `im.reactions.delete`
- `im.reactions.batch_query`

It focuses on:

- What each reaction method does
- The request/response shape you need when calling the raw API commands
- The complete `emoji_type` list used in reaction payloads and filters

> **Important:** These raw API commands accept structured input through `--params '<json>'` and `--data '<json>'`. They do not expose typed flags such as `--message-id` or `--reaction-type` directly.

## Command Overview

| Method | HTTP | Path | Purpose |
|---|---|---|---|
| `im.reactions.create` | `POST` | `/open-apis/im/v1/messages/{message_id}/reactions` | Add a reaction to one message |
| `im.reactions.list` | `GET` | `/open-apis/im/v1/messages/{message_id}/reactions` | List reaction records on one message |
| `im.reactions.delete` | `DELETE` | `/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}` | Delete one specific reaction record |
| `im.reactions.batch_query` | `POST` | `/open-apis/im/v1/messages/reactions/batch_query` | Query reactions for multiple messages in one request |

## Common Notes

- `message_id` is always an IM message ID such as `om_xxx`
- `reaction_id` is the unique record ID returned after a reaction is added
- `reaction_type.emoji_type` is the enum-like emoji identifier used by both write and read APIs
- Reaction APIs return **reaction records**, not only aggregated counts
- When the operator is a human user, the returned ID type may depend on `user_id_type`

## Inspect Schema

```bash
lark-cli schema im.reactions
lark-cli schema im.reactions.create --format pretty
lark-cli schema im.reactions.list --format pretty
lark-cli schema im.reactions.delete --format pretty
```

If your local build has already exposed the batch API in `schema`, also check:

```bash
lark-cli schema im.reactions.batch_query --format pretty
```

## create

Add a reaction to one message.

```bash
lark-cli im reactions create \
  --params '{"message_id":"om_xxx"}' \
  --data '{"reaction_type":{"emoji_type":"SMILE"}}'
```

### Request

- `--params.message_id`: required message ID
- `--data.reaction_type.emoji_type`: required emoji type

### Response

```json
{
  "reaction_id": "ZCaCIjUBVVWSrm5L-3ZTw_xxx",
  "operator": {
    "operator_id": "ou_xxx",
    "operator_type": "user"
  },
  "action_time": "1663054162546",
  "reaction_type": {
    "emoji_type": "SMILE"
  }
}
```

## list

List reaction records on one message.

```bash
lark-cli im reactions list --params '{"message_id":"om_xxx"}'
lark-cli im reactions list --params '{"message_id":"om_xxx","reaction_type":"SMILE"}'
lark-cli im reactions list --params '{"message_id":"om_xxx","page_size":50}'
lark-cli im reactions list --params '{"message_id":"om_xxx","page_token":"<PAGE_TOKEN>"}'
lark-cli im reactions list --params '{"message_id":"om_xxx","user_id_type":"open_id"}'
```

### Request Parameters (`--params`)

| Parameter | Required | Description |
|---|---|---|
| `message_id` | Yes | Message ID (`om_xxx`) |
| `reaction_type` | No | Filter by one emoji type such as `SMILE` or `LAUGH` |
| `page_size` | No | Number of records per page. Default is 20 |
| `page_token` | No | Pagination token from the previous page |
| `user_id_type` | No | Returned operator ID type when `operator_type=user`: `open_id`, `union_id`, or `user_id` |

### Response Shape

```json
{
  "items": [
    {
      "reaction_id": "ZCaCIjUBVVWSrm5L-3ZTw_xxx",
      "operator": {
        "operator_id": "ou_xxx",
        "operator_type": "user"
      },
      "action_time": "1663054162546",
      "reaction_type": {
        "emoji_type": "SMILE"
      }
    }
  ],
  "has_more": true,
  "page_token": "YhljsPiGfUgnVAg9urvRFd-BvSqRLxxxx"
}
```

### Top-Level Fields

| Field | Type | Meaning |
|---|---|---|
| `items` | `array<object>` | Reaction records for the current page |
| `has_more` | `boolean` | Whether more pages are available |
| `page_token` | `string` | Token for the next page when `has_more=true` |

### `items[]` Fields

| Field | Type | Meaning |
|---|---|---|
| `reaction_id` | `string` | Unique ID of this reaction record |
| `operator` | `object` | Identity of the user or app that added the reaction |
| `action_time` | `string` | Unix timestamp in milliseconds |
| `reaction_type` | `object` | Reaction payload. The key field is `emoji_type` |

### `operator` Fields

| Field | Type | Meaning |
|---|---|---|
| `operator.operator_id` | `string` | Operator ID. If `operator_type=user`, the returned ID type follows `user_id_type`; if `operator_type=app`, this is the app ID |
| `operator.operator_type` | `string` | `user` or `app` |

## delete

Delete one specific reaction record from one message.

```bash
lark-cli im reactions delete \
  --params '{"message_id":"om_xxx","reaction_id":"ZCaCIjUBVVWSrm5L-3ZTw_xxx"}'
```

### Request

- `--params.message_id`: required message ID
- `--params.reaction_id`: required reaction record ID

### Response

The response shape is similar to `create`, and usually echoes:

- `reaction_id`
- `operator`
- `action_time`
- `reaction_type.emoji_type`

## batch_query

Query reactions for multiple messages in one request.

```bash
lark-cli im reactions batch_query \
  --params '{"user_id_type":"open_id"}' \
  --data '{
    "queries":[
      {"message_id":"om_xxx"},
      {"message_id":"om_yyy","page_token":"<PAGE_TOKEN>"}
    ],
    "page_size_per_message":10,
    "reaction_type":"LAUGH"
  }'
```

### Request

#### `--params`

| Parameter | Required | Description |
|---|---|---|
| `user_id_type` | No | Returned user ID type in operator info: `open_id`, `union_id`, or `user_id` |

#### `--data`

| Field | Required | Description |
|---|---|---|
| `queries` | Yes | Array of target messages |
| `queries[].message_id` | No | Message ID to query |
| `queries[].page_token` | No | Continuation token for that message |
| `page_size_per_message` | No | Max reactions returned per message |
| `reaction_type` | No | Filter by one emoji type |

### Response

The meta definition contains three top-level result groups:

| Field | Meaning |
|---|---|
| `success_msg_reaction_details` | Per-message reaction detail records |
| `success_msg_reaction_counts` | Per-message aggregated reaction counts |
| `fail_msg_reaction_details` | Query failures for individual messages |

#### `success_msg_reaction_details`

Each `message_reaction_items[]` element includes:

- `reaction_id`
- `operator`
- `action_time`
- `emoji_type`

#### `success_msg_reaction_counts`

Each aggregated count record includes:

- `message_id`
- `reaction_count[].reaction_type`
- `reaction_count[].count`

#### `fail_msg_reaction_details`

Each failed message record includes:

- `message_id`
- `fail_reason`

Supported `fail_reason` values from meta:

- `invalid`
- `invalid_page_token`
- `no_permission`

## `emoji_type` Field

Reaction emoji identifiers are used in slightly different field names across the APIs:

- `im.reactions.create`: request and response use `reaction_type.emoji_type`
- `im.reactions.list`: request filter uses `reaction_type`, response uses `reaction_type.emoji_type`
- `im.reactions.delete`: response uses `reaction_type.emoji_type`
- `im.reactions.batch_query`: request filter uses top-level `reaction_type`, detail results use `message_reaction_items[].emoji_type`, aggregated results use `reaction_count[].reaction_type`

## Complete `emoji_type` List

The following list is synchronized from the official Feishu reaction emoji documentation:

- Source page: `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/emojis-introduce`
- Markdown source: `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/emojis-introduce.md`

Current count in the fetched source: `185`.

```text
OK, THUMBSUP, THANKS, MUSCLE, FINGERHEART, APPLAUSE, FISTBUMP, JIAYI
DONE, SMILE, BLUSH, LAUGH, SMIRK, LOL, FACEPALM, LOVE
WINK, PROUD, WITTY, SMART, SCOWL, THINKING, SOB, CRY
ERROR, NOSEPICK, HAUGHTY, SLAP, SPITBLOOD, TOASTED, GLANCE, DULL
INNOCENTSMILE, JOYFUL, WOW, TRICK, YEAH, ENOUGH, TEARS, EMBARRASSED
KISS, SMOOCH, DROOL, OBSESSED, MONEY, TEASE, SHOWOFF, COMFORT
CLAP, PRAISE, STRIVE, XBLUSH, SILENT, WAVE, WHAT, FROWN
SHY, DIZZY, LOOKDOWN, CHUCKLE, WAIL, CRAZY, WHIMPER, HUG
BLUBBER, WRONGED, HUSKY, SHHH, SMUG, ANGRY, HAMMER, SHOCKED
TERROR, PETRIFIED, SKULL, SWEAT, SPEECHLESS, SLEEP, DROWSY, YAWN
SICK, PUKE, BETRAYED, HEADSET, EatingFood, MeMeMe, Sigh, Typing
Lemon, Get, LGTM, OnIt, OneSecond, VRHeadset, YouAreTheBest, SALUTE
SHAKE, HIGHFIVE, UPPERLEFT, ThumbsDown, SLIGHT, TONGUE, EYESCLOSED, RoarForYou
CALF, BEAR, BULL, RAINBOWPUKE, ROSE, HEART, PARTY, LIPS
BEER, CAKE, GIFT, CUCUMBER, Drumstick, Pepper, CANDIEDHAWS, BubbleTea
Coffee, Yes, No, OKR, CheckMark, CrossMark, MinusOne, Hundred
AWESOMEN, Pin, Alarm, Loudspeaker, Trophy, Fire, BOMB, Music
XmasTree, Snowman, XmasHat, FIREWORKS, 2022, REDPACKET, FORTUNE, LUCK
FIRECRACKER, StickyRiceBalls, HEARTBROKEN, POOP, StatusFlashOfInspiration, 18X, CLEAVER, Soccer
Basketball, GeneralDoNotDisturb, Status_PrivateMessage, GeneralInMeetingBusy, StatusReading, StatusInFlight, GeneralBusinessTrip, GeneralWorkFromHome
StatusEnjoyLife, GeneralTravellingCar, StatusBus, GeneralSun, GeneralMoonRest, MoonRabbit, Mooncake, JubilantRabbit
TV, Movie, Pumpkin, BeamingFace, Delighted, ColdSweat, FullMoonFace, Partying
GoGoGo, ThanksFace, SaluteFace, Shrug, ClownFace, HappyDragon
```

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
- Official emoji doc: `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/emojis-introduce`
