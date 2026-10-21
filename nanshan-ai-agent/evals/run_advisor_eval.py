import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
from time import perf_counter
from unittest.mock import patch


TOPICS = ("机器视觉", "人工智能", "生物医药", "新能源", "机器人", "量子传感", "芯片", "材料")
MATURITY = ("01_idea", "02_lab", "03_pilot_ready", "04_pilot_done", "05_mass_ready", "06_mass_done")


def search_records(records, card_type, **filters):
    results = []
    for source in records:
        if source.get("card_type") != card_type or source.get("status") != "published" or source.get("deleted_at"):
            continue
        if filters.get("exclude_owner_user_id") is not None and source.get("owner_user_id") == filters["exclude_owner_user_id"]:
            continue
        keywords = filters.get("keywords") or []
        searchable = json.dumps({key: source.get(key) for key in ("title", "tech_intro", "description", "application_fields", "innovation_points")}, ensure_ascii=False)
        if keywords and not any(keyword.casefold() in searchable.casefold() for keyword in keywords):
            continue
        organization = source.get("source_org_name") if card_type == "achievement" else source.get("org_name_snapshot")
        if filters.get("organization") and filters["organization"] not in (organization or ""):
            continue
        if filters.get("region") and filters["region"] not in (source.get("region") or ""):
            continue
        rejected = False
        for query_field, record_field in (("min_price_wan", "price_min_wan"), ("max_price_wan", "price_max_wan"), ("min_budget_wan", "budget_min_wan"), ("max_budget_wan", "budget_max_wan")):
            value = filters.get(query_field)
            if value is None:
                continue
            actual = source.get(record_field)
            if actual is None or (query_field.startswith("min_") and actual < value) or (query_field.startswith("max_") and actual > value):
                rejected = True
        if rejected:
            continue
        maturity = filters.get("min_maturity")
        if maturity in MATURITY and (source.get("maturity_level") not in MATURITY or MATURITY.index(source["maturity_level"]) < MATURITY.index(maturity)):
            continue
        if any(mode not in (source.get("coop_mode") or []) for mode in filters.get("coop_modes") or []):
            continue
        results.append(copy.deepcopy(source))
    results.sort(key=lambda row: (-sum(5 if word in row.get("title", "") else 1 for word in filters.get("keywords", []) if word in json.dumps(row, ensure_ascii=False)), str(row.get("created_at") or ""), row["id"]))
    return results[:filters.get("limit", 20)]


def offline_route(message):
    from app.schemas import RouteResult
    topic = next((value for value in TOPICS if value in message), "不存在的")
    kind = "demand" if "需求" in message and "成果" not in message else "achievement"
    values = {"intent": "search_" + kind, "keywords": [topic]}
    ceiling = re.search(r"(?:不超过|不高于|最多|最高|上限)(\d+(?:\.\d+)?)\s*万", message)
    if ceiling:
        values["max_budget_wan" if kind == "demand" else "max_price_wan"] = float(ceiling.group(1))
    return RouteResult(**values)


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percentile) - 1)], 3)


def summarize(results, mode):
    latencies = [row["latencyMs"] for row in results]
    hits = [row["hitAt5"] for row in results if row.get("hitAt5") is not None]
    return {
        "mode": mode,
        "cases": len(results),
        "passed": sum(row["passed"] for row in results),
        "failed": sum(not row["passed"] for row in results),
        "hitAt5": round(statistics.mean(hits), 4) if hits else None,
        "latencyP50Ms": _percentile(latencies, 0.5),
        "latencyP95Ms": _percentile(latencies, 0.95),
        "modelCalls": sum(row["modelCalls"] for row in results) if mode == "offline" else None,
        "providerTokens": None,
        "warning": "离线耗时和替身调用次数不是生产延迟、真实模型准确率或账单" if mode == "offline" else "真实模型用量未被采集时记未知；人工相关性仍需审阅",
        "results": results,
    }


def compare_baseline(current, baseline):
    if baseline.get("mode") != current["mode"] or baseline.get("corpusSha256") != current["corpusSha256"] or [row["id"] for row in baseline["results"]] != [row["id"] for row in current["results"]]:
        raise ValueError("baseline must use the same mode, corpus hash and ordered case IDs")
    if current["hitAt5"] is None or baseline.get("hitAt5") is None:
        return None
    return current["hitAt5"] >= baseline["hitAt5"]


