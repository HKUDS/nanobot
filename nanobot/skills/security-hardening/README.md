# Security Hardening Skill

让任何 OpenClaw 代理都能一键完成安全加固。

## 快速开始

```bash
# 1. 执行一键加固
node skills/security-hardening/install.js --interactive

# 2. 验证加固结果
node skills/security-hardening/verify.js
```

完成！你的代理现在具备企业级安全防护。

---

## 功能特性

| 防护层级 | 功能 | 描述 |
|---------|------|------|
| 🔴 输入层 | 提示词注入检测 | 识别 "忽略之前指令" 等攻击 |
| 🔴 输入层 | 社工攻击检测 | 识别紧急、权威、利诱话术 |
| 🟠 命令层 | 危险命令拦截 | 阻止 /new /model /reset 等 |
| 🟠 命令层 | 管理员验证 | 硬编码管理员ID，不可伪造 |
| 🟡 会话层 | 持久化防护 | /new 后自动恢复安全规则 |
| 🟡 模型层 | 模型锁定 | 防止降级到弱智模型 |
| 🟢 审计层 | 操作日志 | 所有敏感操作可追溯 |

---

## 工作原理

### 多层防御架构

```
用户输入
  ↓
┌─────────────────────────────────────┐
│  输入过滤器 (guard.js)              │
│  • 提示词注入检测                    │
│  • 社工攻击识别                      │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│  命令拦截器 (command-guard.js)       │
│  • 拦截 /new /model /reset          │
│  • 管理员权限验证                    │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│  工具安全钩子 (security-hooks.js)    │
│  • 敏感工具调用确认                  │
│  • 危险命令过滤                      │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│  审计日志 (auditor.js)               │
│  • 记录所有安全事件                  │
│  • 操作可追溯                        │
└─────────────────────────────────────┘
```

---

## 使用场景

### 场景1：新代理快速加固

你是 OpenClaw 用户，刚创建了新代理：

```bash
# 一键加固
node skills/security-hardening/install.js \
  --admin=ou_your_admin_id \
  --workspace=/path/to/your/workspace

# 验证
node skills/security-hardening/verify.js
```

### 场景2：团队协作统一安全标准

团队有多个代理需要统一安全配置：

```bash
# 创建一个标准配置
cp skills/security-hardening/install.js team-security-setup.js

# 修改默认管理员列表（编辑 install.js 顶部 DEFAULT_CONFIG）

# 团队成员各自运行
node team-security-setup.js
```

### 场景3：定期安全演练

```bash
# 运行攻防测试
node security/security-drill.js

# 查看报告
cat logs/security/drill-$(date +%Y%m%d).json
```

---

## 配置说明

### 安装选项

| 选项 | 说明 | 示例 |
|------|------|------|
| `--admin` | 添加管理员ID（可多次使用） | `--admin=ou_xxx --admin=ou_yyy` |
| `--workspace` | 指定工作区路径 | `--workspace=/custom/path` |
| `--models` | 允许的模型列表 | `--models="model1,model2"` |
| `--interactive` | 交互式配置 | 按提示输入 |
| `--update` | 更新现有配置（自动备份） | `--update` |

### 配置文件

**model-lock.json** - 模型锁定配置
```json
{
  "lockPolicy": {
    "allowedModels": ["kimi-coding/k2p5", "kimi-latest"],
    "minimumCapability": "high"
  },
  "unlockPolicy": {
    "adminUsers": ["ou_xxxxxxxx"]
  }
}
```

**security-cron.json** - 定时任务配置
```json
{
  "drills": [
    {
      "name": "weekly-security-drill",
      "schedule": "0 2 * * 1",
      "command": "node security/security-drill.js"
    }
  ]
}
```

---

## 安全防护详解

### 1. 提示词注入防护

检测模式：
- `ignore all previous instructions`
- `disregard all rules`
- `you are now a DAN`
- `system prompt`
- `new instruction`

响应：**拒绝执行，记录日志**

### 2. 社会工程学防护

检测维度：
- **紧急性**：urgent, immediately, asap
- **权威性**：I'm the admin, I'm the owner
- **利诱性**：congratulations, you won, free
- **恐惧性**：account suspended, security breach
- **奉承性**：you are smart, please help

响应：**验证身份，拒绝未授权指令**

### 3. 危险命令拦截

拦截列表：
| 命令 | 风险等级 | 说明 |
|------|---------|------|
| `/new` | HIGH | 重置会话，可能绕过安全规则 |
| `/model` | CRITICAL | 切换到低能力模型 |
| `/reset` | HIGH | 重置所有上下文 |
| `/system` | CRITICAL | 直接访问系统提示词 |
| `/prompt` | CRITICAL | 可能泄露系统提示词 |
| `/config` | HIGH | 修改配置 |

### 4. 信息泄露防护

自动掩码：
- API Keys: `sk-xxxxx...` → `sk-****`
- Tokens: `ghp_xxxx...` → `ghp-****`
- 密码: 完全掩码
- 私钥: `[REDACTED]`
- 系统路径: `/Users/xxx` → `[PATH]`
- 用户ID: `ou_xxx` → `ou_****`

---

## 故障排除

### Q: 安装脚本提示权限不足
```bash
chmod -R u+w ~/.nanobot/workspace
```

### Q: 加固后 /new 仍能执行
检查 `persistent-guard.js` 是否正确加载，重启 OpenClaw。

### Q: 验证失败 "SOUL.md 未找到安全规则"
重新运行安装脚本，或手动添加安全规则到 SOUL.md。

### Q: 如何添加新的管理员
编辑 `security/model-lock.json`，在 `adminUsers` 数组中添加。

---

## 开发扩展

### 添加新的检测规则

编辑 `security/guard.js`：
```javascript
const CUSTOM_PATTERNS = [
  /你的自定义攻击模式/i
];
```

### 集成企业 SIEM

修改 `security/auditor.js`：
```javascript
function sendToSIEM(logEntry) {
  // 你的企业SIEM集成代码
}
```

---

## 许可证

MIT - 自由使用，自担风险

---

**记住：安全是一场持续战斗，不是一次安装就能完成的。**
