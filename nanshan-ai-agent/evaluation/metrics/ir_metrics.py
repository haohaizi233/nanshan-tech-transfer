"""AI 检索与匹配评测指标计算（IR + 工程指标）。"""

from __future__ import annotations

import math
from typing import Any


def dcg_at_k(relevances: list[int], k: int) -> float:
    total = 0.0
    for idx, rel in enumerate(relevances[:k]):
        if rel > 0:
            total += (2**rel - 1) / math.log2(idx + 2)
    return total


def ndcg_at_k(predicted_ids: list[int], relevance_map: dict[int, int], k: int) -> float:
    if not relevance_map:
        return 1.0 if not predicted_ids else 0.0
    actual = [relevance_map.get(rid, 0) for rid in predicted_ids[:k]]
    ideal = sorted(relevance_map.values(), reverse=True)[:k]
    idcg = dcg_at_k(ideal, k)
    if idcg == 0.0:
        return 1.0 if not predicted_ids else 0.0
    return dcg_at_k(actual, k) / idcg


def recall_at_k(predicted_ids: list[int], relevant_ids: set[int], k: int) -> float:
    if not relevant_ids:
        return 1.0 if not predicted_ids else 0.0
    hits = len(set(predicted_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def precision_at_k(predicted_ids: list[int], relevant_ids: set[int], k: int) -> float:
    top = predicted_ids[:k]
    if not top:
        return 1.0 if not relevant_ids else 0.0
    hits = len(set(top) & relevant_ids)
    return hits / len(top)


def mrr(predicted_ids: list[int], relevant_ids: set[int]) -> float:
    for idx, rid in enumerate(predicted_ids):
        if rid in relevant_ids:
            return 1.0 / (idx + 1)
    return 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p / 100.0
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    if n == 0:
        return {}
    zero_cases = [r for r in results if r["expect_zero"]]
    non_zero = [r for r in results if not r["expect_zero"]]
    ev_cases = [r for r in results if r.get("evidence_checked")]
    latencies = [r["latency_ms"] for r in results]
    return {
        "totalQueries": n,
        "intentAccuracy": round(sum(1 for r in results if r["intent_ok"]) / n, 4),
        "constraintExtractionAccuracy": round(sum(1 for r in results if r["constraint_ok"]) / n, 4),
        "hardConstraintViolationRate": round(sum(1 for r in results if r["hard_violation"]) / n, 4),
        "recallAt5": round(sum(r["recall_5"] for r in non_zero) / max(1, len(non_zero)), 4),
        "recallAt10": round(sum(r["recall_10"] for r in non_zero) / max(1, len(non_zero)), 4),
        "recallAt20": round(sum(r["recall_20"] for r in non_zero) / max(1, len(non_zero)), 4),
        "precisionAt5": round(sum(r["precision_5"] for r in non_zero) / max(1, len(non_zero)), 4),
        "mrr": round(sum(r["mrr"] for r in non_zero) / max(1, len(non_zero)), 4),
        "ndcgAt5": round(sum(r["ndcg_5"] for r in non_zero) / max(1, len(non_zero)), 4),
        "ndcgAt10": round(sum(r["ndcg_10"] for r in non_zero) / max(1, len(non_zero)), 4),
        "zeroResultAccuracy": round(
            sum(1 for r in zero_cases if r["zero_ok"]) / max(1, len(zero_cases)), 4
        ),
        "groundedEvidenceAccuracy": round(
            sum(1 for r in ev_cases if r["evidence_ok"]) / max(1, len(ev_cases)), 4
        )
        if ev_cases
        else 1.0,
        "p50LatencyMs": round(percentile(latencies, 50), 2),
        "p95LatencyMs": round(percentile(latencies, 95), 2),
        "p99LatencyMs": round(percentile(latencies, 99), 2),
        "llmCallsPerQuery": round(sum(r["llm_calls"] for r in results) / n, 3),
        "degradationRate": round(sum(1 for r in results if r["degraded"]) / n, 4),
    }
