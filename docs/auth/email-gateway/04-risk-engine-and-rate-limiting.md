# 统一 Redis Lua 风控引擎与 Fail-Closed 限流设计 (04-risk-engine-and-rate-limiting)

## 1. 共享风控底座 (`modules/security/risk_engine.py`)

`SmsRiskEngine` 与 `EmailRiskEngine` 共用抽象底座 `BaseRiskEngine` 与三段 Redis Lua 原子脚本（`REQUEST_LUA`、`RESERVE_LUA`、`TRANSITION_LUA`），统一实现：

1. **高并发防覆盖**：滑动窗口 ZSET 成员采用唯一 UUID（`ARGV[2]`），彻底消除多请求落入同一毫秒时间戳时的 ZSET 覆盖漏计数；时间源优先采用 Redis `TIME` 服务端统一时钟。
2. **Redis Cluster 兼容**：统一采用 Hash Tag 前缀 `{gateway}`（如 `email:{gateway}:`、`sms:{gateway}:`），保证单次 `EVALSHA` 访问的多维度 Key 分配至同一 Slot。
3. **自然日配额午夜守卫**：每日计数器仅在 `redis.call('TTL', r.key) < 0` 时调用 `EXPIRE`，绝不因持续请求刷新 TTL 导致跨午夜错误延后清零。
4. **`NoScriptError` 自动恢复**：首次使用 `SCRIPT LOAD` 缓存 SHA1 并调用 `EVALSHA`；遇到 Redis 重启或脚本缓存清空触发 `NoScriptError` 时，自动重载脚本并无缝重试一次。
5. **全盲索引无 PII 键名**：所有邮箱、手机号、IP、账号及设备号均以独立密钥（`EMAIL_RISK_HMAC_SECRET` / `SMS_RISK_HMAC_SECRET`）经 HMAC-SHA256 摘要后拼接 Key，Redis Key 空间完全不出现明文邮箱或 IP。

---

## 2. 邮箱多维风控规则目录 (`modules/security/email_risk.py`)

`EmailRiskEngine.rule_catalog()` 共配置 **15 条独立规则**（与 `SmsRiskEngine` 互不污染）：

| 规则 ID | 维度 | 默认阈值 / 窗口 | 触发动作 | 对应标准化原因码 |
| :--- | :--- | :--- | :--- | :--- |
| `email.cooldown` / `email.pair.cooldown` | 单邮箱 & (IP+邮箱) 冷却 | 60s（`EMAIL_COOLDOWN_SECONDS`） | `THROTTLE` | `EMAIL_COOLDOWN` |
| `email.10m` | 单目标邮箱 10 分钟上限 | 3 次 / 600s（`EMAIL_LIMIT_10M`） | `THROTTLE` | `EMAIL_RISK_BLOCKED` |
| `email.1h` | 单目标邮箱 1 小时上限 | 5 次 / 3600s（`EMAIL_LIMIT_1H`） | `THROTTLE` | `EMAIL_RISK_BLOCKED` |
| `email.day` | 单目标邮箱自然日上限 | 10 次 / 日（`EMAIL_LIMIT_DAY`） | `THROTTLE` | `EMAIL_DAILY_LIMIT` |
| `email.ip.1m` / `1h` / `day` | 单源 IP 滑动窗口与日配额 | 10 / 30 / 100 | `THROTTLE` | `EMAIL_IP_RATE_LIMIT` |
| `email.account.1h` / `day` | 单账号 1 小时与日配额 | 5 / 10 | `THROTTLE` | `EMAIL_ACCOUNT_RATE_LIMIT` |
| `email.device.1h` / `day` | 单设备 1 小时与日配额 | 5 / 15 | `THROTTLE` | `EMAIL_DEVICE_RATE_LIMIT` |
| `email.ip.distinct_email` | 单 IP 覆盖不同邮箱数 | 5 个 / 3600s | `CHALLENGE` | `EMAIL_RISK_BLOCKED` |
| `email.device.distinct_email` | 单设备覆盖不同邮箱数 | 3 个 / 600s | `CHALLENGE` | `EMAIL_RISK_BLOCKED` |
| `email.global.day` | 全平台邮箱单日总预算 | 5000 封 / 日 | `THROTTLE` | `EMAIL_GLOBAL_BUDGET` |
| `email.domain.anomaly_10m` | 非公共域名 10 分钟突发异常 | 50 次 / 600s | `THROTTLE` | `EMAIL_DOMAIN_ANOMALY` |

### 公共邮箱域免误伤白名单 (`PUBLIC_EMAIL_DOMAINS`)

为防止针对个人用户常用公共邮箱服务商的流量聚合导致无辜用户被封锁，`email.domain.anomaly_10m` 规则显式跳过以下大型公共邮箱域名：
`qq.com`、`foxmail.com`、`163.com`、`126.com`、`yeah.net`、`sina.com`、`sina.cn`、`sohu.com`、`aliyun.com`、`139.com`、`189.cn`、`outlook.com`、`hotmail.com`、`live.com`、`msn.com`、`gmail.com`、`googlemail.com`、`icloud.com`、`me.com`、`yahoo.com`。
仅当自建或冷门企业/一次性邮箱域名在 10 分钟内超出 `EMAIL_DOMAIN_ANOMALY_LIMIT_10M` 时才触发域名突发异常保护。

---

## 3. `SecurityRateLimiter` 与网关 Fail-Closed 语义

旧版本限流器在 Redis 初始化或运行期调用失败时会静默回退进程内存 `_mem_buckets`，导致多 Worker 部署下限流形同虚设。现已重构为：

1. **生产或启用 Redis 时严格 Fail-Closed**：当 `settings.is_production_like` 或 `settings.REDIS_ENABLED` 为真时，`SecurityRateLimiter.check()` 仅执行 Redis Lua 原子脚本；任何连接超时、初始化异常或执行报错均清空缓存句柄（以便恢复后自动重连）并立即返回 HTTP 503 `TT_COMMON_50301`。
2. **仅本地/开发环境 (`local`/`development` 且 `REDIS_ENABLED=false`)** 允许使用线程安全内存滑动窗口，便于纯单机单元测试运行。
3. **`EmailRiskEngine` Fail-Closed**：`BaseRiskEngine._is_dev_bypass_allowed()` 要求 `self.redis is None and not self.config.REDIS_ENABLED and not self.config.is_production_like and self.config.APP_ENV in {"local", "development"}`；其余任何场景遇到 Redis 异常均直接返回 `DecisionAction.DENY`（`email.redis.unavailable`），由上层映射为 HTTP 503。
