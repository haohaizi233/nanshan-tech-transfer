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

## 常见问题

- `ModuleNotFoundError`：确认已激活 `.venv`，并从项目根目录执行 `uvicorn app.main:app --reload`。
- `/health/db` 报错：检查 `.env` 中的 `DB_*` 配置、数据库是否可访问，以及账号是否具备只读查询权限。
- 接口返回 502：检查 `LLM_API_URL`、`LLM_API_KEY`、`LLM_MODEL` 和网络连通性。
