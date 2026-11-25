"""Executable acceptance-manifest & CI evidence verifier (HF05).

Validates `docs/auth/email-gateway/acceptance-manifest.yaml` against:
1. Immutable requirement ID completeness (`A01-A30`, `R-A01-R-A32`, `RF-A01-RF-A42`,
   `HF-A01-HF-A25`, `EXT-EMAIL-01-03`) with zero duplicate IDs;
2. Prohibition of hardcoded `status: PASS` on automated requirements (must declare
   `evidence_type`, `expected_outcome: PASS`, and concrete `test_nodes`);
3. Strict preservation of external live smoke items (`EXT-EMAIL-*`) as `NOT RUN`;
4. Filesystem existence of referenced `sources`/`tests` and Python AST / `.mjs` test
   node resolution;
5. Historical snapshot banners on `12`/`14`/`16` and factual accuracy on `15`;
6. Real JUnit XML execution verification (every scoped `test_node` executed and
   passed with zero skips or failures).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REQUIRED_A_IDS = {f"A{i:02d}" for i in range(1, 31)}
REQUIRED_R_A_IDS = {f"R-A{i:02d}" for i in range(1, 33)}
REQUIRED_RF_A_IDS = {f"RF-A{i:02d}" for i in range(1, 43)}
REQUIRED_HF_A_IDS = {f"HF-A{i:02d}" for i in range(1, 26)}
REQUIRED_EXT_IDS = {f"EXT-EMAIL-{i:02d}" for i in range(1, 4)}
REQUIRED_IDS = REQUIRED_A_IDS | REQUIRED_R_A_IDS | REQUIRED_RF_A_IDS | REQUIRED_HF_A_IDS | REQUIRED_EXT_IDS

ALLOWED_EVIDENCE_TYPES = frozenset(
    {
        "backend_pytest",
        "pg_redis_integration",
        "frontend_node_test",
        "miniprogram_node_test",
    }
)
PYTHON_EVIDENCE_TYPES = frozenset({"backend_pytest", "pg_redis_integration"})
JS_EVIDENCE_TYPES = frozenset({"frontend_node_test", "miniprogram_node_test"})
BANNED_STATIC_STATUSES = frozenset({"PASS", "PASSED", "OK", "VERIFIED", "SUCCESS", "TRUE"})


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def parse_manifest_yaml(raw: str) -> dict[str, Any]:
    """Parse acceptance-manifest.yaml via PyYAML when available, or strict stdlib subset."""
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(raw)
        if isinstance(loaded, dict):
            return loaded
    except ImportError:
        pass

    data: dict[str, Any] = {"requirements": []}
    current_req: dict[str, Any] | None = None
    current_list_key: str | None = None

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "requirements:":
            current_req = None
            current_list_key = None
            continue

        if not line.startswith(" ") and ":" in stripped:
            k, _, v = stripped.partition(":")
            data[k.strip()] = _strip_quotes(v)
            current_list_key = None
            continue

        if stripped.startswith("- id:"):
            if current_req is not None:
                data["requirements"].append(current_req)
            current_req = {"id": _strip_quotes(stripped.split(":", 1)[1])}
            current_list_key = None
            continue

        if current_req is None:
            continue

        if stripped.startswith("- ") and current_list_key is not None:
            lst = current_req.setdefault(current_list_key, [])
            if isinstance(lst, list):
                lst.append(_strip_quotes(stripped[2:]))
            continue

        if ":" in stripped:
            k, _, v = stripped.partition(":")
            key = k.strip()
            val = v.strip()
            if val == "[]" or val == "":
                current_req[key] = []
                current_list_key = key
            else:
                current_req[key] = _strip_quotes(val)
                current_list_key = None

    if current_req is not None:
        data["requirements"].append(current_req)
    return data


def _collect_python_test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _collect_js_test_titles(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {title for _q, title in re.findall(r"""\btest\(\s*(['"])(.+?)\1\s*,""", text)}


def _rel_path_to_pytest_classnames(rel_test_path: str) -> set[str]:
    norm = rel_test_path.replace("\\", "/").removesuffix(".py")
    candidates = {norm.replace("/", ".")}
    if norm.startswith("tech-transfer-service/"):
        candidates.add(norm.removeprefix("tech-transfer-service/").replace("/", "."))
    return candidates


def _load_junit_outcomes(xml_paths: list[Path]) -> dict[tuple[str, str], list[str]]:
    outcomes: dict[tuple[str, str], list[str]] = {}
    for xml_path in xml_paths:
        root = ET.parse(xml_path).getroot()
        for tc in root.iter("testcase"):
            classname = str(tc.attrib.get("classname") or "").strip()
            raw_name = str(tc.attrib.get("name") or "").strip()
            base_name = raw_name.split("[", 1)[0]
            if tc.find("failure") is not None:
                status = "failed"
            elif tc.find("error") is not None:
                status = "error"
            elif tc.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            outcomes.setdefault((classname, base_name), []).append(status)
    return outcomes


def _match_junit_statuses(
    junit_by_fn: dict[str, list[tuple[str, list[str]]]],
    rel_file: str,
    test_name: str,
) -> list[str]:
    cls_candidates = _rel_path_to_pytest_classnames(rel_file)
    matched: list[str] = []
    for j_cls, j_statuses in junit_by_fn.get(test_name, ()):
        if any(j_cls == cls or j_cls.startswith(f"{cls}.") for cls in cls_candidates):
            matched.extend(j_statuses)
    return matched


def verify_docs_consistency(repo_root: Path) -> list[str]:
    errors: list[str] = []
    docs_dir = repo_root / "docs" / "auth" / "email-gateway"
    for snap in ("12-final-acceptance.md", "14-phase-r-acceptance.md", "16-phase-r-final-acceptance.md"):
        p = docs_dir / snap
        if not p.exists():
            errors.append(f"Missing historical doc: {p}")
            continue
        head = p.read_text(encoding="utf-8")[:600]
        if "HISTORICAL SNAPSHOT" not in head:
            errors.append(f"{snap} must carry an explicit HISTORICAL SNAPSHOT banner")

    doc15 = docs_dir / "15-phase-r-final-hardening.md"
    if not doc15.exists():
        errors.append(f"Missing hardening doc: {doc15}")
    else:
        txt15 = doc15.read_text(encoding="utf-8")
        if "VARCHAR(128)" in txt15 or "idem_claimed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP" in txt15:
            errors.append("15-phase-r-final-hardening.md still contains stale 038 column mismatches")
        if "idx_auth_session_user_sid_status (user_id, sid, status, expires_at)" in txt15:
            errors.append("15-phase-r-final-hardening.md still contains stale auth_session index definition")
        if "source_contact_fingerprint VARCHAR(64)" not in txt15:
            errors.append("15-phase-r-final-hardening.md missing factual source_contact_fingerprint VARCHAR(64)")
    return errors


def verify_acceptance_manifest(
    manifest_path: Path,
    *,
    repo_root: Path | None = None,
    junit_xml_paths: list[Path] | None = None,
    scope: str = "all",
    check_docs: bool = True,
    require_report_doc: bool = False,
) -> dict[str, Any]:
    root = repo_root or manifest_path.resolve().parents[3]
    errors: list[str] = []

    if not manifest_path.exists():
        raise AssertionError(f"Manifest not found: {manifest_path}")

    manifest = parse_manifest_yaml(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "phase-r-hotfix":
        errors.append(f"manifest version must be 'phase-r-hotfix', got {manifest.get('version')!r}")
    if manifest.get("schema_version") != "039":
        errors.append(f"manifest schema_version must be '039', got {manifest.get('schema_version')!r}")
    baseline = str(manifest.get("baseline_sha") or "").strip()
    if len(baseline) < 7 or "PENDING" in baseline.upper():
        errors.append(f"Invalid baseline_sha: {baseline!r}")

    reqs = manifest.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        raise AssertionError("manifest requirements must be a non-empty list")

    by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    py_ast_cache: dict[Path, set[str]] = {}
    js_test_cache: dict[Path, set[str]] = {}

    for item in reqs:
        if not isinstance(item, dict):
            errors.append(f"Invalid requirement entry: {item!r}")
            continue
        rid = str(item.get("id") or "").strip()
        if not rid:
            errors.append(f"Requirement missing id: {item!r}")
            continue
        if rid in by_id:
            duplicates.append(rid)
        by_id[rid] = item

    if duplicates:
        errors.append(f"Duplicate manifest requirement IDs: {sorted(set(duplicates))}")

    missing_ids = sorted(REQUIRED_IDS - set(by_id))
    if missing_ids:
        errors.append(f"Missing required immutable manifest IDs: {missing_ids}")

    junit_by_fn: dict[str, list[tuple[str, list[str]]]] | None = None
    if junit_xml_paths:
        missing_xml = [str(p) for p in junit_xml_paths if not p.exists()]
        if missing_xml:
            errors.append(f"JUnit XML file(s) not found: {missing_xml}")
        else:
            junit_outcomes = _load_junit_outcomes(junit_xml_paths)
            junit_by_fn = {}
            for (j_cls, j_fn), j_statuses in junit_outcomes.items():
                junit_by_fn.setdefault(j_fn, []).append((j_cls, j_statuses))

    checked_junit_nodes = 0
    for rid, item in by_id.items():
        sources = item.get("sources") or []
        tests = item.get("tests") or []
        test_nodes = item.get("test_nodes") or []
        evidence_type = str(item.get("evidence_type") or "").strip()
        raw_status = str(item.get("status") or "").strip()

        if not isinstance(sources, list) or not sources:
            errors.append(f"{rid}: sources must be a non-empty list")
        else:
            for src in sources:
                if not (root / str(src)).exists():
                    errors.append(f"{rid}: missing source file {src}")

        if rid in REQUIRED_EXT_IDS:
            if evidence_type != "external_live_smoke":
                errors.append(f"{rid}: evidence_type must be 'external_live_smoke', got {evidence_type!r}")
            if raw_status != "NOT RUN":
                errors.append(f"{rid}: external verification must remain 'NOT RUN', got {raw_status!r}")
            if tests or test_nodes:
                errors.append(f"{rid}: external verification must not claim automated tests")
            continue

        if raw_status.upper() in BANNED_STATIC_STATUSES or (raw_status and raw_status != "DYNAMIC"):
            errors.append(
                f"{rid}: hardcoded static status={raw_status!r} is forbidden; use evidence_type + expected_outcome + test_nodes"
            )
        if str(item.get("expected_outcome") or "").strip() != "PASS":
            errors.append(f"{rid}: expected_outcome must be 'PASS', got {item.get('expected_outcome')!r}")
        if evidence_type not in ALLOWED_EVIDENCE_TYPES:
            errors.append(f"{rid}: invalid evidence_type {evidence_type!r}")
            continue
        if not isinstance(tests, list) or not tests:
            errors.append(f"{rid}: automated requirement must list non-empty tests")
            continue
        if not isinstance(test_nodes, list) or not test_nodes:
            errors.append(f"{rid}: automated requirement must list non-empty test_nodes")
            continue

        for test_rel in tests:
            if not (root / str(test_rel)).exists():
                errors.append(f"{rid}: missing test file {test_rel}")

        for node in test_nodes:
            node_str = str(node)
            if "::" not in node_str:
                errors.append(f"{rid}: invalid test_node '{node_str}' (expected '<file>::<test_name>')")
                continue
            rel_file, test_name = node_str.split("::", 1)
            full_test_path = root / rel_file
            if not full_test_path.exists():
                errors.append(f"{rid}: test_node references missing file {rel_file}")
                continue
            if rel_file not in tests:
                errors.append(f"{rid}: test_node file {rel_file} must also appear in tests")

            if evidence_type in PYTHON_EVIDENCE_TYPES:
                if full_test_path not in py_ast_cache:
                    py_ast_cache[full_test_path] = _collect_python_test_functions(full_test_path)
                if test_name not in py_ast_cache[full_test_path]:
                    errors.append(f"{rid}: Python AST check failed: {test_name} not found in {rel_file}")
                    continue
                should_check_junit = junit_by_fn is not None and (scope == "all" or evidence_type == scope)
                if should_check_junit and junit_by_fn is not None:
                    checked_junit_nodes += 1
                    matched_statuses = _match_junit_statuses(junit_by_fn, rel_file, test_name)
                    if not matched_statuses:
                        errors.append(f"{rid}: test_node '{node_str}' missing from JUnit XML execution")
                    else:
                        bad = [s for s in matched_statuses if s != "passed"]
                        if bad:
                            errors.append(f"{rid}: test_node '{node_str}' did not pass cleanly in JUnit XML ({bad})")
            elif evidence_type in JS_EVIDENCE_TYPES:
                if full_test_path not in js_test_cache:
                    js_test_cache[full_test_path] = _collect_js_test_titles(full_test_path)
                if test_name not in js_test_cache[full_test_path]:
                    errors.append(f"{rid}: JS test title check failed: '{test_name}' not found in {rel_file}")

    if check_docs:
        errors.extend(verify_docs_consistency(root))

    if require_report_doc:
        rep = root / "docs" / "auth" / "email-gateway" / "17-phase-r-hotfix-acceptance.md"
        if not rep.exists():
            errors.append(f"Missing final report doc: {rep}")
        else:
            rtxt = rep.read_text(encoding="utf-8")
            if "CODE_ACCEPTED" not in rtxt:
                errors.append("17-phase-r-hotfix-acceptance.md missing CODE_ACCEPTED verdict")
            if "NOT RUN" not in rtxt:
                errors.append("17-phase-r-hotfix-acceptance.md missing EXT-EMAIL NOT RUN declaration")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "requirement_count": len(by_id),
        "checked_junit_nodes": checked_junit_nodes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Phase R-Hotfix acceptance manifest and JUnit execution evidence"
    )
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=default_root / "docs" / "auth" / "email-gateway" / "acceptance-manifest.yaml",
    )
    parser.add_argument(
        "--junit-xml",
        action="append",
        dest="junit_xml",
        type=Path,
        default=[],
        help="Path to pytest --junit-xml output file (can be specified multiple times)",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "pg_redis_integration", "backend_pytest"),
        default="all",
        help="Which Python test categories require JUnit XML proof in this invocation",
    )
    parser.add_argument("--skip-docs", action="store_true", help="Skip doc snapshot consistency checks")
    parser.add_argument("--require-report-doc", action="store_true", help="Also verify 17-phase-r-hotfix-acceptance.md")
    args = parser.parse_args(argv)

    result = verify_acceptance_manifest(
        args.manifest.resolve(),
        repo_root=default_root,
        junit_xml_paths=[p.resolve() for p in args.junit_xml],
        scope=args.scope,
        check_docs=not args.skip_docs,
        require_report_doc=args.require_report_doc,
    )
    if not result["ok"]:
        sys.stderr.write("[FAIL] Acceptance evidence verification failed:\n")
        for err in result["errors"]:
            sys.stderr.write(f"  - {err}\n")
        return 1
    print(
        f"[OK] Verified {result['requirement_count']} manifest requirements "
        f"(junit_nodes_verified={result['checked_junit_nodes']}, scope={args.scope})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
