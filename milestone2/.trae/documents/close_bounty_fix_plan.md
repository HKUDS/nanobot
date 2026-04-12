# 结束任务失败问题排查计划

## 问题分析

**现象**：调用 `POST /bounties/{id}/close` 接口时返回 422 Unprocessable Entity 错误。

**可能原因**：
1. **API 接口参数定义错误**：后端期望 `issuer_id` 作为路径参数或查询参数，而前端通过请求体发送
2. **请求格式不匹配**：FastAPI 无法解析请求体格式
3. **缺少 Pydantic 模型**：未使用正确的请求模型来接收参数

## 代码分析

### 后端代码（bff_service.py）
```python
@app.post("/bounties/{bounty_id}/close")
async def api_close_bounty(bounty_id: str, issuer_id: str):
    """关闭悬赏任务，只有发布者可以操作"""
    try:
        await bounty_hub.close_bounty(bounty_id, issuer_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close bounty: {str(e)}")
```

### 前端代码（BountyMarket.vue）
```javascript
await request.post(`/bounties/${bounty.id}/close`, {
  issuer_id: props.conversationId
})
```

## 问题原因

**根本原因**：`api_close_bounty` 函数的 `issuer_id` 参数被定义为路径参数或查询参数，但前端通过请求体发送。FastAPI 无法解析这种请求格式，因此返回 422 错误。

## 修复方案

### 方案 1：使用 Pydantic 模型接收请求体（推荐）
1. 创建 `CloseBountyRequest` 模型
2. 修改 `api_close_bounty` 函数使用该模型
3. 保持前端调用方式不变

### 方案 2：修改前端调用方式
1. 将 `issuer_id` 作为查询参数发送
2. 保持后端代码不变

## 修复步骤

### 步骤 1：创建 Pydantic 模型
在 `bff_service.py` 中添加：
```python
class CloseBountyRequest(BaseModel):
    issuer_id: str
```

### 步骤 2：修改 API 接口
将 `api_close_bounty` 函数修改为：
```python
@app.post("/bounties/{bounty_id}/close")
async def api_close_bounty(bounty_id: str, req: CloseBountyRequest):
    """关闭悬赏任务，只有发布者可以操作"""
    try:
        await bounty_hub.close_bounty(bounty_id, req.issuer_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close bounty: {str(e)}")
```

### 步骤 3：测试验证
1. 重新构建 BFF 镜像
2. 启动服务
3. 测试结束任务功能

## 预期结果

- **调用成功**：`POST /bounties/{id}/close` 接口返回 200 OK
- **功能正常**：任务状态从 `open` 变为 `completed`
- **前端反馈**：显示"任务已结束"的成功提示

## 风险评估

- **风险**：修改 API 接口可能影响其他调用方
- **缓解**：只修改参数接收方式，保持功能逻辑不变

- **风险**：前端代码需要适配
- **缓解**：保持前端调用方式不变，只修改后端

## 执行计划

1. **修改后端代码**：添加 Pydantic 模型并修改 API 接口
2. **重新构建镜像**：应用修改
3. **测试验证**：确保结束任务功能正常
4. **文档更新**：记录修复过程和结果