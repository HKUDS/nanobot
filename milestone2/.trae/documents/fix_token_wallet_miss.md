# 修复 token_wallet.py 漏改问题

## 问题描述

**严重程度**: 🔴 严重

**问题**: `token_wallet.py` 第 14-17 行漏改了初始 Token 数量

**影响**: 新钱包被初始化为 1000 而不是 1000000

---

## 修复内容

### 文件: `bff/token_wallet.py`

#### 当前代码 (第 14-17 行):
```python
if not row:
    conn.execute("INSERT INTO wallets (conversation_id, balance, updated_at) VALUES (?, 1000, ?)",
                 (conv_id, datetime.now()))
    return 1000
```

#### 修改后:
```python
if not row:
    conn.execute("INSERT INTO wallets (conversation_id, balance, updated_at) VALUES (?, 1000000, ?)",
                 (conv_id, datetime.now()))
    return 1000000
```

---

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `bff/token_wallet.py` | 第 14, 17 行: 1000 → 1000000 |

---

## 验证清单

修复后验证：
- [ ] 第 14 行的 INSERT 语句: 1000 → 1000000
- [ ] 第 17 行的 return: 1000 → 1000000
