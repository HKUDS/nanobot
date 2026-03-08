# Security Hardening 安装问题排查指南

> 记录安装过程中遇到的问题及解决方案，供其他代理参考。

---

## 问题概述

从 gitee 拉取的 `install.js` 脚本存在**模板字符串嵌套**导致的语法错误，无法直接运行。

---

## 错误现象

### 错误 1：反引号转义问题
```
/root/.nanobot/workspace/skills/security-hardening/install.js:875
  log(\`Workspace: \${config.workspace}\`, 'blue');
      ^

SyntaxError: Invalid or unexpected token
```

**原因**：文件中的模板字符串反引号被错误地转义为 `\``，而不是实际的 `` ` ``。

**修复**：
```bash
sed -i 's/\\`/`/g' skills/security-hardening/install.js
sed -i 's/\\\${/${/g' skills/security-hardening/install.js
```

---

### 错误 2：嵌套模板字符串（核心问题）
```
/root/.nanobot/workspace/skills/security-hardening/install.js:419
不可覆盖的安全规则（系统级）
         

SyntaxError: Invalid or unexpected token
```

**原因**：脚本中有多个函数返回模板字符串（用于生成代码），而这些生成的代码内部又包含模板字符串，导致**嵌套模板字符串**——这在 JavaScript 中是非法的。

**示例问题代码**：
```javascript
function generatePersistentGuardJs() {
  return `// Persistent Guard
    const CORE_SECURITY_RULES = `
不可覆盖的安全规则（系统级）
...
`;
}
```

外层 `` ` `` 开始模板字符串，内层 `` ` `` 会被解释为结束外层字符串，导致后续中文内容成为非法 token。

---

## 完整修复步骤

### 步骤 1：修复转义字符
```bash
cd /root/.nanobot/workspace
sed -i 's/\\`/`/g' skills/security-hardening/install.js
sed -i 's/\\\${/${/g' skills/security-hardening/install.js
```

### 步骤 2：修复嵌套模板字符串
需要找到所有在 `return \`` 和结束 `` ` `` 之间的内层模板字符串，将其反引号转义为 `\``。

涉及的函数和修复位置：

| 函数 | 行号范围 | 内层模板字符串位置 |
|------|---------|-------------------|
| `generatePersistentGuardJs` | 415-498 | 第 418 行 `CORE_SECURITY_RULES = \``，第 443 行结束 |
| `generateAuditorJs` | 502-583 | 第 532 行 `\`audit-\${dateStr}.log\`` |
| `generateHooksJs` | 587-677 | 第 649 行 `\`Dangerous command...\``，第 663 行 `\`Sensitive file...\`` |
| `generateMainJs` | 681-760 | 第 700 行 `\`Security rules...\`` |

**具体修复命令**：
```bash
# 修复 CORE_SECURITY_RULES 定义
sed -i 's/CORE_SECURITY_RULES = `/CORE_SECURITY_RULES = \`/' skills/security-hardening/install.js

# 修复其结束标记（需要确认具体行号）
# 手动编辑第 443 行：将 `; 改为 \`;

# 修复 audit 日志文件名
sed -i 's/`audit-\${dateStr}.log`/\`audit-\${dateStr}.log\`/' skills/security-hardening/install.js

# 修复错误消息
sed -i 's/`Dangerous command blocked: \${blocked}`/\`Dangerous command blocked: \${blocked}\`/' skills/security-hardening/install.js
sed -i 's/`Sensitive file requires admin: \${sensitive}`/\`Sensitive file requires admin: \${sensitive}\`/' skills/security-hardening/install.js

# 修复 console.log
sed -i 's/`Security rules: \${injection.injected/\`Security rules: \${injection.injected/' skills/security-hardening/install.js
```

### 步骤 3：验证语法
```bash
node --check skills/security-hardening/install.js
```

无输出表示语法正确。

---

### 步骤 4：正确运行安装
注意参数格式使用**空格分隔**，而非等号：

```bash
# ✅ 正确
node skills/security-hardening/install.js \
  --admin ou_4379c83438a527426548168a8ac72d07 \
  --workspace /root/.nanobot/workspace \
  --models kimi-coding/k2p5

# ❌ 错误（等号格式不被支持）
node install.js --admin=ou_xxx --workspace=...
```

---

## 验证安装

```bash
node skills/security-hardening/verify.js
```

预期输出：
```
✅ Security directory exists
✅ File: security/guard.js
✅ File: security/command-guard.js
...
✅ All checks passed!
🛡️  Security hardening is active
```

---

## 总结

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 反引号转义 | 文件编码/传输问题 | `sed -i 's/\\`/`/g'` |
| 嵌套模板字符串 | 代码生成逻辑设计问题 | 内层反引号转义为 `\`` |
| 参数解析失败 | 使用等号而非空格 | `--admin id` 而非 `--admin=id` |

---

*记录时间：2026-02-25*  
*记录者：奇卓*  
*适用版本：security-hardening v1.0.0*
