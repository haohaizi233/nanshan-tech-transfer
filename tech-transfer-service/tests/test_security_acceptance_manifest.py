"""验收清单可执行证据门禁测试（HF05）：验证编号不可变性、AST/JUnit 证据与文档一致性。"""

from __future__ import annotations

import uuid
from pathlib import Path

from scripts.verify_acceptance_evidence import (
    REQUIRED_IDS,
    _match_junit_statuses,
    parse_manifest_yaml,
    verify_acceptance_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "auth" / "email-gateway" / "acceptance-manifest.yaml"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_acceptance_manifest_integrity_immutable_ids_and_evidence_paths():
    """验证 A01-A30、R-A01-R-A32、RF-A01-RF-A42、HF-A01-HF-A25、EXT-EMAIL-01-03 与 CI 阻断配置。"""
    manifest = parse_manifest_yaml(MANIFEST_PATH.read_text(encoding="utf-8"))
    reqs = manifest.get("requirements") or []
    ids = [str(item.get("id")) for item in reqs]
    assert len(ids) == len(set(ids)), "Manifest contains duplicate requirement IDs"
    assert REQUIRED_IDS.issubset(set(ids))

    result = verify_acceptance_manifest(MANIFEST_PATH, repo_root=REPO_ROOT, check_docs=True)
    assert result["ok"] is True, result["errors"]

    ci_text = CI_PATH.read_text(encoding="utf-8")
    for test_file in (
        "tests/test_security_provider_execution_right.py",
        "tests/test_security_idempotency_crash_recovery.py",
        "tests/test_security_delivery_fault_injection.py",
        "tests/test_security_acceptance_manifest.py",
    ):
        assert test_file in ci_text
    assert "verify_acceptance_evidence.py" in ci_text
    assert "--junit-xml=security-junit.xml" in ci_text
    assert "mypy modules/security core/jwt_utils.py core/middleware.py" in ci_text


def test_acceptance_manifest_rejects_static_pass_and_verifies_ast_and_docs(tmp_path: Path):
    """验证证据核验脚本能拦截静态 status=PASS、缺失节点与不真实 JUnit XML。"""
    raw = MANIFEST_PATH.read_text(encoding="utf-8")

    # 1. 若某条自动化项写死 status: PASS，必须拒绝
    bad_manifest = tmp_path / f"bad-{uuid.uuid4().hex[:8]}.yaml"
    bad_manifest.write_text(
        raw.replace("expected_outcome: PASS", "status: PASS\n    expected_outcome: PASS", 1),
        encoding="utf-8",
    )
    bad_res = verify_acceptance_manifest(bad_manifest, repo_root=REPO_ROOT, check_docs=False)
    assert bad_res["ok"] is False
    assert any("hardcoded static status='PASS'" in err for err in bad_res["errors"])

    # 2. 若某条节点引用不存在的测试函数，AST 门禁必须失败
    missing_node_manifest = tmp_path / f"missing-{uuid.uuid4().hex[:8]}.yaml"
    missing_node_manifest.write_text(
        raw.replace(
            "test_email_provider_registry_strict_check_order",
            "test_nonexistent_function_xyz",
            1,
        ),
        encoding="utf-8",
    )
    ast_res = verify_acceptance_manifest(missing_node_manifest, repo_root=REPO_ROOT, check_docs=False)
    assert ast_res["ok"] is False
    assert any("Python AST check failed" in err for err in ast_res["errors"])

    # 3. 若 JUnit XML 显示某项被 skip 或未执行，必须拒绝
    fake_junit = tmp_path / "junit.xml"
    fake_junit.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="0" skipped="1">
  <testcase classname="tests.test_email_risk" name="test_email_risk_and_rate_limiter_fail_closed_on_redis_failure">
    <skipped message="skipped" />
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    junit_res = verify_acceptance_manifest(
        MANIFEST_PATH,
        repo_root=REPO_ROOT,
        junit_xml_paths=[fake_junit],
        scope="pg_redis_integration",
        check_docs=True,
    )
    assert junit_res["ok"] is False
    assert any("did not pass cleanly in JUnit XML" in err for err in junit_res["errors"])


def test_match_junit_statuses_supports_class_scoped_test_methods():
    """验证 pytest class-scoped testcase classname（如 module.TestClass）可精确匹配且不误匹配相似模块。"""
    junit_by_fn = {
        "test_refresh_happy_path": [
            ("tests.test_cov_ach_identity.TestRefreshSession", ["passed"]),
            ("tests.test_cov_ach_identity_other.TestRefreshSession", ["failed"]),
        ]
    }
    statuses = _match_junit_statuses(
        junit_by_fn,
        "tech-transfer-service/tests/test_cov_ach_identity.py",
        "test_refresh_happy_path",
    )
    assert statuses == ["passed"]


def test_match_junit_statuses_treats_any_real_pass_as_evidence_over_skip():
    """同一节点在集成报告 passed、全量报告 skipped 时，证据成立；失败仍必须阻塞。"""
    junit_by_fn = {
        "test_hf03_migration_039": [
            ("tests.test_security_delivery_fault_injection", ["passed"]),
            ("tests.test_security_delivery_fault_injection", ["skipped"]),
        ],
        "test_failed_node": [
            ("tests.test_security_delivery_fault_injection", ["passed"]),
            ("tests.test_security_delivery_fault_injection", ["failed"]),
        ],
    }
    rel_file = "tech-transfer-service/tests/test_security_delivery_fault_injection.py"
    assert _match_junit_statuses(junit_by_fn, rel_file, "test_hf03_migration_039") == ["passed"]
    assert _match_junit_statuses(junit_by_fn, rel_file, "test_failed_node") == ["failed"]
