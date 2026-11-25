"""密码哈希安全模块。

支持：
1. Argon2id（首选现代强哈希算法，抗 GPU/ASIC 离线破解）
2. PBKDF2-SHA256（标准库备选与存量格式完全兼容）
3. 渐进式哈希升级（存量账号登录验证成功后无缝升级至 Argon2id）
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata

# 尝试载入 argon2-cffi；若未安装则平滑降级至 pbkdf2
_HAS_ARGON2 = False
try:
    import argon2
    from argon2.exceptions import VerifyMismatchError

    _ph = argon2.PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MB
        parallelism=2,
        hash_len=32,
        salt_len=16,
        type=argon2.Type.ID,
    )
    _HAS_ARGON2 = True
except ImportError:
    _ph = None

PBKDF2_ITERATIONS = 200_000
ALGORITHM_PBKDF2 = "pbkdf2_sha256"
MAX_PASSWORD_BYTES = 128


def _normalize_password(password: str) -> str:
    """Unicode NFKC 规范化并限制合理长度。"""
    if not isinstance(password, str):
        password = str(password)
    normalized = unicodedata.normalize("NFKC", password)
    if len(normalized.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("密码长度不能超过 128 字节")
    return normalized


def hash_password(password: str) -> str:
    """生成安全哈希。环境支持 argon2id 时优先使用，否则降级至 pbkdf2_sha256。"""
    normalized = _normalize_password(password)
    if _HAS_ARGON2 and _ph is not None:
        try:
            return str(_ph.hash(normalized))
        except Exception:
            pass
    # 降级至 PBKDF2
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{ALGORITHM_PBKDF2}${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码。支持 Argon2id 与 PBKDF2 格式，常量时间比较防侧信道。"""
    if password is None or not isinstance(password, str) or not stored or not isinstance(stored, str):
        return False
    try:
        normalized = _normalize_password(password)
    except ValueError:
        return False

    # 1. 检测 Argon2 格式（形如 $argon2id$v=19$m=...）
    if stored.startswith("$argon2"):
        if not _HAS_ARGON2 or _ph is None:
            return False
        try:
            return bool(_ph.verify(stored, normalized))
        except (VerifyMismatchError, Exception):
            return False

    # 2. 检测存量 PBKDF2 格式（形如 pbkdf2_sha256$<iter>$<salt>$<hash>）
    try:
        parts = stored.split("$")
        if len(parts) == 4 and parts[0] == ALGORITHM_PBKDF2:
            _, iterations_str, salt_hex, hash_hex = parts
            iterations = int(iterations_str)
            salt = bytes.fromhex(salt_hex)
            dk = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError, AttributeError):
        return False

    return False


def needs_rehash(stored: str) -> bool:
    """判断该密码哈希是否需要平滑升级至当前推荐算法 (Argon2id)。"""
    if not stored:
        return False
    if _HAS_ARGON2 and _ph is not None:
        if not stored.startswith("$argon2"):
            return True
        try:
            return bool(_ph.check_needs_rehash(stored))
        except Exception:
            return True
    return False
