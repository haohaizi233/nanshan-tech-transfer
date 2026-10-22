-- ========================================================
-- 032_ai_task_progress_stage —— AI 评估任务实时阶段回传
--
-- 背景：AI 评估执行过程较长（LLM 调用为主），前端轮询只能看到
-- queued/running 两个粗粒度状态。执行器/worker 在关键阶段把
-- 当前阶段文案写入 progress_stage，GET /ai/evaluation-tasks/{id}
-- 原样返回给前端展示，替代纯前端模拟的阶段轮播。
--
-- 阶段文案由 modules/ai/progress.py 统一维护（STAGE_* 常量）：
--   正在读取成果数据 → AI正在分析技术内容 → 正在生成评价报告
--   → 正在计算综合评分 → 正在保存评估结果
--
-- 约定：
--   - 仅 running 任务允许更新（SQL 带 status='running' 条件，
--     迟到的进度写回不会污染终态任务）
--   - VARCHAR(64) 足够容纳最长阶段文案
--   - 允许 NULL：queued 任务尚未进入任何执行阶段
-- ========================================================

ALTER TABLE public.ai_task ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(64) DEFAULT NULL;

COMMENT ON COLUMN public.ai_task.progress_stage IS '实时执行阶段文案（仅 running 更新；NULL=尚未开始执行）';
