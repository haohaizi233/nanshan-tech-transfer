# 南山科转通 AI Agent

基于 FastAPI 的科技成果与技术需求查询服务。用户用自然语言提问，服务会调用 LLM 解析查询条件，从 PostgreSQL 检索候选数据，并返回最多 10 条结果。

## 环境要求

- Python 3.10+
- 可访问的 PostgreSQL 数据库
- 可访问的 Qwen Chat Completions API

## 启动

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requestment.txt
```

创建 `.env` 文件并填写以下配置（不要提交真实密钥）：

```dotenv
LLM_API_URL=https://your-llm-api/v1/chat/completions
LLM_API_KEY=your-api-key
LLM_MODEL=your-qwen-model

DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=tech_transfer
DB_USER=your-db-user
DB_PASSWORD=your-db-password
```

启动服务：

```powershell
uvicorn app.main:app --reload
```

服务默认运行在 <http://127.0.0.1:8000>，接口文档地址为 <http://127.0.0.1:8000/docs>。

## 检查服务

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/db
```

`/health/db` 返回 `status: ok` 表示数据库连接正常。

## 查询接口

`POST /api/ai/chat`

```powershell
$body = @{ message = "帮我找机器学习用于生态环境遥感监测的科技成果" } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/ai/chat `
  -ContentType 'application/json' `
  -Body $body
```

请求体：

```json
{
  "message": "帮我找机器学习用于生态环境遥感监测的科技成果"
}
```

返回结果包含查询意图、提示信息和成果或需求卡片；每次最多返回 10 条。

## 成果顾问二期

支持经过主服务校验的会话上下文、卡片指代、预算调整与两项比较；客户端不能自行提交历史事实。
本服务 `/api/ai/chat` 是内部接口。公网客户端应使用 `POST /api/tech-transfer/v1/ai/chat` 并携带登录 Token，地址不含 `/h5`。

新持久执行模式默认关闭。启用需要迁移 029、独立聊天 worker、私网 Agent 和双方一致的 `AI_INTERNAL_SERVICE_KEY`；不能仅部署前端。
新私有端点 `POST /internal/ai/chat/stream` 与 `GET /internal/ai/ready` 必须携带 `X-AI-Service-Key`，不能发布到公网。

完整配置、灰度、回退和测试说明见 [二期交付说明](../docs/agent-evolution-2026-10-20.md)。

离线合成评测（不会请求模型或生产数据库）：

```powershell
python evals/run_advisor_eval.py --output ../outputs/advisor-eval.json
```

真实模型评测必须显式设置 `AI_EVAL_ALLOW_LIVE=1` 并提供 `--live`，可能产生费用；离线通过率不代表真实模型准确率或生产延迟。

## 常见问题

- `ModuleNotFoundError`：确认已激活 `.venv`，并从项目根目录执行 `uvicorn app.main:app --reload`。
- `/health/db` 报错：检查 `.env` 中的 `DB_*` 配置、数据库是否可访问，以及账号是否具备只读查询权限。
- 接口返回 502：检查 `LLM_API_URL`、`LLM_API_KEY`、`LLM_MODEL` 和网络连通性。
