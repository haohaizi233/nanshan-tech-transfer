"""RF11: 机器可读验收清单 (acceptance-manifest.yaml) 完整性与不可变语义门禁测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "auth" / "email-gateway" / "acceptance-manifest.yaml"

EXPECTED_A: dict[str, str] = {
    "A01": "生产环境无法使用 Mock Email",
    "A02": "EMAIL_ENABLED=false 时无法真实发信",
    "A03": "未知 Provider 不会静默回退",
    "A04": "OTP、Token、Grant 不进入日志",
    "A05": "Redis 异常时生产发送 Fail-Closed",
    "A06": "未确权邮箱无法用于账号恢复",
    "A07": "安全邮箱换绑具备二次认证",
    "A08": "Challenge 与 Grant 不可重复消费",
    "A09": "邮件发送失败不会残留错误有效挑战",
    "A10": "真实数据库并发核验通过",
    "A11": "邮件链接 GET 无不可逆副作用",
    "A12": "密码重置后旧会话失效",
    "A13": "SMTP 错误分类完整",
    "A14": "SES 请求与响应契约测试通过",
    "A15": "多维原子风控完整",
    "A16": "投递任务具备应用内部幂等性",
    "A17": "供应商结果未知时不会盲目重发",
    "A18": "邮件结构化投递 Receipt",
    "A19": "邮件故障诊断工具可用",
    "A20": "邮件模板工程化",
    "A21": "H5 邮箱流程正常",
    "A22": "微信小程序邮箱流程正常",
    "A23": "数据库增量迁移兼容",
    "A24": "原有 SMS Gateway 全量回归",
    "A25": "微信登录及注册流程无回归",
    "A26": "邮箱专项测试进入 CI",
    "A27": "部署及送达验收文档完整",
    "A28": "密码找回接口防账号枚举",
    "A29": "风控及投递日志完成脱敏",
    "A30": "代码及文档实际行为一致",
}

EXPECTED_RA: dict[str, str] = {
    "R-A01": "首次绑定安全邮箱必须满足敏感操作授权策略",
    "R-A02": "已绑定邮箱换绑必须通过 Step-up",
    "R-A03": "JWT 刷新不会推进真实 auth_time",
    "R-A04": "旧 Token 不会自动获得近期认证资格",
    "R-A05": "Step-up Grant 强制绑定用途及目标",
    "R-A06": "Grant 不可跨账号、跨会话消费",
    "R-A07": "密码重置、邮箱绑定锁顺序统一",
    "R-A08": "真实交叉事务并发测试无未处理死锁",
    "R-A09": "同一 Challenge 并发核验仅成功一次",
    "R-A10": "同一 Grant 并发消费仅成功一次",
    "R-A11": "匿名恢复核验失败公开语义一致",
    "R-A12": "防枚举改造不影响真实失败次数累加",
    "R-A13": "高权限账号不会通过弱认证建立恢复渠道",
    "R-A14": "已关闭认证状态不可被投递回执重新激活",
    "R-A15": "同一 HTTP 幂等请求不会重复创建任务",
    "R-A16": "同一幂等请求不会重复消耗真实发送额度",
    "R-A17": "幂等冲突能够正确识别",
    "R-A18": "Provider unknown 不会盲目重发",
    "R-A19": "投递状态转换采用真实状态 CAS",
    "R-A20": "Worker 崩溃恢复具备明确安全边界",
    "R-A21": "所有异常终止路径执行必要 PII 清理",
    "R-A22": "Provider 切换后历史回执不会错误查询",
    "R-A23": "供应商日志与诊断数据完成脱敏",
    "R-A24": "H5 首次绑定和换绑正常",
    "R-A25": "微信小程序首次绑定和换绑正常",
    "R-A26": "原 SMS Gateway 不发生安全回归",
    "R-A27": "微信登录、刷新、注销无回归",
    "R-A28": "数据库迁移支持历史数据升级",
    "R-A29": "新增安全测试实际进入 CI",
    "R-A30": "原始 A01–A30 验收编号完整恢复",
    "R-A31": "本轮新增安全模块无未解释类型问题",
    "R-A32": "真实外部投递验收未执行时明确 NOT RUN",
}

EXPECTED_RFA: dict[str, str] = {
    "RF-A01": "不存在的新版 SID 必须拒绝",
    "RF-A02": "会话查询异常必须 Fail-Closed",
    "RF-A03": "已注销会话无法签发或消费 Step-up Grant",
    "RF-A04": "旧 Token 不得获得现代近期认证资格",
    "RF-A05": "CAS 失败时 Provider 调用次数为零",
    "RF-A06": "CAS 未提交时 Provider 调用次数为零",
    "RF-A07": "多执行者竞争发送权仅一方获得",
    "RF-A08": "Challenge 已取消或过期时不能获得新发送权",
    "RF-A09": "迟到回执不能激活已关闭 Challenge",
    "RF-A10": "Refresh 与密码重置并发不能恢复旧会话",
    "RF-A11": "Refresh 与 Logout 并发具备一致结果",
    "RF-A12": "普通密码修改后旧恢复 Grant 失效",
    "RF-A13": "密码重置后历史恢复 Challenge 按策略撤销",
    "RF-A14": "登录与凭证修改并发不会签发错误有效会话",
    "RF-A15": "全局安全事务锁顺序得到真实测试验证",
    "RF-A16": "新版 Step-up Challenge 强制绑定完整上下文",
    "RF-A17": "Step-up Challenge 不可跨会话核验",
    "RF-A18": "Step-up Challenge 不可跨用途核验",
    "RF-A19": "Step-up Challenge 不可跨目标核验",
    "RF-A20": "不完整历史 Challenge 不会获得新版 Grant",
    "RF-A21": "安全关键异常不再触发弱化回退",
    "RF-A22": "生产安全 Schema 版本具备明确门禁",
    "RF-A23": "Provider 成功后持久化失败不会错误释放幂等键",
    "RF-A24": "unknown 状态不会盲目重新发送",
    "RF-A25": "idem_pending 中间状态具备明确生命周期",
    "RF-A26": "活跃任务不会因幂等 TTL 到期而错误重放",
    "RF-A27": "清理程序不会破坏合法执行中的任务",
    "RF-A28": "所有必要终止路径执行 PII 清理",
    "RF-A29": "Redis 状态转换失败具备诊断及协调策略",
    "RF-A30": "PostgreSQL 与 Provider 结果不一致时安全收敛",
    "RF-A31": "原始 A01–A30 编号恢复",
    "RF-A32": "原始 R-A01–R-A32 编号恢复",
    "RF-A33": "验收清单具备自动化完整性检查",
    "RF-A34": "原 SMS Gateway 不发生安全回归",
    "RF-A35": "微信登录、密码登录、刷新及注销无回归",
    "RF-A36": "H5 邮箱绑定及密码恢复流程无回归",
    "RF-A37": "微信小程序账号安全流程无回归",
    "RF-A38": "最新数据库迁移兼容历史版本",
    "RF-A39": "安全核心阻断式 mypy 通过",
    "RF-A40": "新增真实并发与故障注入测试进入 CI",
    "RF-A41": "性能数据具有实际测试证据",
    "RF-A42": "未授权真实邮件测试未被执行且如实标记",
}

EXPECTED_EXT: dict[str, str] = {
    "EXT-EMAIL-01": "真实 SMTP 投递及受控收件箱确认",
    "EXT-EMAIL-02": "真实腾讯云 SES 投递及受控收件箱确认",
    "EXT-EMAIL-03": "SPF / DKIM / DMARC 与发信域名配置检查",
}


def _parse_manifest_fallback(raw: str) -> dict[str, Any]:
    """轻量零依赖 YAML 校验解析器（仅当 PyYAML 未安装时启用）。"""
    items: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    cur_list_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- id:"):
            if cur is not None:
                items.append(cur)
            cur = {"id": stripped.split(":", 1)[1].strip().strip('"'), "sources": [], "tests": []}
            cur_list_key = None
        elif cur is not None and stripped in {"sources: []", "tests: []"}:
            key = stripped.split(":", 1)[0]
            cur[key] = []
            cur_list_key = None
        elif cur is not None and stripped in {"sources:", "tests:"}:
            cur_list_key = stripped[:-1]
        elif cur is not None and stripped.startswith("- ") and cur_list_key:
            cur[cur_list_key].append(stripped[2:].strip().strip('"'))
        elif cur is not None and ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            cur[k.strip()] = v.strip().strip('"')
            cur_list_key = None
    if cur is not None:
        items.append(cur)
    return {"requirements": items}


def _load_manifest() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_text(encoding="utf-8")
    try:
        import yaml

        data = yaml.safe_load(raw)
        assert isinstance(data, dict)
        return data
    except ImportError:
        return _parse_manifest_fallback(raw)


def test_acceptance_manifest_integrity_immutable_ids_and_evidence_paths():
    assert MANIFEST_PATH.is_file(), f"Missing manifest: {MANIFEST_PATH}"
    data = _load_manifest()
    reqs = data.get("requirements")
    assert isinstance(reqs, list)

    seen_ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for entry in reqs:
        rid = str(entry["id"])
        seen_ids.append(rid)
        by_id[rid] = entry

    # 1. 编号无重复
    assert len(seen_ids) == len(set(seen_ids)), "Duplicate requirement IDs found in manifest"

    # 2. 原始 A01-A30, R-A01-R-A32, RF-A01-RF-A42, EXT-EMAIL-01-03 完整且语义严格一致
    all_expected = {**EXPECTED_A, **EXPECTED_RA, **EXPECTED_RFA, **EXPECTED_EXT}
    assert set(by_id.keys()) == set(all_expected.keys())
    for rid, expected_desc in all_expected.items():
        assert by_id[rid]["description"] == expected_desc, f"{rid} description drifted!"

    # 3. 外部真实投递验收不得被标为 PASS
    for ext_id in EXPECTED_EXT:
        assert by_id[ext_id]["status"] == "NOT RUN", f"{ext_id} must remain NOT RUN"

    # 4. 非外部条款全部有真实代码与测试证据路径，且路径在仓库真实存在
    for rid, entry in by_id.items():
        sources = entry.get("sources") or []
        tests = entry.get("tests") or []
        assert sources, f"{rid} missing source references"
        for src in sources:
            assert (REPO_ROOT / src).exists(), f"{rid} missing source file: {src}"
        if rid not in EXPECTED_EXT:
            assert entry["status"] == "PASS", f"{rid} expected PASS"
            assert tests, f"{rid} missing test evidence"
            for test_path in tests:
                assert (REPO_ROOT / test_path).is_file(), f"{rid} missing test file: {test_path}"
