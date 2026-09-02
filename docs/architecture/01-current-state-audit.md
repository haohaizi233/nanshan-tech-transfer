# 01 · 现状源码审计（Current State Audit）

> 文档状态：基线版（基于 2026-09-02 真实源码盘点）
> 盘点方式：目录扫描 + 逐文件源码阅读 + `rg` 全局检索（`uni.setStorageSync` / `uni.getStorageSync` / `uni.request` / `mock-data` / `USE_CAPITAL_DEMO` / `API_BASE` / `ownerUserId` / `TODO` / `演示` / `模拟` / `待接入`）
> 结论性质：本文所有结论均可在仓库源码中找到对应文件与行号；不含推测性"完成百分比"。

---

## 1. 仓库实际目录结构

```text
南山小程序\                                  # 仓库根
├─ 南山科转通_架构与接口设计.md              # 架构评审稿 V2（单文档，1486 行）
├─ project.config.json                       # 根级微信开发者工具配置（指向编译产物目录）
├─ project.private.config.json
└─ 南山小程序\                               # 实际工程目录
   ├─ 交接说明.md                            # 2026-08-17 交接文档
   ├─ start_dev.py                           # 一键联调启动器（Flask 后端 + HBuilderX 编译）
   ├─ 南山\                                  # 【uni-app 源码】HBuilderX 打开的目录
   │  ├─ App.vue / main.js / manifest.json / pages.json
   │  ├─ project.config.json                 # appid=wxa65993c6516305c7
   │  ├─ uni.scss / uni.promisify.adaptor.js / index.html
   │  ├─ common\                             # 10 个公共 JS 模块（业务逻辑所在地）
   │  │  ├─ config.js                        # USE_CAPITAL_DEMO / API_BASE
   │  │  ├─ user.js                          # 本地账号/会话/资料/收藏/意向（17.7KB）
   │  │  ├─ mock-data.js                     # 需求/成果演示数据 + 用户发布数据存取
   │  │  ├─ capital.js                       # 资本对接模块配置 + API 请求封装
   │  │  ├─ capital-demo-data.js             # 资本演示数据（58KB，从本地库导出）
   │  │  ├─ ai-chat.js                       # AI 匹配对话（本地演示回复）
   │  │  ├─ ai-eval.js                       # AI 评估（演示评分 + 哈希兜底评分）
   │  │  ├─ patent-fee.js                    # 专利年费（6 条演示数据 + 真实费率表）
   │  │  ├─ search.js                        # 客户端关键词过滤 + 搜索历史
   │  │  └─ external-miniprogram.js          # 外部小程序跳转配置（appId 为空）
   │  ├─ pages\                              # 主包 4 页
   │  │  ├─ index\index.vue                  # 首页（需求/成果/检索/资本对接 4 Tab）
   │  │  ├─ ai-match\ai-match.vue            # AI 匹配对话
   │  │  ├─ mine\mine.vue                    # 个人中心（注册/登录/资料/入口）
   │  │  └─ capital-list\capital-list.vue    # 资本对接列表
   │  ├─ packageA\                           # 分包 7 页
   │  │  ├─ search\search.vue                # 搜索
   │  │  ├─ dock-detail\dock-detail.vue      # 对接详情（意向状态机）
   │  │  ├─ post-demand\post-demand.vue      # 发布需求表单
   │  │  ├─ post-result\post-result.vue      # 发布成果表单
   │  │  ├─ fee-detail\fee-detail.vue        # 专利年费详情
   │  │  ├─ my-list\my-list.vue              # 我的需求/成果/收藏/意向
   │  │  └─ ai-eval-detail\ai-eval-detail.vue# AI 评估结果
   │  ├─ static\                             # 图片资源（banner、tab 图标、logo）
   │  ├─ tools\                              # ⚠ 交接时带入的 tools 副本（见 §11）
   │  └─ unpackage\                          # 编译产物（mp-weixin）
   └─ tools\                                 # 【后端与数据工具】实际使用的目录
      ├─ api-server\                         # Flask API（app.py + cache\logos\31 张图片缓存）
      ├─ platform-crawler\                   # 平台爬虫（schema + 100 条 JSON 数据）
      ├─ szte-crawler\                       # 机构爬虫（schema + 21/16 条 JSON 数据）
      ├─ import_data.py                      # 数据库导入脚本（schema SQL + JSON）
      ├─ export_db_to_excel.py               # 数据库导出 Excel 脚本
      ├─ nanshan_capital_backup.sql          # ⚠ 损坏的 GBK 编码备份（禁止导入）
      ├─ nanshan_capital_backup_utf8.sql     # 干净 UTF-8 备份
      └─ nanshan_capital_交接数据_20260817.xlsx
```

