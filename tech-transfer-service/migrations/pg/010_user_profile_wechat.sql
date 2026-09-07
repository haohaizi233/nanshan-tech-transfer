-- ============================================================
-- 010: user_profile 新增 wechat（微信号）
--   —— 个人中心资料字段，手机号密码注册的普通用户可填写
--   —— 与 phone/email 同级，随 /me/profile 乐观锁更新
-- 幂等：可重复执行
-- ============================================================

ALTER TABLE public.user_profile
    ADD COLUMN IF NOT EXISTS wechat VARCHAR(64) DEFAULT NULL;
COMMENT ON COLUMN public.user_profile.wechat IS '微信号（用户联系方式，随资料维护）';
