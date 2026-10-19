-- ============================================================
-- 028: 放宽 audit_log.resource_type 列宽（VARCHAR(32) → VARCHAR(64)）
--   背景：membership.apply 写入 resource_type='organization_membership_application'
--         （35 字符）超过原 VARCHAR(32)，触发 22001 字符串截断错误，
--         审计与业务同事务 → 整个申请提交回滚并返回 500。
--   对齐：action 列本身即为 VARCHAR(64)，resource_type 与之保持一致。
--   幂等：可重复执行。
-- ============================================================

BEGIN;

ALTER TABLE public.audit_log
    ALTER COLUMN resource_type TYPE VARCHAR(64);

COMMENT ON COLUMN public.audit_log.resource_type IS '资源类型（如 achievement / membership_application），上限 64 与 action 对齐';

COMMIT;