def evaluate(corpus, mode="offline", limit=None):
    from app import main, reranker, router
    from app.schemas import ChatRequest
    records = corpus["records"]
    contexts = corpus["contexts"]
    indexed = {(row["card_type"], row["id"]): row for row in records}

    def visible(card_type, ids, exclude_owner_user_id=None):
        return [copy.deepcopy(indexed[(card_type, record_id)]) for record_id in ids if (card_type, record_id) in indexed and indexed[(card_type, record_id)].get("status") == "published" and not indexed[(card_type, record_id)].get("deleted_at") and indexed[(card_type, record_id)].get("owner_user_id") != exclude_owner_user_id]

    output = []
    for case in corpus["cases"][:limit]:
        model_calls = []

        def route_call(message):
            model_calls.append("route")
            return offline_route(message)

        def rank_call(content):
            model_calls.append("rank")
            return {"results": [{"id": row["id"]} for row in content["candidates"]]}

        payload = {"message": case["message"], "exclude_owner_user_id": 99}
        if case.get("context"):
            payload["context"] = copy.deepcopy(contexts[case["context"]])
        started = perf_counter()
        expected = case["expected"]
        violations = []
        cards = []
        response = {}
        error_type = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(main, "search_achievements", side_effect=lambda **values: search_records(records, "achievement", **values)))
            stack.enter_context(patch.object(main, "search_demands", side_effect=lambda **values: search_records(records, "demand", **values)))
            stack.enter_context(patch.object(main, "get_visible_records", side_effect=visible, create=True))
            if mode == "offline":
                stack.enter_context(patch.object(router, "_classify_intent_llm", side_effect=route_call))
                stack.enter_context(patch.object(reranker, "_call_reranker", side_effect=rank_call))
            try:
                result = main._process_ai_chat(ChatRequest(**payload))
                response = result.model_dump()
                cards = response.get("data") if isinstance(response.get("data"), list) else []
            except Exception as error:
                error_type = type(error).__name__
        text = response.get("message") or ""
        if error_type:
            if expected["kind"] != "rejected":
                violations.append("exception:" + error_type)
        elif expected["kind"] == "rejected":
            violations.append("expected_rejection")
        elif expected["kind"] == "results":
            if not cards:
                violations.append("expected_results")
        elif cards:
            violations.append("unexpected_cards")
        elif expected["kind"] == "clarify" and not re.search(r"请|提供|无法|不能|未|确认|条件|需要|预算|调整", text):
            violations.append("missing_clarification")
        if expected.get("contains") and expected["contains"] not in text:
            violations.append("missing_expected_text")
        for forbidden in expected.get("forbidden", []):
            if forbidden in text:
                violations.append("unsafe_reply")
        plan = response.get("queryPlan") or {}
        for name in ("min_price_wan", "max_price_wan", "min_budget_wan", "max_budget_wan"):
            if name in expected and expected["kind"] == "results" and plan.get(name) != expected[name]:
                violations.append("wrong_query_condition")
        for card in cards:
            record = indexed.get((card.get("card_type"), card.get("id")))
            if record is None:
                violations.append("fabricated_id")
                continue
            if record.get("status") != "published" or record.get("deleted_at"):
                violations.append("unpublished_record")
            if record.get("owner_user_id") == 99:
                violations.append("own_record")
            for query_field, record_field in (("max_price_wan", "price_max_wan"), ("max_budget_wan", "budget_max_wan")):
                if expected.get(query_field) is not None:
                    if record.get(record_field) is None or record[record_field] > expected[query_field]:
                        violations.append("hard_condition_violation")
        ids = [card.get("id") for card in cards[:5]]
        expected_ids = expected.get("ids") or []
        hit = int(bool(set(ids) & set(expected_ids))) if expected_ids else None
        if hit == 0:
            violations.append("relevant_candidate_missing")
        if case["category"] == "reference" and expected_ids and set(ids) != set(expected_ids):
            violations.append("wrong_reference")
        output.append({"id": case["id"], "category": case["category"], "passed": not violations, "violations": sorted(set(violations)), "ids": ids, "hitAt5": hit, "latencyMs": round((perf_counter() - started) * 1000, 3), "modelCalls": len(model_calls) if mode == "offline" else None})
    report = summarize(output, mode)
    report["corpusSha256"] = hashlib.sha256(json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description="Synthetic advisor regression; offline by default, no production DB access")
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("advisor_cases.json"))
    parser.add_argument("--agent-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live and os.getenv("AI_EVAL_ALLOW_LIVE") != "1":
        parser.error("Real paid model calls require AI_EVAL_ALLOW_LIVE=1 and --live")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if not args.live:
        for key, value in {"LLM_API_URL": "https://offline.invalid/v1/chat/completions", "LLM_API_KEY": "offline-fixture", "LLM_MODEL": "offline-fixture", "DB_HOST": "127.0.0.1", "DB_NAME": "offline_fixture", "DB_USER": "offline_fixture", "DB_PASSWORD": "offline_fixture", "AI_EMPTY_DIAGNOSTICS": "0"}.items():
            os.environ.setdefault(key, value)
    sys.path.insert(0, str(args.agent_root.resolve()))
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    report = evaluate(corpus, "live" if args.live else "offline", args.limit)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["baseline"] = {key: baseline.get(key) for key in ("mode", "cases", "passed", "hitAt5")}
        try:
            report["hitAt5NotRegressed"] = compare_baseline(report, baseline)
        except ValueError as error:
            parser.error(str(error))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=True, indent=2))
    return 1 if report["failed"] or report.get("hitAt5NotRegressed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
