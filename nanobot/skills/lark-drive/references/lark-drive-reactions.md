# drive reactions

> **前置条件：** 先阅读 [`../SKILL.md`](../SKILL.md) 了解 Drive 评论卡片模型、评论数/回复数统计口径、`file_token` / `file_type` 规则；再阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

处理文档评论 / 回复上的 reaction（点赞、表情、各表情数量、谁点了什么、添加/删除表情）。这个场景不常见，但规则比较集中：查询时只有在用户明确需要 reaction 信息时才带 `need_reaction=true`；写入时统一使用 `drive file.comment.reply.reactions update_reaction`，操作对象始终是 `reply_id`。

> [!IMPORTANT]
> **`reaction_type` 只能使用本文下方“完整 `reaction_type` 列表”中定义的枚举值。**
> 不要自由填写、不要根据自然语言临时编造、也不要把列表里的 mixed-case 值改写成别的大小写形式。需要写入时，只能从下方枚举中原样选择并传参。

## 何时使用

- 用户明确要求查看评论 / 回复上的 reaction（表情）。
- 用户要统计某条评论卡片有哪些表情、各表情数量，或要看谁点了什么。
- 用户要给评论或回复添加 / 删除 reaction。

## 查询规则

- `drive file.comments list`、`drive file.comments batch_query`、`drive file.comment.replys list` 都支持通过指定`need_reaction`查询reaction信息。
- `need_reaction` 只在用户明确需要 reaction 信息时再带；如果用户只关心评论正文、回复正文、评论数 / 回复数，默认不要加。
- 遍历评论卡片并顺带拿 reaction：使用 `drive file.comments list`。
- 已知评论 ID，批量查看 reaction：使用 `drive file.comments batch_query`，并在请求体里带 `need_reaction=true`。
- 某张评论卡片下继续翻页拉 reply reaction：使用 `drive file.comment.replys list`。
- 如果 `drive file.comments list` 返回的某个 `item.has_more=true`，且用户要完整的 reply reaction 数据，后续每一页 `drive file.comment.replys list` 都要持续带 `need_reaction=true`。

## 查询示例

```bash
# 遍历评论卡片，并把 reaction 一起拿回来
lark-cli drive file.comments list \
  --params '{"file_token":"<DOC_TOKEN>","file_type":"docx","need_reaction":true}'

# 已知 comment_id，批量查询评论卡片 reaction
lark-cli drive file.comments batch_query \
  --params '{"file_token":"<DOC_TOKEN>","file_type":"docx"}' \
  --data '{"comment_ids":["<COMMENT_ID>"],"need_reaction":true}'

# 继续翻某张评论卡片下的 replies，并把 reaction 一起拿回来
lark-cli drive file.comment.replys list \
  --params '{"file_token":"<DOC_TOKEN>","comment_id":"<COMMENT_ID>","file_type":"docx","need_reaction":true}'
```

## 写入规则

- 添加 / 删除 reaction 时，使用 `drive file.comment.reply.reactions update_reaction`。
- 请求里必须带正确的 `file_type`，并在 body 中传 `action=add|delete`、`reply_id`、`reaction_type`。
- `update_reaction` 的操作对象是 `reply_id`，不是 `comment_id`。
- 如果用户说要给“这条评论”加 / 删 reaction，通常需要定位到该评论卡片首条 reply 的 `reply_id` 再操作。

## 写入示例

```bash
# 给某条 reply 添加一个点赞 reaction
lark-cli drive file.comment.reply.reactions update_reaction \
  --params '{"file_token":"<DOC_TOKEN>","file_type":"docx"}' \
  --data '{"action":"add","reply_id":"<REPLY_ID>","reaction_type":"THUMBSUP"}'

# 删除某条 reply 上已有的 DONE reaction
lark-cli drive file.comment.reply.reactions update_reaction \
  --params '{"file_token":"<DOC_TOKEN>","file_type":"docx"}' \
  --data '{"action":"delete","reply_id":"<REPLY_ID>","reaction_type":"DONE"}'
```

> [!CAUTION]
> `update_reaction` 是写入操作。执行前必须确认用户意图，不要默认替用户点表情。

## `reaction_type` 使用规则

- `reaction_type` 必须传平台定义的枚举字符串，大小写敏感。
- 不要擅自把 mixed-case 值改成全大写，例如 `Yes`、`No`、`Get`、`EatingFood`、`CheckMark`、`CrossMark` 都要按原值传。
- **不要编造列表外的 `reaction_type`，也不要把自然语言描述臆造成平台未定义的新枚举**。
- 如果用户给的是自然语言语义（如“点赞”“在处理中”“确认一下”），可以在下方枚举列表内选择语义最接近的现有值；如果是近似映射，应在执行时明确告知用户。

## 常见语义联想

- `Yes`：确认 / 同意 / 批准。
- `No`：拒绝 / 不同意 / 否定。
- `DONE`：已完成 / 已处理。
- `Typing`：正在输入 / 正在处理中 / 正在跟进（近似语义）。
- `OK`：好的 / 收到 / 确认一下。
- `THUMBSUP`：点赞 / 认可。
- `LGTM`：看起来没问题 / 可以继续。

## 完整 `reaction_type` 列表

以下枚举按当前 Drive 评论 reaction 指引维护，使用时请保持原样：

```text
ANGRY, APPLAUSE, ATTENTION, AWESOME, BEAR, BEER, BETRAYED, BIGKISS
BLACKFACE, BLUBBER, BLUSH, BOMB, CAKE, CHUCKLE, CLAP, CLEAVER
COMFORT, CRAZY, CRY, CUCUMBER, DETERGENT, DIZZY, DONE, DONNOTGO
DROOL, DROWSY, DULL, DULLSTARE, EATING, EMBARRASSED, ENOUGH, ERROR
EYESCLOSED, FACEPALM, FINGERHEART, FISTBUMP, FOLLOWME, FROWN, GIFT, GLANCE
GOODJOB, HAMMER, HAUGHTY, HEADSET, HEART, HEARTBROKEN, HIGHFIVE, HUG
HUSKY, INNOCENTSMILE, JIAYI, JOYFUL, KISS, LAUGH, LIPS, LOL
LOOKDOWN, LOVE, MONEY, MUSCLE, NOSEPICK, OBSESSED, OK, PARTY
PETRIFIED, POOP, PRAISE, PROUD, PUKE, RAINBOWPUKE, ROSE, SALUTE
SCOWL, SHAKE, SHHH, SHOCKED, SHOWOFF, SHY, SICK, SILENT
SKULL, SLAP, SLEEP, SLIGHT, SMART, SMILE, SMIRK, SMOOCH
SMUG, SOB, SPEECHLESS, SPITBLOOD, STRIVE, SWEAT, TEARS, TEASE
TERROR, THANKS, THINKING, THUMBSUP, TOASTED, TONGUE, TRICK, UPPERLEFT
WAIL, WAVE, WELLDONE, WHAT, WHIMPER, WINK, WITTY, WOW
WRONGED, XBLUSH, YAWN, YEAH, FIREWORKS, BULL, CALF, AWESOMEN
2021, CANDIEDHAWS, REDPACKET, FORTUNE, LUCK, FIRECRACKER, Yes, No
Get, LGTM, Lemon, EatingFood, Hundred, MinusOne, ThumbsDown, Fire
OKR, Drumstick, BubbleTea, Loudspeaker, Pin, Coffee, Alarm, Trophy
Music, Typing, Pepper, CheckMark, CrossMark
```

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
