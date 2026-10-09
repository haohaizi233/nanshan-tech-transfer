-- 007_view_count.sql
-- 需求与成果统一使用数据库真实详情访问量（PV）。
-- 注意：历史数值清零由一次性运维操作执行，不能放在可重复执行的迁移中。

ALTER TABLE public.demand
    ADD COLUMN IF NOT EXISTS view_count BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.demand.view_count IS '详情页成功访问次数（PV）';
COMMENT ON COLUMN public.achievement.view_count IS '详情页成功访问次数（PV）';
