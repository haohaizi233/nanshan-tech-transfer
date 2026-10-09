"""导入行归一化：爬取列全部进入 import payload。"""

from core.errors import BizError
from modules.admin.service import _normalize_import_item


def main():
    item = _normalize_import_item({
        "kind": "platform",
        "name": "深圳市先进电子封装材料中小试基地",
        "platformType": "中小试基地",
        "platformTypeKey": "pilot",
        "unit": "深圳先进电子材料国际创新研究院",
        "functionText": "面向集成电路…",
        "contact": "周文祥",
        "phone": "13763372783",
        "serialNo": 1,
        "sourcePk": 1,
        "sourceStatus": 1,
        "orderNum": 0,
        "sourceSite": "first-net.cn",
        "sourceApi": "https://www.first-net.cn/portal/platformBase_showPlatformBaseList",
        "fetchedAt": "2026-09-11T09:56:51+08:00",
        "status": "active",
    })
    assert item["kind"] == "platform"
    assert item["name"].startswith("深圳市先进")
    assert item["platformType"] == "中小试基地"
    assert item["platformTypeKey"] == "pilot"
    assert item["unit"]
    assert item["functionText"]
    assert item["contact"] == "周文祥"
    assert item["phone"] == "13763372783"
    assert item["serialNo"] == 1
    assert item["sourcePk"] == 1
    assert item["sourceStatus"] == 1
    assert item["orderNum"] == 0
    assert item["sourceSite"] == "first-net.cn"
    assert item["fetchedAt"]

    item = _normalize_import_item({
        "kind": "service",
        "name": "中国工商银行股份有限公司深圳市分行",
        "intro": "深圳分行简介",
        "label": "银行",
        "logoFileId": "1849696008309708053",
        "sortOrder": 1,
        "sourceSite": "szte.com",
        "sourceApi": "https://www.szte.com/pubsapi/officialSiteApi/intellectualProperty/zyrz/user/get/1",
    })
    assert item["kind"] == "service"
    assert item["label"] == "银行"
    assert item["logoFileId"] == "1849696008309708053"
    assert item["intro"] == "深圳分行简介"

    snake = _normalize_import_item({
        "kind": "platform",
        "name": "概念验证中心示例",
        "platform_type": "概念验证中心",
        "platform_type_key": "poc",
        "functions": "功能说明",
        "serial_no": "2",
        "source_pk": "2",
        "source_status": "0",
        "order_num": "3",
        "source_site": "first-net.cn",
    })
    assert snake["platformTypeKey"] == "poc"
    assert snake["platformType"] == "概念验证中心"
    assert snake["functionText"] == "功能说明"
    assert snake["serialNo"] == 2
    assert snake["sourcePk"] == 2
    assert snake["sourceStatus"] == 0
    assert snake["orderNum"] == 3

    try:
        _normalize_import_item({"kind": "platform", "name": ""})
        raise AssertionError("expected empty name to fail")
    except BizError as exc:
        assert exc.code == "TT_INST_40001"

    print("PASS: institution import normalize")


if __name__ == "__main__":
    main()
