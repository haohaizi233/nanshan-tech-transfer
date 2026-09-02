class BizError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details

    def __str__(self):
        return f"[{self.code}] {self.message}"


TT_COMMON_40001 = ("TT_COMMON_40001", "请求参数无效", 400)
TT_COMMON_40101 = ("TT_COMMON_40101", "未提供认证令牌", 401)
TT_COMMON_40102 = ("TT_COMMON_40102", "认证令牌无效或已过期", 401)
TT_COMMON_40902 = ("TT_COMMON_40902", "资源版本冲突（乐观锁）", 409)
TT_AUTH_40103 = ("TT_AUTH_40103", "宿主凭证无效", 401)


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
