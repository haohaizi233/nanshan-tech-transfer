"""
business error codes and exception

Architecture source: 06-api-design.md §error-codes, openapi.yaml
Frozen: error codes are add-only, never modify existing codes.
"""

class BizError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details

    def __str__(self):
        return f"[{self.code}] {self.message}"


# ── Common ──────────────────────────────────────────────────
TT_COMMON_40001 = ("TT_COMMON_40001", "请求参数无效", 400)
TT_COMMON_40101 = ("TT_COMMON_40101", "未提供认证令牌", 401)
TT_COMMON_40102 = ("TT_COMMON_40102", "认证令牌无效或已过期", 401)
TT_COMMON_40301 = ("TT_COMMON_40301", "无权限访问该资源", 403)
TT_COMMON_40401 = ("TT_COMMON_40401", "接口不存在", 404)
TT_COMMON_40402 = ("TT_COMMON_40402", "资源不存在", 404)
TT_COMMON_40901 = ("TT_COMMON_40901", "幂等键冲突，请勿重复提交", 409)
TT_COMMON_40902 = ("TT_COMMON_40902", "资源版本冲突（乐观锁）", 409)
TT_COMMON_42901 = ("TT_COMMON_42901", "请求过于频繁，请稍后再试", 429)
TT_COMMON_50001 = ("TT_COMMON_50001", "服务内部错误", 500)

# ── Auth ────────────────────────────────────────────────────
TT_AUTH_40103 = ("TT_AUTH_40103", "宿主凭证无效", 401)
TT_AUTH_40104 = ("TT_AUTH_40104", "refresh token 已被吊销", 401)

# ── Achievement ─────────────────────────────────────────────
TT_ACH_40901 = ("TT_ACH_40901", "成果状态不允许此操作", 409)

# ── Demand ──────────────────────────────────────────────────
TT_DMD_40301 = ("TT_DMD_40301", "非需求所有者", 403)
TT_DMD_40401 = ("TT_DMD_40401", "需求不存在", 404)
TT_DMD_40901 = ("TT_DMD_40901", "需求状态不允许此操作", 409)

# ── Cooperation ─────────────────────────────────────────────
TT_COOP_40901 = ("TT_COOP_40901", "对接状态不允许此操作", 409)
TT_COOP_40301 = ("TT_COOP_40301", "无权操作此对接", 403)

# ── AI ──────────────────────────────────────────────────────
TT_AI_50301 = ("TT_AI_50301", "AI 服务不可用", 503)

# ── Patent ──────────────────────────────────────────────────
TT_PATENT_50301 = ("TT_PATENT_50301", "专利查询服务不可用", 503)

# ── File ────────────────────────────────────────────────────
TT_FILE_40001 = ("TT_FILE_40001", "文件格式不支持", 400)
TT_FILE_40401 = ("TT_FILE_40401", "文件不存在", 404)

# ── Convenience constructors ────────────────────────────────

def bad_request(msg="请求参数无效", details=None):
    code, message, status = TT_COMMON_40001
    return BizError(code, msg, status, details)


def unauthorized(msg="认证令牌无效或已过期", details=None):
    code, message, status = TT_COMMON_40101
    return BizError(code, msg, status, details)


def bootstrap_credential_invalid(msg="宿主凭证无效", details=None):
    code, message, status = TT_AUTH_40103
    return BizError(code, msg, status, details)


def conflict(msg="资源版本冲突", details=None):
    code, message, status = TT_COMMON_40902
    return BizError(code, msg, status, details)


def not_found(msg="资源不存在", details=None):
    code, message, status = TT_COMMON_40402
    return BizError(code, msg, status, details)


def demand_not_found(msg="需求不存在", details=None):
    code, message, status = TT_DMD_40401
    return BizError(code, msg, status, details)


def demand_forbidden(msg="非需求所有者", details=None):
    code, message, status = TT_DMD_40301
    return BizError(code, msg, status, details)


def demand_conflict(msg="需求状态不允许此操作", details=None):
    code, message, status = TT_DMD_40901
    return BizError(code, msg, status, details)


def forbidden(msg="无权限访问该资源", details=None):
    code, message, status = TT_COMMON_40301
    return BizError(code, msg, status, details)


def ai_unavailable(msg="AI 服务不可用", details=None):
    code, message, status = TT_AI_50301
    return BizError(code, msg, status, details)