**盘点确认：交接材料中提到的"项目进度表、功能架构图、可行性方案、成果数据表（约 223 条成果）"均不在当前仓库中。** 仓库内可核实的数据仅包含：3 条需求演示数据、3 条成果演示数据（`mock-data.js`）、100 条平台数据、21 条投资机构、16 家融资机构（`tools/`）。"223 条成果"来自需求方陈述与根目录评审稿的前提，本仓库无法核实其数据文件；该数据的清洗与导入是后续阶段 C 的前置条件（见 `07-integration-and-testing.md`）。

---

## 2. 页面盘点（共 11 个页面）

主包 4 页 + 分包 `packageA` 7 页，`pages.json` 中注册一致，无未注册页面。

| # | 页面 | 功能 | 数据来源（import） | 写操作（落点） |
|---|------|------|--------------------|----------------|
| 1 | `pages/index/index` | 首页：需求/成果列表、检索入口（跳外部小程序）、发布入口、资本对接入口 | `mock-data.js`、`user.js`、`capital.js`、`external-miniprogram.js` | 收藏切换 → 本地缓存 |
| 2 | `pages/ai-match/ai-match` | AI 匹配对话 | `ai-chat.js`（纯本地演示） | 无 |
| 3 | `pages/mine/mine` | 个人中心：注册/登录/资料/我的内容入口 | `user.js`、`mock-data.js` | 注册/登录/资料 → 本地缓存 |
| 4 | `pages/capital-list/capital-list` | 资本对接列表（概念验证/中小试/银行/投资） | `capital.js`（唯一真实 API 消费方） | 无 |
| 5 | `packageA/search/search` | 需求/成果搜索 | `mock-data.js`、`search.js`、`user.js` | 搜索历史 → 本地缓存 |
| 6 | `packageA/dock-detail/dock-detail` | 需求/成果详情 + 对接意向全流程 | `mock-data.js`、`user.js` | 收藏、意向提交/接受/拒绝/确认 → 本地缓存 |
| 7 | `packageA/post-demand/post-demand` | 发布需求表单 | `mock-data.js`、`user.js` | 发布需求 → 本地缓存 |
| 8 | `packageA/post-result/post-result` | 发布成果表单 | `mock-data.js`、`user.js` | 发布成果 → 本地缓存 |
| 9 | `packageA/fee-detail/fee-detail` | 专利年费详情 | `patent-fee.js`（纯本地演示） | 无 |
| 10 | `packageA/my-list/my-list` | 我的需求/成果/收藏/意向列表 | `mock-data.js`、`user.js` | 取消收藏 → 本地缓存 |
| 11 | `packageA/ai-eval-detail/ai-eval-detail` | AI 评估结果展示 | `ai-eval.js`（纯本地演示） | 无 |

**TabBar**：首页 / AI匹配 / 我的（3 个 Tab），`pages/capital-list` 不在 TabBar 中，由首页"资本对接"区块进入。

**分包预加载**：`preloadRule` 配置首页预加载 `packageA`（network: all）。

---

## 3. `uni.request` 调用点盘点

全局检索结果：**业务页面没有任何直接 `uni.request` 调用**。唯一的网络请求封装在 `common/capital.js`：

```text
capital.js:152  getRequestApi()      → 优先返回 uni，降级 require('./vendor.js')
capital.js:162  requestJson(path)    → uni.request({ url: API_BASE + path, ... })
```

`requestJson` 被 `fetchPlatformList`（→ `/api/platform-base`）和 `fetchOrgList`（→ `/api/service-orgs` / `/api/invest-orgs`）消费，调用方仅 `capital-list.vue`。

这一现状对目标架构是**有利**的：网络请求已经收敛到单一模块，改造面小。但该封装与目标 HostBridge 契约不一致（无 Authorization 头、无 requestId、无统一错误码解析），需按 `03-frontend-dual-host-design.md` 迁移。

---

## 4. 本地缓存 Key 全清单

