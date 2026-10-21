-- ========================================================
-- 030_ai_evaluation_multidim —— AI 成果评价增强（多维评价 / 评分体系 / 报告生成）
--
-- 增强内容（在 013_ai_evaluation 基础上 additive only）：
--   1. 多维度评价：dimensions JSONB —— 六维（创新性/技术成熟度/市场前景/
--      团队实力/合作可行性/风险评估），每维 {key,label,score,weight,comment}
--   2. 评分体系：total_score 沿用百分制（加权总分），rating 五档等级，
--      starScore（五分制）为读取时派生，不落库
--   3. 评价报告：report_sections JSONB —— AI 生成的结构化报告
--      [{heading, content}]，前端分节渲染
--
-- 兼容约定：
--   - 013 的四列（score_tech/score_application/score_maturity/score_feasibility）
--     仍 NOT NULL，由多维评分 1:1 派生写入（见 modules/ai/evaluation.py
--     LEGACY_SCORE_MAP）：技术特点←创新性、应用范围←市场前景、
--     成熟度←技术成熟度、合作可行性←合作可行性
--   - 旧数据（无 dimensions）读取时只展示旧四维，不回填假的新维度评分
-- ========================================================

ALTER TABLE public.ai_evaluation
    ADD COLUMN IF NOT EXISTS dimensions      JSONB        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS report_sections JSONB        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS rating          VARCHAR(16)  DEFAULT NULL;

COMMENT ON COLUMN public.ai_evaluation.dimensions IS
    '多维评价明细 JSONB：[{key,label,score,weight,comment}]；NULL=增强前旧数据';
COMMENT ON COLUMN public.ai_evaluation.report_sections IS
    'AI 生成评价报告 JSONB：[{heading,content}]；NULL=增强前旧数据或无报告';
COMMENT ON COLUMN public.ai_evaluation.rating IS
    '综合等级：excellent/good/fair/weak（由 total_score 分档，见 evaluation.py）';

-- 历史查询：按用户时间线拉取评价记录（GET /ai/evaluations）
CREATE INDEX IF NOT EXISTS idx_ai_eval_created ON public.ai_evaluation (created_at DESC, id DESC);
