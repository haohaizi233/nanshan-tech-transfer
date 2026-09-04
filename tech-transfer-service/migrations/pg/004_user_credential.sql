-- 004：账号密码凭证表（真实数据库登录）
-- 独立于宿主身份域（external_identity）：bootstrap/宿主票据流不受影响
-- 密码哈希格式：pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>（stdlib 实现）

CREATE TABLE IF NOT EXISTS public.user_credential (
    user_id BIGINT NOT NULL PRIMARY KEY REFERENCES public.app_user(id),
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_user_credential_username UNIQUE (username)
);

COMMENT ON TABLE public.user_credential IS '账号密码登录凭证（后台管理）';
COMMENT ON COLUMN public.user_credential.user_id IS '关联 app_user.id';
COMMENT ON COLUMN public.user_credential.username IS '登录用户名（全局唯一）';
COMMENT ON COLUMN public.user_credential.password_hash IS 'PBKDF2-SHA256 哈希';
COMMENT ON COLUMN public.user_credential.status IS 'active/disabled';

DROP TRIGGER IF EXISTS trg_user_credential_updated_at ON public.user_credential;
CREATE TRIGGER trg_user_credential_updated_at BEFORE UPDATE ON public.user_credential
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX IF NOT EXISTS idx_user_credential_user_id ON public.user_credential(user_id);
