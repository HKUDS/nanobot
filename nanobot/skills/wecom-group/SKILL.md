---
name: wecom-group
description: 企业微信群聊管理 — 创建/修改群聊、发送群消息、查询群信息。当用户提及群聊、建群、群成员、群消息、appchat 时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 企业微信群聊管理 (Group Chat)

企业微信应用群聊 API，创建、修改群聊，发送群消息。

## 使用流程

1. 创建应用群聊（需指定群 ID）
2. 添加/删除成员
3. 发送群消息

## API 函数

### create

创建应用群聊。

```
python3 scripts/wecom_group.py create --chatid GROUP_001 --name "项目组" --owner smile --userlist "zhangsan,lisi,wangwu"
```

### get

获取群聊详情。

```
python3 scripts/wecom_group.py get --chatid GROUP_001
```

### update

修改群聊（改名/换群主/加减人）。

```
python3 scripts/wecom_group.py update --chatid GROUP_001 --name "新群名" --add-users "zhaoliu"
python3 scripts/wecom_group.py update --chatid GROUP_001 --del-users "lisi"
```

### send

发送群消息。

```
python3 scripts/wecom_group.py send --chatid GROUP_001 --msgtype text --content "大家好，开会了"
python3 scripts/wecom_group.py send --chatid GROUP_001 --msgtype markdown --content "## 通知\n**下午 3 点开会**"
```

## 群 ID 规则

- 群 ID 由开发者自定义
- 建议格式：`GROUP_xxx` 或 `CHAT_xxx`
- 同一企业内必须唯一

## 群成员限制

| 项目 | 限制 |
|------|------|
| 最少人数 | 2 人（含群主） |
| 最多人数 | 2000 人 |
| 群主变更 | 只能转让给群内成员 |

## 消息类型

| 类型 | 说明 |
|------|------|
| `text` | 文本消息 |
| `image` | 图片消息 |
| `file` | 文件消息 |
| `markdown` | Markdown 消息 |

## 常见错误

| 错误码 | 说明 | 解决方法 |
|--------|------|----------|
| 86001 | chatid 无效 | 检查群 ID 格式 |
| 86002 | 群已存在 | 更换群 ID |
| 86003 | 无权限 | 检查应用群聊权限 |
| 86004 | 用户不在群 | 先添加用户 |

## 配置说明

自动读取 `~/.hiperone/config.json` 中的企业微信配置。

## 官方文档

- [应用群聊 API](https://developer.work.weixin.qq.com/document/path/90245)
- [创建群聊](https://developer.work.weixin.qq.com/document/path/90246)
- [发送群消息](https://developer.work.weixin.qq.com/document/path/90248)