| Key | 写入方 | 内容 | 问题 |
|-----|--------|------|------|
| `ns_user_accounts` | `user.js` | `{ phone: { phone, password, profile, createdAt } }` | **明文密码**，多账号并存 |
| `ns_user_session` | `user.js` | 当前登录手机号 | 无凭证、无过期，可被任意改写 |
| `ns_user_profile` | `user.js`（旧版遗留） | 旧版资料，启动时迁移 | 遗留兼容代码 |
| `ns_user_favorites_{phone}` | `user.js` | 收藏数组，按手机号隔离 | 业务事实存本地 |
| `ns_user_intentions` | `user.js` | 全局意向数组（含双方手机号、状态） | **业务事实存本地**，跨账号共享可被篡改 |
| `ns_user_demands` | `mock-data.js` | 用户发布的需求数组 | 业务事实存本地 |
| `ns_user_results` | `mock-data.js` | 用户发布的成果数组 | 业务事实存本地 |
| `ns_search_history_demand` | `search.js` | 需求搜索历史（最多 10 条） | 纯 UI 状态，可保留本地 |
| `ns_search_history_result` | `search.js` | 成果搜索历史（最多 10 条） | 纯 UI 状态，可保留本地 |
| `_health_check` | `user.js` | 存储健康探测临时值 | 临时 |
| `ns_reset_all_test_data_20260722_v3` | `App.vue` | 一次性清库标记 | 演示期数据迁移 hack |
| `ns_cleared_user_demands_20260722` | `mock-data.js` | 一次性清需求标记 | 演示期数据迁移 hack |

---

## 5. Mock 数据入口全清单

| 模块 | 演示内容 | 规模 | 源码位置 | 目标处置 |
|------|----------|------|----------|----------|
| `mock-data.js` | 需求演示数据 | 3 条（d1–d3，含假联系方式） | `demandList` | 阶段 B 后由 `/demands` 接口替代，删除 |
| `mock-data.js` | 成果演示数据 | 3 条（r1–r3，专利号为"演示专利号"） | `resultList` | 阶段 B 后由 `/achievements` 接口替代，删除 |
| `capital-demo-data.js` | 资本演示数据 | 100+21+16 条（从本地库导出） | 独立文件 | `USE_CAPITAL_DEMO=true` 时启用；API 稳定后删除 |
| `ai-chat.js` | AI 对话回复 | 本地字符串拼接 + 600ms 延迟 | `buildDemoReply` | 接入 AI 匹配任务 API 后删除 |
| `ai-eval.js` | AI 评估评分 | r1–r3 写死分数；其余按 id 哈希生成"稳定假分" | `DEMO_EVAL_MAP` + `buildFallbackEval` | 接入评估任务 API 后删除 |
| `patent-fee.js` | 专利数据 | 6 条演示专利（p1–p6）；**费率表为真实数据** | `patentDemoList` + `FEE_TABLE` | 专利数据接 API；费率表可后移服务端 |
| `external-miniprogram.js` | 外部检索小程序 | appId 为空，点击提示"暂未开通" | `EXTERNAL_SEARCH_MINIPROGRAM` | 与"源码合并"目标冲突，需上级确认（见 08 清单 #16） |

**当前模式开关**：`common/config.js` 中 `USE_CAPITAL_DEMO = false`（联调模式），`API_BASE = http://127.0.0.1:8787`。

---

## 6. 当前后端路由（Flask `tools/api-server/app.py`）

| 方法 | 路径 | 功能 | 数据源 | 鉴权 |
|------|------|------|--------|------|
| GET | `/api/health` | 健康检查（返回三表计数） | MySQL | 无 |
| GET | `/api/platform-base` | 概念验证/中小试平台列表（type=poc\|pilot\|all、keyword、page、pageSize） | `platform_base` 表 | 无（公开数据，可接受） |
| GET | `/api/service-orgs` | 银行融资机构列表 | `ip_service_org` 表 | 无 |
| GET | `/api/invest-orgs` | 投资机构列表 | `featured_invest_org` 表 | 无 |
| GET | `/api/file/<file_id>` | 代理深圳科交中心图片（szte.com），本地缓存到 `cache/logos/` | 外部 HTTP + 文件缓存 | 无 |

响应包格式为 `{ code, msg, data }`——**注意字段名是 `msg` 而不是目标契约的 `message`**，迁移时须统一（见 `06-api-design.md` §2）。无 CORS 白名单限制（`CORS(app)` 全开放）。数据库异常直接返回 `str(e)`，**泄漏 SQL 错误细节**。

## 7. 当前数据库（`nanshan_capital`，共 3 张表）

| 表 | 行数 | 字段概要 | 来源 |
|----|------|----------|------|
| `platform_base` | 100 | serial_no、platform_name、platform_type、support_unit、platform_fun、contact_person、contact_mobile、source_* | `platform-crawler` 爬取（first-net.cn） |
| `featured_invest_org` | 21 | org_name、intro、detail_info、label、logo_file_id、sort_order、source_* | `szte-crawler` 爬取（szte.com） |
| `ip_service_org` | 16 | account、org_name、intro、detail_info、label、user_type、logo_file_id、sort_order、source_* | `szte-crawler` 爬取（szte.com） |

