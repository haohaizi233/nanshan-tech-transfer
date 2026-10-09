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
# ── T008 统一异常处理新增（add-only，2026-09-03） ─────────────
TT_COMMON_40501 = ("TT_COMMON_40501", "请求方法不被允许", 405)
TT_COMMON_42201 = ("TT_COMMON_42201", "请求参数校验失败", 422)
TT_COMMON_40903 = ("TT_COMMON_40903", "数据冲突，请勿重复操作", 409)
TT_COMMON_50301 = ("TT_COMMON_50301", "服务暂时不可用，请稍后再试", 503)

# ── Auth ────────────────────────────────────────────────────
TT_AUTH_40103 = ("TT_AUTH_40103", "宿主凭证无效", 401)
TT_AUTH_40104 = ("TT_AUTH_40104", "refresh token 已被吊销", 401)
TT_AUTH_40105 = ("TT_AUTH_40105", "账号或密码错误", 401)
TT_AUTH_40106 = ("TT_AUTH_40106", "账号已被禁用", 401)
TT_AUTH_40901 = ("TT_AUTH_40901", "该手机号已注册，请直接登录", 409)

# ── Achievement ─────────────────────────────────────────────
TT_ACH_40301 = ("TT_ACH_40301", "非成果所有者", 403)
TT_ACH_40401 = ("TT_ACH_40401", "成果不存在", 404)
TT_ACH_40901 = ("TT_ACH_40901", "成果状态不允许此操作", 409)

# ── Demand ──────────────────────────────────────────────────
TT_DMD_40301 = ("TT_DMD_40301", "非需求所有者", 403)
TT_DMD_40401 = ("TT_DMD_40401", "需求不存在", 404)
TT_DMD_40901 = ("TT_DMD_40901", "需求状态不允许此操作", 409)

# ── Cooperation ─────────────────────────────────────────────
TT_COOP_40001 = ("TT_COOP_40001", "不能对自己发布的内容发起对接", 400)
TT_COOP_40301 = ("TT_COOP_40301", "无权操作此对接", 403)
TT_COOP_40401 = ("TT_COOP_40401", "对接意向不存在", 404)
TT_COOP_40901 = ("TT_COOP_40901", "对接状态不允许此操作", 409)
TT_COOP_40902 = ("TT_COOP_40902", "已有进行中的对接意向", 409)

# ── Favorite ────────────────────────────────────────────────
TT_FAV_40401 = ("TT_FAV_40401", "收藏目标不存在或不可见", 404)

# ── AI ──────────────────────────────────────────────────────
TT_AI_40301 = ("TT_AI_40301", "无权查看该任务", 403)
TT_AI_40401 = ("TT_AI_40401", "AI 任务不存在", 404)
TT_AI_42901 = ("TT_AI_42901", "AI 任务创建频率超限", 429)
TT_AI_50201 = ("TT_AI_50201", "AI Provider 调用失败", 502)
TT_AI_50301 = ("TT_AI_50301", "AI 服务不可用", 503)

# ── Admin ───────────────────────────────────────────────────
TT_ADMIN_40301 = ("TT_ADMIN_40301", "非管理员", 403)
TT_ADMIN_40001 = ("TT_ADMIN_40001", "审核驳回必须填写原因", 400)

# ── Institution（add-only，Release Closure P0-2） ─────────────
TT_INST_40001 = ("TT_INST_40001", "机构参数无效", 400)
TT_INST_40401 = ("TT_INST_40401", "机构不存在", 404)
TT_INST_40901 = ("TT_INST_40901", "机构状态不允许此操作", 409)
TT_INST_REG_40001 = ("TT_INST_REG_40001", "机构注册参数无效", 400)
TT_INST_REG_40901 = ("TT_INST_REG_40901", "机构名称、信用代码或管理员账号已存在", 409)
TT_INST_REG_40401 = ("TT_INST_REG_40401", "机构注册申请不存在", 404)
TT_INST_REG_40902 = ("TT_INST_REG_40902", "机构注册申请当前状态不允许该操作", 409)

