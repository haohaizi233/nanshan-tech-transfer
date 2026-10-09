"""
L3: 文件访问短时效一次性 token（HMAC-SHA256 签名）

替代 access_token 走 URL query 的问题（token 进 Caddy/uvicorn 日志、浏览器历史、Referer）。

协议：
- POST /files/:id/token → 返回 {fileToken, expiresIn}（需要 Bearer 认证）
- GET /files/:id?file_token=<token> → 校验 HMAC 签名 + 过期时间 + file_id 匹配

token 格式：<user_id>:<file_id>:<expires_ts>:<hmac_hex>
HMAC 密钥复用 JWT_SECRET（同源信任，无需额外配置）。
"""
import hashlib
import hmac
import time

from config import settings


def generate_file_token(user_id: int, file_id: int, ttl_seconds: int = 300) -> str:
    """生成 5 分钟有效的文件访问 token。"""
    expires = int(time.time()) + ttl_seconds
    payload = f"{user_id}:{file_id}:{expires}"
    sig = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_file_token(token: str, file_id: int) -> int | None:
    """校验文件 token，返回 user_id 或 None（无效/过期/不匹配）。"""
    if not token or not token.strip():
        return None
    parts = token.strip().split(":")
    if len(parts) != 4:
        return None
    user_id_str, file_id_str, expires_str, sig = parts
    try:
        user_id = int(user_id_str)
        token_file_id = int(file_id_str)
        expires = int(expires_str)
    except (ValueError, TypeError):
        return None
    # 过期检查
    if time.time() > expires:
        return None
    # file_id 匹配检查
    if token_file_id != file_id:
        return None
    # HMAC 签名验证
    payload = f"{user_id}:{file_id}:{expires}"
    expected = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return user_id
