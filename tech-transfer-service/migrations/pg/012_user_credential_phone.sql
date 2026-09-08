-- 012：user_credential 新增 phone 列（修复字段语义混用）
--
-- 背景：小程序手机号注册此前把手机号写入 username，与后台"登录账号"语义混用，
-- 导致后台注册的机构管理员（username 非手机号）无法在小程序端用手机号登录。
-- 修复后：
--   - 小程序端登录：phone + password（phone 列校验）
--   - 后台管理端登录：username + password（username 列校验，行为不变）
--   - 小程序注册：username 与 phone 均写入手机号（username 保留作兼容）
--   - 后台/机构注册：username 照旧，填写的 11 位手机号同时写入 phone

ALTER TABLE public.user_credential
    ADD COLUMN IF NOT EXISTS phone VARCHAR(32);

COMMENT ON COLUMN public.user_credential.phone IS '登录手机号（小程序端登录标识，11位数字，可空）';

-- 部分唯一索引：phone 非空时全局唯一；NULL 不参与约束（后台未填手机号的账号可多行为 NULL）
CREATE UNIQUE INDEX IF NOT EXISTS uk_user_credential_phone
    ON public.user_credential(phone) WHERE phone IS NOT NULL;

-- 存量回填 1：username 为 11 位纯数字的记录（小程序手机号注册）→ phone = username
UPDATE public.user_credential
SET phone = username
WHERE phone IS NULL AND username ~ '^\d{11}$';

-- 存量回填 2：其余账号从 user_profile.phone 回填（后台/机构注册时手机号仅存 profile）。
-- 跳过两类冲突：该手机号在 user_profile 中归属多个用户；该手机号已被其他凭证占用。
UPDATE public.user_credential uc
SET phone = up.phone
FROM public.user_profile up
WHERE up.user_id = uc.user_id
  AND uc.phone IS NULL
  AND up.phone ~ '^\d{11}$'
  AND NOT EXISTS (
      SELECT 1 FROM public.user_profile up2
      WHERE up2.phone = up.phone AND up2.user_id <> up.user_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM public.user_credential uc2
      WHERE uc2.phone = up.phone AND uc2.user_id <> uc.user_id
  );

-- 回填后 updated_at 触发器已自动刷新；无数据删除，事务可安全重跑（幂等）