# ── Patent ──────────────────────────────────────────────────
TT_PATENT_40401 = ("TT_PATENT_40401", "专利不存在", 404)
TT_PATENT_50201 = ("TT_PATENT_50201", "专利查询上游调用失败", 502)
TT_PATENT_50301 = ("TT_PATENT_50301", "专利查询服务不可用", 503)

# ── File ────────────────────────────────────────────────────
TT_FILE_40001 = ("TT_FILE_40001", "文件格式不支持", 400)
TT_FILE_40401 = ("TT_FILE_40401", "文件不存在", 404)
TT_FILE_50201 = ("TT_FILE_50201", "源站文件获取失败", 502)

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


def achievement_not_found(msg="成果不存在", details=None):
    code, message, status = TT_ACH_40401
    return BizError(code, msg, status, details)


def achievement_forbidden(msg="非成果所有者", details=None):
    code, message, status = TT_ACH_40301
    return BizError(code, msg, status, details)


def achievement_conflict(msg="成果状态不允许此操作", details=None):
    code, message, status = TT_ACH_40901
    return BizError(code, msg, status, details)


def demand_forbidden(msg="非需求所有者", details=None):
    code, message, status = TT_DMD_40301
    return BizError(code, msg, status, details)


def demand_conflict(msg="需求状态不允许此操作", details=None):
    code, message, status = TT_DMD_40901
    return BizError(code, msg, status, details)


def favorite_not_found(msg="收藏目标不存在或不可见", details=None):
    code, message, status = TT_FAV_40401
    return BizError(code, msg, status, details)


def coop_bad_request(msg="不能对自己发布的内容发起对接", details=None):
    code, message, status = TT_COOP_40001
    return BizError(code, msg, status, details)


def coop_forbidden(msg="无权操作此对接", details=None):
    code, message, status = TT_COOP_40301
    return BizError(code, msg, status, details)


def coop_not_found(msg="对接意向不存在", details=None):
    code, message, status = TT_COOP_40401
    return BizError(code, msg, status, details)


def coop_conflict(msg="对接状态不允许此操作", details=None):
    code, message, status = TT_COOP_40901
    return BizError(code, msg, status, details)


def coop_active_exists(msg="已有进行中的对接意向", details=None):
    code, message, status = TT_COOP_40902
    return BizError(code, msg, status, details)


def forbidden(msg="无权限访问该资源", details=None):
    code, message, status = TT_COMMON_40301
    return BizError(code, msg, status, details)


def ai_unavailable(msg="AI 服务不可用", details=None):
    code, message, status = TT_AI_50301
    return BizError(code, msg, status, details)


def ai_provider_failed(msg="AI 服务暂时不可用，请稍后重试", details=None):
    code, _, status = TT_AI_50201
    safe_msg = "AI 服务暂时不可用，请稍后重试"
    text = (msg or safe_msg).strip()
    lowered = text.lower()
    if any(hint in lowered for hint in (
        "provider", "qwen", "openai", "hermes", "deepseek",
        "http", "https://", "timeout", "connection", "api_key",
        "authorization", "ai_agent"
    )):
        text = safe_msg
    return BizError(code, text, status, details)


def patent_not_found(msg="专利不存在", details=None):
    code, message, status = TT_PATENT_40401
    return BizError(code, msg, status, details)


def patent_unavailable(msg="专利查询服务不可用", details=None):
    code, message, status = TT_PATENT_50301
    return BizError(code, msg, status, details)


def patent_provider_failed(msg="专利查询上游调用失败", details=None):
    code, message, status = TT_PATENT_50201
    return BizError(code, msg, status, details)


def file_upstream_error(msg="源站文件获取失败", details=None):
    code, message, status = TT_FILE_50201
    return BizError(code, msg, status, details)
