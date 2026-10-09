-- ============================================================
-- 006: 账号身份柔性化
--   1) user_profile 新增 subject_type（主体类型）/ business_capabilities（合作方向，JSONB）
--      —— 仅用于画像与推荐，不参与任何权限判断（对接权限由后端状态机+归属校验决定）
--      —— 旧 user_type 保留但逐步废弃，不再作为业务语义使用
--   2) cooperation_intent 新增 intent_type（本次对接的合作意向，按目标类型区分枚举）
--      —— 每次对接的角色/方式由用户当次选择决定，与账号属性解耦
-- 幂等：可重复执行
-- ============================================================

-- 1. user_profile 主体类型（相对稳定的属性：企业/高校院所/科研团队/个人/服务机构/投资机构/其他）
ALTER TABLE public.user_profile
    ADD COLUMN IF NOT EXISTS subject_type VARCHAR(32) DEFAULT NULL;
COMMENT ON COLUMN public.user_profile.subject_type IS
    '主体类型：enterprise/university/research_institute/team/service_org/investment_org/individual/other，仅画像用，不作权限门禁';

-- 2. user_profile 合作方向（可多选，推荐信号）
ALTER TABLE public.user_profile
    ADD COLUMN IF NOT EXISTS business_capabilities JSONB DEFAULT NULL;
COMMENT ON COLUMN public.user_profile.business_capabilities IS
    '合作方向多选数组：seek_technology/publish_demand/provide_achievement/joint_rnd/provide_service/investment，仅画像与推荐用';

-- 3. cooperation_intent 合作意向（发起时用户选择；NULL=历史数据或未选择）
ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS intent_type VARCHAR(32) DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.intent_type IS
    '本次对接的合作意向：目标为 demand 时 provide_solution/provide_achievement/joint_rnd/provide_service/investment/other；目标为 achievement 时 purchase/license/joint_rnd/commercialization/pilot_validation/investment/other';
