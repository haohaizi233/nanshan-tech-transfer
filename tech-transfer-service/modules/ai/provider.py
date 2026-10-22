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
from modules.ai import evaluation

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
        headers["x-api-key"] = key
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


def complete_json(system: str, user: str, timeout: int | None = None) -> Any:
    content = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=timeout,
    )
    return parse_json_content(content)

def evaluate_achievement(snapshot: dict, timeout: int | None = None) -> dict:
    """多维成果评价 + 评价报告（LLM 生成，评分算法在 evaluation 模块换算）。

    返回 assemble_result 结构：dimensions/totalScore/starScore/rating/
    ratingLabel/conclusion/highlights/report/legacyScores。
    """
    dim_desc = "；".join(
        f"{d['key']}（{d['label']}，权重{d['weight']}：{d['hint']}）"
        for d in evaluation.DIMENSIONS
    )
    system = (
        "你是南山科转通的成果评价专家。只输出 JSON，不要 markdown。\n"
        f"请对成果做多维评价，必须包含六个维度：{dim_desc}。\n"
        '输出格式：{"dimensions":{"innovation":{"score":0-100,"comment":"30字内点评"},'
        '"techMaturity":{...},"marketProspect":{...},"teamStrength":{...},'
        '"cooperation":{...},"riskAssessment":{...}},'
        '"conclusion":"150字内综合评价摘要","highlights":["亮点1","亮点2"],'
        '"report":[{"heading":"小节标题","content":"150-300字详细评价分析"}]}。\n'
        "要求：score 为 0-100 百分制；riskAssessment 分越高代表风险越可控；"
        "report 输出 4-8 个小节，覆盖总体评价、各维度分析与成果转化建议；"
        "所有文字用简体中文，基于给出的成果信息客观评价，信息不足时说明假设。"
    )
    user = json.dumps({"achievement": snapshot}, ensure_ascii=False, default=str)
    data = complete_json(system, user, timeout=timeout)
    try:
        normalized = evaluation.normalize_llm_result(data)
    except evaluation.EvaluationDataError as exc:
        raise AiProviderError(f"evaluation JSON invalid: {exc}") from None
    return evaluation.assemble_result(normalized)
