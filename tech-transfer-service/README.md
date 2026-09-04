# tech-transfer-service

南山科转通统一后端（FastAPI + PostgreSQL）。统一 API 前缀 `/api/tech-transfer/v1`，默认端口 8787。

## 环境配置（T006 统一配置）

所有环境相关配置统一由 `config.py`（pydantic-settings）管理，业务代码通过 `from config import settings` 读取，**不得硬编码**数据库地址、密钥、外部 URL 等环境参数。

三套运行环境通过 `APP_ENV` 切换：`local` / `development`（等价，开发）、`staging`、`production`，同一份代码无需改动。

### 首次配置

```bash
cd tech-transfer-service
copy .env.example .env    # Windows；Linux/macOS 用 cp
# 编辑 .env，按环境填写数据库、JWT 密钥等
```

读取优先级（高 → 低）：进程环境变量 > `.env.{APP_ENV}`（可选的环境覆盖文件）> `.env` > 代码默认值（仅本地开发）。

### 启动

```bash
python app.py                  # 开发（热重载，docs 开启）
# 或使用仓库根启动器
python 南山小程序/start_dev.py --backend-only
```

staging / production 部署时通过环境变量或 `.env` 提供：`APP_ENV`、真实 `DB_*`、≥16 位随机 `JWT_SECRET`、`HOST_MODE`/`AUTH_PROVIDER`（禁止 local/mock）、真实域名 `API_BASE`、`CORS_ORIGINS` 白名单。上述弱配置会被启动断言 `assert_environment()` 直接拦截（exit 1），不会带弱密钥进入生产。

### 说明

- `.env`、`.env.*` 已被 `.gitignore` 忽略，只有 `.env.example` 模板入库；
- 存量资本库 MySQL（`CAPITAL_DB_*`）仅 `tools/` 一次性 ETL 脚本使用，业务运行时零 MySQL 依赖。