三张表均为爬虫导出的**只读展示数据**，无用户表、无成果表、无需求表、无收藏/对接表、无 AI/专利表。`db_config.json`（两份）当前指向本机 MySQL root/123456@3306。

⚠ 已知数据事故：`tools/nanshan_capital_backup.sql` 为 GBK 损坏文件（如"有限公司"变"有限公叿"），**禁止再导入**；干净备份为 `nanshan_capital_backup_utf8.sql`，重导入口径为 `python tools/import_data.py`。

---

## 8. AI / 专利 / 资本模块实现现状

### 8.1 AI 匹配（`ai-chat.js` + `ai-match.vue`）
- 纯前端演示：用户输入 → 600ms 定时器 → `buildDemoReply()` 返回固定话术，页面明示"当前为界面演示，大模型接入后将支持真实智能问答"。
- 无任何模型调用、无任务队列、无结果持久化。

### 8.2 AI 评估（`ai-eval.js` + `ai-eval-detail.vue`）
- 四维评分（技术特点/应用范围/成熟度/合作可行性，0–100）。
- r1–r3 写死评分；其余成果按 `id` 字符哈希生成**确定性假分**（`buildFallbackEval`，`dataSource: 'fallback'`）。
- 无模型版本记录、无输入数据版本、无任务状态。

### 8.3 专利（`patent-fee.js` + `fee-detail.vue`）
- 6 条演示专利；年费费率表为**真实的国家费率标准**（发明/实用新型/外观三档 × 标准/减70%/减85%）。
- `calcLatestPayDate`（申请日+N年前一天）与 `getAnnualFees` 为真实业务规则，应随迁移保留到服务端。
- 无专利检索、无法律状态、无成果—专利关联。

### 8.4 资本对接（`capital.js` + `capital-list.vue` + Flask）
- **当前唯一真实前后端链路**：页面 → `fetchPlatformList/fetchOrgList` → Flask → MySQL。
- 5 个模块入口：概念验证中心、中小试基地、银行融资、投资机构、专利价值评估（`pending: true` 占位，页面显示"参考价值区间（待接入）"）。
- 图片经 Flask 代理（`/api/file/<id>`）回源 szte.com 并落盘缓存，规避小程序直连外域。

---

## 9. 可真实运行链路 vs 仅演示链路

### 9.1 已实现且真实可用

| 链路 | 证据 |
|------|------|
| 资本对接列表（平台/机构）查询、关键词、分页 | `capital-list.vue` → `capital.js` → Flask `/api/platform-base`、`/api/service-orgs`、`/api/invest-orgs` → MySQL |
| 机构 Logo 展示（代理 + 缓存） | Flask `/api/file/<id>` + `cache/logos/` 31 张图 |
| 本地一键联调 | `start_dev.py`：检查 CLI/config/依赖/MySQL → 起 Flask → HBuilderX 编译 → 拉起微信开发者工具（已验证可运行） |
| 数据重建 | `tools/import_data.py`（schema + JSON，校验行数 100/21/16） |

### 9.2 已实现但使用 Mock（页面完整、数据假）

注册/登录/会话、个人资料、需求列表/发布/详情、成果列表/发布/详情、收藏、对接意向全流程（含 pending/accepted/rejected/success 状态机与竞对自动拒绝）、搜索、AI 匹配对话、AI 评估、专利年费。

### 9.3 只有页面没有接口

- 扫码（`index.vue` `onScanCode`：仅调起扫码界面 + Toast，"码规则/接口待客户提供"）。
- 专利价值评估模块入口（capital 页 `pending: true` 占位）。

### 9.4 只有接口没有页面

- Flask `/api/health`（运维用，无需页面）。
- 数据库中 `featured_invest_org.detail_info`（机构详情正文）已有字段和 API 数据，前端仅展示 `intro`，详情页未开发。

### 9.5 只有脚本没有正式服务

- `platform-crawler` / `szte-crawler`：可运行爬虫，但产出为静态 JSON + SQL，无定时更新、无正式数据管道。
- `export_db_to_excel.py` / `import_data.py`：运维脚本，非服务。

### 9.6 完全缺失

统一认证与身份映射、成果/需求的正式后端与数据库、收藏后端、对接意向后端（事件表/审计）、AI 任务后端、专利检索后端、文件上传服务、通知、管理审核后台、OpenAPI 契约、监控与审计日志、生产部署。

---

