"""爱马仕 / OpenAI 兼容 AiProvider。密钥与上游 URL 只留在服务端。

企业微信 Bot ID/Secret 不在这里使用：长连接由远端爱马仕 gateway 持有，
本模块只调用 OpenAI 兼容 HTTP（默认 Hermes API Server :8642/v1）。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from config import settings

logger = logging.getLogger("nanshan.error")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class AiProviderError(Exception):
    pass


def configured() -> bool:
    return bool(settings.AI_PROVIDER_BASE.strip())


def _base() -> str:
    return settings.AI_PROVIDER_BASE.strip().rstrip("/")


def parse_json_content(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        raise AiProviderError("empty model content")
    raw = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise AiProviderError("model did not return JSON")


def _chat(messages: list[dict], timeout: int | None = None) -> str:
    if not configured():
        raise AiProviderError("AI_PROVIDER_BASE is not set")
    url = f"{_base()}/chat/completions"
    body = {
        "model": settings.AI_PROVIDER_MODEL or "hermes-agent",
        "temperature": 0.2,
        "messages": messages,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "nanshan-tech-transfer/1.0",
    }
    key = settings.AI_PROVIDER_KEY.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    wait = timeout if timeout is not None else int(settings.AI_PROVIDER_TIMEOUT or 120)
    try:
        with _OPENER.open(req, timeout=wait) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("ai provider http error status=%s", exc.code)
        raise AiProviderError(f"provider HTTP {exc.code}") from None
    except Exception as exc:
        logger.warning("ai provider fetch failed err=%r", exc)
        raise AiProviderError(f"provider call failed: {exc}") from None

    if not isinstance(payload, dict):
        raise AiProviderError("provider returned non-object")
    choices = payload.get("choices") or []
    if not choices:
        raise AiProviderError("provider returned no choices")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str) or not content.strip():
        raise AiProviderError("provider returned empty content")
    return content


def complete_json(system: str, user: str) -> Any:
    content = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    return parse_json_content(content)


def match_demand(snapshot: dict, achievements: list[dict]) -> list[dict]:
    system = (
        "你是南山科转通的技术供需匹配助手。只输出 JSON，不要 markdown。"
        "格式：{\"results\":[{\"achievementId\":1,\"score\":0-100,\"matchReasons\":[\"理由\"]}] }。"
        "只从给定成果中挑选，最多 8 条，按 score 降序。没有合适成果时 results 为空数组。"
    )
    user = json.dumps(
        {"demand": snapshot, "achievements": achievements},
        ensure_ascii=False,
        default=str,
    )
    data = complete_json(system, user)
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise AiProviderError("match JSON missing results[]")
    allowed = {int(item["id"]) for item in achievements if item.get("id") is not None}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ach_id = int(row.get("achievementId") or row.get("achievement_id"))
        except (TypeError, ValueError):
            continue
        if ach_id not in allowed:
            continue
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            continue
        score = max(0.0, min(100.0, round(score, 1)))
        reasons = row.get("matchReasons") or row.get("match_reasons") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        reasons = [str(x).strip() for x in reasons if str(x).strip()][:6]
        out.append({"achievementId": ach_id, "score": score, "matchReasons": reasons})
        if len(out) >= 8:
            break
    out.sort(key=lambda item: (-item["score"], item["achievementId"]))
    return out


def evaluate_achievement(snapshot: dict) -> dict:
    system = (
        "你是南山科转通的成果评估助手。只输出 JSON，不要 markdown。"
        "格式：{\"scores\":{\"techFeature\":0-100,\"applyScope\":0-100,"
        "\"maturity\":0-100,\"cooperation\":0-100},\"totalScore\":0-100,"
        "\"conclusion\":\"摘要\",\"highlights\":[\"要点\"]}。"
        "四维对应技术特点/应用范围/成熟度/合作可行性。"
    )
    user = json.dumps({"achievement": snapshot}, ensure_ascii=False, default=str)
    data = complete_json(system, user)
    if not isinstance(data, dict):
        raise AiProviderError("evaluation JSON is not an object")
    scores_in = data.get("scores") if isinstance(data.get("scores"), dict) else data

    def _score(keys):
        for key in keys:
            if scores_in.get(key) is not None:
                try:
                    return max(0.0, min(100.0, round(float(scores_in[key]), 1)))
                except (TypeError, ValueError):
                    continue
        raise AiProviderError(f"evaluation missing score {keys[0]}")

    scores = {
        "techFeature": _score(("techFeature", "score_tech", "tech")),
        "applyScope": _score(("applyScope", "score_application", "application")),
        "maturity": _score(("maturity", "score_maturity")),
        "cooperation": _score(("cooperation", "score_feasibility", "feasibility")),
    }
    try:
        total = float(data.get("totalScore"))
    except (TypeError, ValueError):
        total = sum(scores.values()) / 4.0
    total = max(0.0, min(100.0, round(total, 1)))
    highlights = data.get("highlights") or data.get("suggestions") or []
    if not isinstance(highlights, list):
        highlights = [str(highlights)]
    highlights = [str(x).strip() for x in highlights if str(x).strip()][:8]
    return {
        "scores": scores,
        "totalScore": total,
        "conclusion": str(data.get("conclusion") or data.get("summary") or "").strip(),
        "highlights": highlights,
    }
