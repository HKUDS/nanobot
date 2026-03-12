# OAuth 用户授权

默认的 tenant_access_token 以应用身份调用 API。
部分场景（个人日历、搜索联系人）需要 user_access_token 代表用户操作。

## 授权流程

### 1. 构造 redirect_uri 并重定向用户到授权页面

```typescript
// 域名和路径根从运行时获取
const redirectUri = `https://${req.hostname}${process.env.CLIENT_BASE_PATH}/feishu/oauth/callback`;
const authorizeUrl = `https://open.feishu.cn/open-apis/authen/v1/authorize?app_id=${FEISHU_APP_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&state=${state}`;
// 返回 302 重定向或将 URL 返回给前端
```

### 2. 回调中用 code 换取 token

```typescript
const userId = req.userContext.userId; // 当前登录用户
await client.userAccessToken.initWithCode({ [userId]: code });
```

### 3. 获取 token（自动 refresh）

```typescript
const token = await client.userAccessToken.get(userId);
```

### 4. 携带 user_access_token 调用 API

```typescript
await client.calendar.calendarEvent.create(
  { data: { summary: '我的日程', ... } },
  lark.withUserAccessToken(token),
);
```

## Token 持久化与用户关联

SDK 默认将 token 存在内存，重启后丢失。生产环境需持久化到数据库。

### 建表

```sql
CREATE TABLE feishu_user_token (
  user_id           VARCHAR(64) PRIMARY KEY,  -- req.userContext.userId
  open_id           VARCHAR(64) NOT NULL,     -- 飞书用户标识
  access_token      TEXT NOT NULL,
  refresh_token     TEXT NOT NULL,
  token_expire_at   TIMESTAMPTZ NOT NULL,
  refresh_expire_at TIMESTAMPTZ NOT NULL,
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### FeishuOAuthService 示例

回调保存和 token 刷新的完整 NestJS Service 实现：

- `access_token` 有效期 2 小时，`refresh_token` 有效期 30 天
- 每次 refresh 后，服务端会同时返回**新的 `refresh_token`**（token rotation），必须用新值覆盖旧值，否则下次刷新会失败

```typescript
import { Injectable, Inject } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { eq } from 'drizzle-orm';
import { feishuUserToken } from '@server/database/schema';

@Injectable()
export class FeishuOAuthService {
  private readonly EXPIRY_BUFFER_MS = 3 * 60 * 1000; // 预留 3 分钟 buffer

  constructor(
    private readonly feishuService: FeishuService,
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  /** 回调中用 code 换取 token 并持久化（Step 2 之后调用） */
  async handleCallback(userId: string, code: string) {
    const client = this.feishuService.getClient();
    const tokenRes = await client.authen.oidcAccessToken.create({
      data: { grant_type: 'authorization_code', code },
    });
    if (tokenRes.code !== 0 || !tokenRes.data) {
      throw new Error(`Feishu OAuth token error [${tokenRes.code}]: ${tokenRes.msg}`);
    }
    const { access_token, refresh_token, open_id, expires_in, refresh_expires_in } = tokenRes.data;
    const now = Date.now();
    await this.db.insert(feishuUserToken).values({
      userId,
      openId: open_id,
      accessToken: access_token,
      refreshToken: refresh_token,
      tokenExpireAt: new Date(now + expires_in * 1000),
      refreshExpireAt: new Date(now + refresh_expires_in * 1000),
    }).onConflictDoUpdate({
      target: feishuUserToken.userId,
      set: {
        openId: open_id,
        accessToken: access_token,
        refreshToken: refresh_token,
        tokenExpireAt: new Date(now + expires_in * 1000),
        refreshExpireAt: new Date(now + refresh_expires_in * 1000),
      },
    });
  }

  /** 获取有效的 user_access_token，自动刷新 */
  async getValidToken(userId: string): Promise<string> {
    const [stored] = await this.db
      .select()
      .from(feishuUserToken)
      .where(eq(feishuUserToken.userId, userId));
    if (!stored) throw new Error('用户未授权飞书，请先完成 OAuth 授权');

    const now = Date.now();

    // 1. access_token 未过期 → 直接返回
    if (stored.tokenExpireAt.getTime() - now > this.EXPIRY_BUFFER_MS) {
      return stored.accessToken;
    }

    // 2. access_token 过期，但 refresh_token 未过期 → 刷新
    if (stored.refreshExpireAt.getTime() - now > this.EXPIRY_BUFFER_MS) {
      const client = this.feishuService.getClient();
      const res = await client.authen.oidcRefreshAccessToken.create({
        data: { grant_type: 'refresh_token', refresh_token: stored.refreshToken },
      });
      if (res.code !== 0 || !res.data) {
        throw new Error(`Feishu OAuth refresh error [${res.code}]: ${res.msg}`);
      }
      const { access_token, refresh_token, expires_in, refresh_expires_in } = res.data;

      // 必须同时更新 access_token 和 refresh_token（token rotation）
      await this.db.update(feishuUserToken)
        .set({
          accessToken: access_token,
          refreshToken: refresh_token,
          tokenExpireAt: new Date(now + expires_in * 1000),
          refreshExpireAt: new Date(now + refresh_expires_in * 1000),
        })
        .where(eq(feishuUserToken.userId, userId));
      return access_token;
    }

    // 3. refresh_token 也过期 → 需要用户重新授权（回到第 1 步）
    throw new Error('飞书授权已过期，请重新授权');
  }
}
```

#### 在业务代码中使用

```typescript
// 在 Controller 或其他 Service 中注入 FeishuOAuthService
const token = await this.feishuOAuthService.getValidToken(req.userContext.userId);
await this.feishuService.getClient().calendar.calendarEvent.create(
  { data: { summary: '我的日程', ... } },
  lark.withUserAccessToken(token),
);
```
