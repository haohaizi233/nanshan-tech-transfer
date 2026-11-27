# Phase P3-9：标准化部署、分层健康检查与备份恢复演练

## 1. 部署脚本路径配置化与进程隔离
- [watchdog.sh](file:///d:/Users/Administrator/Desktop/南山小程序/watchdog.sh)：
  - 消除硬编码 `/Users/mac/...` 路径，改为 `NANSHAN_PROJECT_ROOT`、`NANSHAN_PYTHON`、`NANSHAN_LOG_DIR`、`NANSHAN_PID_DIR`、`FRPC_BIN`、`FRPC_CONF` 环境变量与 `.env` 注入；
  - 移除无关项目 `stock-api`（8007）及硬编码外部 IP；
  - 进程检查与启动改用 PID 文件（`kill -0 "$(cat "$pid_file")"`），禁止仅凭端口号 `lsof -i :$port` 误杀同机其他项目进程。
- [install_watchdog.sh](file:///d:/Users/Administrator/Desktop/南山小程序/install_watchdog.sh) 与 [com.nanshan.watchdog.plist](file:///d:/Users/Administrator/Desktop/南山小程序/com.nanshan.watchdog.plist)：使用 `__NANSHAN_PROJECT_ROOT__` / `__NANSHAN_LOG_DIR__` 占位符并在安装时 `sed` 渲染。

## 2. 分层健康检查（[app.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/app.py)）
- `GET /health/live`（`/api/health/live`）：Liveness 探针，仅检测进程存活。
- `GET /health/ready`（`/api/health/ready`）：Readiness 探针，检测 PostgreSQL `SELECT 1`、Schema Gate (`040` / `042`) 及 Redis（若 `REDIS_ENABLED=true`），任一不满足返回 HTTP 503。
- `GET /health/deps`（`/api/health/deps`）：依赖与后台协调状态详情（非 `local` 环境需 `X-Internal-Health-Key`），返回 DB/Schema/Redis 状态、AI Agent 可达性、媒体目录可写性、安全协调调度状态（`pendingRiskSyncCount`、`lastSuccessAt`）与脱敏版本信息。
- `GET /health/version`（`/api/health/version`）：返回 `applicationVersion`、`gitCommit`、`schemaVersion`、`buildTime`，不暴露 DSN/密钥/内部路径。

## 3. PostgreSQL 18.6 备份与恢复演练实测
- 演练方式：创建临时源库 `tech_transfer_drill_src` 并导入 `041_capital_module_icons.sql`（4 条二进制图标行）→ `pg_dump -Fc` → 创建临时恢复库 `tech_transfer_restore_drill` → `pg_restore --no-owner` → 校验行数并清理临时库与备份文件。
- 实测结果：
  - 备份文件大小：`14,344 bytes`
  - `pg_dump` 耗时：`0.109s`
  - `pg_restore` 耗时（实测 RTO）：`0.073s`
  - 数据一致性校验：`src_rows=4` == `dst_rows=4`（100% 一致）
- 生产备份与恢复策略：每日全量 `pg_dump -Fc` 加密离线/异地保存（保留 14–30 天），回滚遵循数据库向前兼容原则，禁止将代码回退等同于结构回退。

## 4. CI 到 CD 发布门禁说明
- 生产环境部署与 Staging 实机变更需取得明确授权，本轮标记为 **NOT RUN（未执行生产部署）**。
