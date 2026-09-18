"""
联系方式脱敏工具

规则：对接被对方接受（cooperation_intent.status ∈ accepted/confirmed/completed）
之前，除发布方本人外的所有查看者（含未登录游客）只能看到脱敏值。
"""


def mask_name(name):
    """姓名脱敏：保留姓氏，李经理 → 李**"""
    if not name:
        return name or None
    return name[0] + "**"


def mask_phone(phone):
    """电话脱敏：13912342222 → 139****2222"""
    if not phone or len(phone) < 8:
        return phone or None
    return phone[:3] + "****" + phone[-4:]


def mask_email(email):
    """邮箱脱敏：li@jm-green.com → l****@jm-green.com"""
    if not email or "@" not in email:
        # 旧库可能遗留非邮箱格式的联系方式。公开详情不能因无法按邮箱规则
        # 打码就回退为明文；返回空值让调用方按“无可展示信息”处理。
        return None
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        return (local[:1] or "") + "****@" + domain
    return local[:2] + "****@" + domain


def mask_wechat(wechat):
    """微信号脱敏：jm_green_li → jm****i"""
    if not wechat:
        return wechat or None
    if len(wechat) <= 3:
        return "*" * len(wechat)
    return wechat[:2] + "****" + wechat[-1:]


def mask_contact(contact):
    """联系方式整体脱敏（contactTitle 职务非隐私，保留）"""
    return {
        "contactName": mask_name(contact.get("contactName")),
        "contactTitle": contact.get("contactTitle"),
        "contactPhone": mask_phone(contact.get("contactPhone")),
        "contactEmail": mask_email(contact.get("contactEmail")),
        "contactWechat": mask_wechat(contact.get("contactWechat")),
    }