## 10. 安全问题清单

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| S1 | **明文密码存本地缓存**（`map[p] = { phone, password: pwd, ... }`） | `user.js` registerAccount/loginAccount | 高 |
| S2 | 会话即手机号，无凭证无过期，任意改写即冒充他人 | `user.js` SESSION_KEY | 高 |
| S3 | 数据归属靠前端比对手机号（`contact === phone \|\| owner === phone`） | `user.js` isOwnPublishedContent、`mock-data.js` getMyDemands | 高（越权模型） |
| S4 | 意向数据全局共享于本地缓存，任何设备可篡改双方手机号与状态 | `user.js` ns_user_intentions | 高 |
| S5 | Flask `CORS(app)` 全开放、数据库异常字符串直接返回（泄漏 SQL 细节） | `app.py` | 中 |
| S6 | `db_config.json` 明文 root 密码入库于仓库（当前 root/123456） | `tools/*/db_config.json` | 中 |
| S7 | `manifest.json` `urlCheck: false` + API 走 `http://127.0.0.1`（联调必需，但配置无环境保护，易带上线） | `manifest.json` / `config.js` | 中 |
| S8 | 演示数据含完整假联系方式（手机号/邮箱/微信号），正式环境须确认不外泄真实联系人数据模型边界 | `mock-data.js` | 低（演示期） |
| S9 | 外部图片代理无 referer/频控，可被当作开放代理刷流量 | `app.py` `/api/file/<id>` | 低（本地环境） |

---

## 11. 与目标架构冲突点清单

| # | 冲突 | 现状 | 目标 | 处置 |
|---|------|------|------|------|
| C1 | 用户体系 | 本地缓存多账号 + 明文密码 | 上级认证 → external_identity → app_user | 阶段 B 替换，本地账号库不迁移（见 ADR-002） |
| C2 | 业务数据落点 | 需求/成果/收藏/意向全部本地缓存 | 正式 API + 开发数据库 | 阶段 B 逐页替换（见 03 §6） |
| C3 | AI 能力 | 前端假数据 | 后端异步任务 + 版本记录 | 阶段 C |
| C4 | 响应包字段 | Flask 返回 `msg` | 契约统一 `message` | 迁移资本接口时统一 |
| C5 | API 路径 | `/api/platform-base` 等裸路径 | `/api/tech-transfer/v1/*` | 资本接口迁移映射见 06 §11 |
| C6 | "检索"入口 | 跳转外部小程序（appId 空） | 源码合并后的统一搜索 `/search` | 待上级确认（08 清单 #16），本地先实现站内搜索 |
| C7 | tools 目录双份 | `南山/tools/`（交接副本，config 已脱敏 3307/空密码）与 `南山小程序/tools/`（实际使用）并存 | 单一 tools 目录，随分包迁移时清理 | 前端重构时将 `南山/tools/` 移出 uni-app 工程（避免进编译范围），不删除文件 |
| C8 | 宿主耦合 | 页面直接 import `common/*`，TabBar 写死 3 Tab | HostBridge + 分包不依赖本地 TabBar | 见 03 §4–§5 |
| C9 | `capital.js` 兜底 `require('./vendor.js')` | 编译产物内部模块降级引用 | 统一走 HostBridge.request | 迁移期保留，阶段 B 替换 |
| C10 | 环境保护 | 仅靠注释/人工记忆防演示配置进生产 | 构建期硬校验 | 见 02 §8 |

---

## 12. 现状结论汇总（对照"步骤2"分类）

| 分类 | 内容 |
|------|------|
| **已实现且真实可用** | 资本对接三列表 + 图片代理链路；本地联调工具链（start_dev.py + import_data.py）；3 张资本数据表 |
| **已实现但使用 Mock** | 登录注册会话、资料、需求发布/列表/详情、成果发布/列表/详情、收藏、对接意向状态机、搜索、AI 匹配、AI 评估、专利年费 |
| **只有页面没有接口** | 扫码对接、专利价值评估入口 |
| **只有接口没有页面** | 机构详情正文展示（detail_info 字段闲置） |
| **只有脚本没有正式服务** | 两个爬虫（一次性管道）、导入/导出脚本 |
| **完全缺失** | 统一认证、业务后端全套（用户/成果/需求/收藏/对接/AI/专利/文件/通知/审核）、OpenAPI、审计、监控、生产部署 |

**总体判断**：当前工程是一个**结构清晰的前端演示壳 + 单点真实只读 API**。页面路由、业务流程（尤其对接意向状态机）已具备完整产品形态，但其数据层必须整体从"本地缓存 + Mock"迁移到"正式 API + 开发数据库"，且用户体系必须按 ADR-002 重建。前端请求已收敛于 `capital.js` 单点、页面无散落 `uni.request`，这是本次架构迁移最有利的现状条件。
