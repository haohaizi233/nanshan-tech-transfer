"""
admin 请求 Schema（Release Closure P0-2）—— Pydantic v2

仅用于管理端机构写接口（Create/Update）；其余管理端接口为 GET 查询参数或
沿用项目既有的 json_body dict 风格（分寸：§21 只要求 Institution 有明确 Schema）。

字段名 camelCase 与统一响应契约一致（institution 公开视图同为 camelCase）。
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

INST_KINDS = (
    "platform", "invest", "service",
    "university", "institute", "enterprise", "other",
)
PLATFORM_TYPE_KEYS = ("poc", "pilot", "other")


class InstitutionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    kind: str = Field(
        ...,
        description="机构类别：platform/invest/service/university/institute/enterprise/other",
    )
    name: str = Field(..., min_length=1, max_length=255)
    region: Optional[str] = Field(None, max_length=64)
    intro: Optional[str] = Field(None, max_length=5000)
    detailInfo: Optional[str] = Field(None, max_length=10000)
    label: Optional[str] = Field(None, max_length=64)
    logoFileId: Optional[str] = Field(None, max_length=64)
    sortOrder: int = Field(0, ge=0, le=10_000_000)
    userType: Optional[str] = Field(None, max_length=64)
    # platform 类专有（invest/service 忽略）
    platformType: Optional[str] = Field(None, max_length=64)
    platformTypeKey: Optional[str] = Field(None, max_length=16)
    unit: Optional[str] = Field(None, max_length=255)
    functionText: Optional[str] = Field(None, max_length=10000)
    contact: Optional[str] = Field(None, max_length=64)
    phone: Optional[str] = Field(None, max_length=64)
    serialNo: Optional[int] = Field(None, ge=0)
    detailActivityId: Optional[int] = Field(None)


class InstitutionUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    region: Optional[str] = Field(None, max_length=64)
    intro: Optional[str] = Field(None, max_length=5000)
    detailInfo: Optional[str] = Field(None, max_length=10000)
    label: Optional[str] = Field(None, max_length=64)
    logoFileId: Optional[str] = Field(None, max_length=64)
    sortOrder: Optional[int] = Field(None, ge=0, le=10_000_000)
    userType: Optional[str] = Field(None, max_length=64)
    platformType: Optional[str] = Field(None, max_length=64)
    platformTypeKey: Optional[str] = Field(None, max_length=16)
    unit: Optional[str] = Field(None, max_length=255)
    functionText: Optional[str] = Field(None, max_length=10000)
    contact: Optional[str] = Field(None, max_length=64)
    phone: Optional[str] = Field(None, max_length=64)
    serialNo: Optional[int] = Field(None, ge=0)
    detailActivityId: Optional[int] = Field(None)
