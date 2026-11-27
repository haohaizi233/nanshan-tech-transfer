"""可复现 AI 检索评测运行器（离线语料库 + 真实路由/检索/重排管线）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from app import main as agent_main  # noqa: E402
from app.schemas import ChatRequest, RouteResult  # noqa: E402
from app.services import retrieval, taxonomy  # noqa: E402
from app.services.achievement_service import get_allowed_maturity_levels  # noqa: E402
from evaluation.metrics.ir_metrics import (  # noqa: E402
    aggregate_metrics,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _corpus_search_achievements(corpus: list[dict], **kwargs) -> list[dict]:
    keywords = kwargs.get("keywords") or []
    min_price = kwargs.get("min_price_wan")
    max_price = kwargs.get("max_price_wan")
    min_maturity = kwargs.get("min_maturity")
    target_ids = kwargs.get("target_ids")
    exclude_owner = kwargs.get("exclude_owner_user_id")

    plan = retrieval.build_term_plan(keywords, taxonomy.KEYWORD_EXPANSIONS)
    allowed_mat = set(get_allowed_maturity_levels(min_maturity))
    matched: list[dict] = []
    for item in corpus:
        if item.get("status") != "published" or item.get("deleted_at") is not None:
            continue
        if target_ids is not None and item.get("id") not in target_ids:
            continue
        if exclude_owner is not None and item.get("owner_user_id") == exclude_owner:
            continue
        if allowed_mat and item.get("maturity_level") not in allowed_mat:
            continue
        if not taxonomy.amount_band_matches(min_price, max_price, item.get("price_min_wan"), item.get("price_max_wan")):
            continue
        text_blob = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("source_org_name") or ""),
                str(item.get("tech_intro") or ""),
                " ".join(item.get("application_fields") or []),
                " ".join(item.get("innovation_points") or []),
            ]
        ).lower()
        if plan.all_terms and not any(t.lower() in text_blob for t in plan.all_terms):
            continue
        matched.append(dict(item))
    scores = retrieval.score_items("achievement", matched, plan)
    paired = sorted(zip(matched, scores), key=lambda x: (x[1], str(x[0].get("created_at") or "")), reverse=True)
    return [row for row, _ in paired[:50]]


def _corpus_search_demands(corpus: list[dict], **kwargs) -> list[dict]:
    keywords = kwargs.get("keywords") or []
    region = kwargs.get("region")
    min_budget = kwargs.get("min_budget_wan")
    max_budget = kwargs.get("max_budget_wan")
    coop_modes = kwargs.get("coop_modes") or []
    target_ids = kwargs.get("target_ids")
    exclude_owner = kwargs.get("exclude_owner_user_id")

    plan = retrieval.build_term_plan(keywords, taxonomy.KEYWORD_EXPANSIONS)
    matched: list[dict] = []
    for item in corpus:
        if item.get("status") != "published" or item.get("deleted_at") is not None:
            continue
        if target_ids is not None and item.get("id") not in target_ids:
            continue
        if exclude_owner is not None and item.get("owner_user_id") == exclude_owner:
            continue
        if region and region.lower() not in str(item.get("region") or "").lower():
            continue
        if not taxonomy.amount_band_matches(
            min_budget, max_budget, item.get("budget_min_wan"), item.get("budget_max_wan")
        ):
            continue
        if coop_modes:
            coop_text = " ".join(item.get("coop_mode") or []).lower()
            ok_coop = False
            for m in coop_modes:
                if any(sp.lower() in coop_text for sp in taxonomy.resolve_coop_modes(m)):
                    ok_coop = True
                    break
            if not ok_coop:
                continue
        text_blob = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("org_name_snapshot") or ""),
                str(item.get("description") or ""),
                str(item.get("region") or ""),
                " ".join(item.get("coop_mode") or []),
            ]
        ).lower()
        if plan.all_terms and not any(t.lower() in text_blob for t in plan.all_terms):
            continue
        matched.append(dict(item))
    scores = retrieval.score_items("demand", matched, plan)
    paired = sorted(zip(matched, scores), key=lambda x: (x[1], str(x[0].get("created_at") or "")), reverse=True)
    return [row for row, _ in paired[:50]]


def run_dataset(dataset_path: Path, corpus_path: Path) -> dict[str, Any]:
    dataset = _load_json(dataset_path)
    corpus = _load_json(corpus_path)
    achievements = corpus["achievements"]
    demands = corpus["demands"]

    per_query: list[dict[str, Any]] = []
    for entry in dataset["queries"]:
        q = entry["query"]
        llm_calls = 0

        def _fake_router(messages, **_kwargs):
            nonlocal llm_calls
            llm_calls += 1
            intent = entry["intent"]
            kw = [w for w in taxonomy.KEYWORD_EXPANSIONS if w in q]
            if not kw:
                kw = [q[:12]]
            return json.dumps({"intent": intent, "keywords": kw}, ensure_ascii=False)

        def _fake_rerank(messages, **_kwargs):
            nonlocal llm_calls
            llm_calls += 1
            user_obj = json.loads(messages[1]["content"])
            cands = user_obj.get("candidates", [])
            return json.dumps({"results": [{"id": c["id"]} for c in cands[:10]]}, ensure_ascii=False)

        t0 = time.perf_counter()
        with (
            patch("app.router.chat_completion", side_effect=_fake_router),
            patch("app.reranker.chat_completion", side_effect=_fake_rerank),
            patch("app.main.search_achievements", side_effect=lambda **kw: _corpus_search_achievements(achievements, **kw)),
            patch("app.main.search_demands", side_effect=lambda **kw: _corpus_search_demands(demands, **kw)),
            patch("app.main.facts_for", return_value={"total": len(achievements), "unpriced": 1, "priced": 6}),
        ):
            req = ChatRequest(message=q)
            resp = agent_main._process_ai_chat(req)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        predicted_ids = [c["id"] for c in resp.data if isinstance(c, dict) and c.get("id") is not None]
        rel_map = {r["recordId"]: r["grade"] for r in entry.get("relevance", [])}
        rel_ids = {rid for rid, g in rel_map.items() if g >= 1}
        forbidden = set(entry.get("forbiddenRecords", []))
        hard_violation = bool(set(predicted_ids) & forbidden)

        # Check hard constraints on returned cards
        hc = entry.get("hardConstraints", {})
        if hc and not hard_violation:
            by_id = {x["id"]: x for x in achievements + demands}
            for pid in predicted_ids:
                rec = by_id.get(pid)
                if not rec:
                    continue
                if resp.intent == "search_achievement":
                    r = RouteResult(
                        intent="search_achievement",
                        min_maturity=hc.get("min_maturity"),
                        min_price_wan=hc.get("min_price_wan"),
                        max_price_wan=hc.get("max_price_wan"),
                    )
                    if not agent_main.record_matches(rec, r):
                        hard_violation = True
                elif resp.intent == "search_demand":
                    r = RouteResult(
                        intent="search_demand",
                        region=hc.get("region"),
                        min_budget_wan=hc.get("min_budget_wan"),
                        max_budget_wan=hc.get("max_budget_wan"),
                        coop_modes=hc.get("coop_modes", []),
                    )
                    if not agent_main.record_matches(rec, r):
                        hard_violation = True

        expect_zero = bool(entry.get("expectZero", False))
        intent_ok = resp.intent == entry["intent"]
        constraint_ok = not hard_violation
        if hc.get("min_maturity") and resp.queryPlan:
            constraint_ok = constraint_ok and resp.queryPlan.get("min_maturity") == hc["min_maturity"]
        if hc.get("region") and resp.queryPlan:
            constraint_ok = constraint_ok and hc["region"] in str(resp.queryPlan.get("region") or "")

        per_query.append(
            {
                "queryId": entry["queryId"],
                "intent_ok": intent_ok,
                "constraint_ok": constraint_ok,
                "hard_violation": hard_violation,
                "recall_5": recall_at_k(predicted_ids, rel_ids, 5),
                "recall_10": recall_at_k(predicted_ids, rel_ids, 10),
                "recall_20": recall_at_k(predicted_ids, rel_ids, 20),
                "precision_5": precision_at_k(predicted_ids, rel_ids, 5),
                "mrr": mrr(predicted_ids, rel_ids),
                "ndcg_5": ndcg_at_k(predicted_ids, rel_map, 5),
                "ndcg_10": ndcg_at_k(predicted_ids, rel_map, 10),
                "expect_zero": expect_zero,
                "zero_ok": len(predicted_ids) == 0 if expect_zero else True,
                "latency_ms": latency_ms,
                "llm_calls": llm_calls,
                "degraded": False,
                "predictedIds": predicted_ids,
            }
        )

    summary = aggregate_metrics(per_query)
    return {"datasetVersion": dataset["datasetVersion"], "summary": summary, "queries": per_query}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(AGENT_ROOT / "evaluation/datasets/v1_test.json"))
    parser.add_argument("--corpus", default=str(AGENT_ROOT / "evaluation/datasets/corpus_v1.json"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = run_dataset(Path(args.dataset), Path(args.corpus))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
