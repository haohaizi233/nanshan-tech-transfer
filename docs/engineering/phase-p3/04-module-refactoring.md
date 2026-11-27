# Phase P3-D：前端渐进解耦与后端职责收敛

## 1. P3-6：前端大型页面渐进解耦与双端构建
- 抽离 [mine-security-helpers.mjs](file:///d:/Users/Administrator/Desktop/南山小程序/南山小程序/南山/subpackages/tech-transfer/utils/mine-security-helpers.mjs) 与 [ai-match-helpers.mjs](file:///d:/Users/Administrator/Desktop/南山小程序/南山小程序/南山/subpackages/tech-transfer/utils/ai-match-helpers.mjs)，将 OTP 前导零规范化、手机/邮箱格式校验、冷却倒计时计算、防并发请求上下文校验与历史卡片映射从页面脚本抽离为独立可测模块。
- 保留现有 UI 风格、安全流程与 `contact-card`、`formatted-text`、`ai-generated-mark` 等公共组件不变。
- 验证结果：
  - `南山小程序/南山` Node 测试（含新增 [p3-frontend-helpers.test.mjs](file:///d:/Users/Administrator/Desktop/南山小程序/南山小程序/南山/tests/p3-frontend-helpers.test.mjs)）：**456 passed, 0 failed**。
  - `npm run build:h5`：**DONE Build complete.**
  - `npm run build:mp-weixin`：**DONE Build complete.**
  - `nanshan-frontend` Node 测试：**54 passed, 0 failed**；`npm run build`：**built in 491ms**。

## 2. P3-7：后端大型业务模块职责收敛与架构棘轮
- 将 [tech-transfer-service/modules/admin/service.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/admin/service.py)（原 3,415 行）中的审计日志查询与机构目录管理拆分为独立子模块：
  - [modules/admin/audit.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/admin/audit.py)
  - [modules/admin/institutions.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/admin/institutions.py)
  - `modules/admin/service.py` 降为 2,888 行并保持 100% 向后兼容门面重导出，不破坏路由与原子事务。
- 新增 AST 导入治理棘轮 [test_architecture_imports.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/tests/test_architecture_imports.py)：
  - 冻结历史已知 2-节点循环（`achievement` ↔ `admin`）与 10 处历史跨模块私有函数导入；
  - 阻断任何新增反向层依赖、循环依赖与跨模块 `_` 私有导入。
- `test_architecture_imports.py`、`ruff format --check`、`ruff check` 全部通过。
