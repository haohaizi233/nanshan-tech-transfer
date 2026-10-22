"""爱马仕 / OpenAI 兼容 AiProvider。密钥与上游 URL 只留在服务端。

企业微信 Bot ID/Secret 不在这里使用：长连接由远端爱马仕 gateway 持有，
本模块只调用 OpenAI 兼容 HTTP（默认 Hermes API Server :8642/v1）。
"""
from __future__ import annotations

import json
import time
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from config import settings
from modules.ai import evaluation
from modules.ai import progress

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


def _chat_stream(messages: list[dict], timeout: float | None = None, on_progress=None) -> str:
    """SSE流式聊天：逐token返回，on_progress(text, token_count)回调实时进度。"""
    if not configured():
        raise AiProviderError("AI_PROVIDER_BASE is not set")
    url = f"{_base()}/chat/completions"
    body = {
        "model": settings.AI_PROVIDER_MODEL or "hermes-agent",
        "temperature": 0.2,
        "messages": messages,
        "stream": True,
    }
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "nanshan-tech-transfer/1.0",
    }
    key = settings.AI_PROVIDER_KEY.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    wait = timeout if timeout is not None else float(settings.AI_PROVIDER_TIMEOUT or 120)
    
    content_parts = []
    token_count = 0
    try:
        with _OPENER.open(req, timeout=wait) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content", "")
                    if piece:
                        content_parts.append(piece)
                        token_count += 1
                        if on_progress:
                            try:
                                on_progress("".join(content_parts), token_count)
                            except Exception:
                                pass
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as exc:
        raise AiProviderError(f"provider HTTP {exc.code}") from None
    except Exception as exc:
        raise AiProviderError(f"stream error: {exc}") from None
    
    result = "".join(content_parts)
    if not result.strip():
        raise AiProviderError("stream returned empty content")
    return result


def _chat(messages: list[dict], timeout: float | None = None) -> str:
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


def complete_json(system: str, user: str, timeout: float | None = None) -> Any:
    content = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=timeout,
    )
    return parse_json_content(content)

def evaluate_achievement(
    snapshot: dict,
    timeout: float | None = None,
    on_stage=None,
    on_delta=None,
) -> dict:
    """多维成果评价 + 评价报告（LLM 生成，评分算法在 evaluation 模块换算）。

    返回 assemble_result 结构：dimensions/totalScore/starScore/rating/
    ratingLabel/conclusion/highlights/report/legacyScores。

    on_stage：实时阶段回调（可选），在 LLM 调用/解析/评分换算三个关键节点
    回传 progress.STAGE_ANALYZING / STAGE_REPORT / STAGE_SCORING，
    由调用方（worker）写入 ai_task.progress_stage。回调异常只记日志，
    不影响评价主流程。

    on_delta：报告原文增量回调（可选），LLM 每产出一段新文字就回传该增量，
    供 SSE 流式总线（modules/ai/eval_stream）实时推给前端做打字机渲染。
    回调异常只记日志，不影响评价主流程。
    """
    def _stage(stage: str) -> None:
        if on_stage is None:
            return
        try:
            on_stage(stage)
        except Exception:
            logger.exception("ai evaluation on_stage callback failed stage=%s", stage)

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
    _stage(progress.STAGE_ANALYZING)  # 阶段2：LLM 调用中
    llm_start = time.time()
    _seen_len = 0  # 已推送给 on_delta 的累计字数（增量 = 累计文本[_seen_len:]）

    def _llm_progress(partial_text, token_count):
        """实时进度回调：增量推给 SSE 流（打字机），每 30 个 token 更新一次阶段信息。"""
        nonlocal _seen_len
        # 增量 = 本次回调相对上次的新增片段（_chat_stream 回传的是累计全文）
        if on_delta is not None and partial_text and len(partial_text) > _seen_len:
            delta = partial_text[_seen_len:]
            _seen_len = len(partial_text)
            try:
                on_delta(delta)
            except Exception:
                logger.exception("ai evaluation on_delta callback failed")
        if token_count % 30 == 0:
            elapsed = int(time.time() - llm_start)
            _stage(f"AI生成中... 已产出{token_count}字 ({elapsed}s)")
    data = parse_json_content(_chat_stream([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], timeout=timeout, on_progress=_llm_progress))
    _stage(progress.STAGE_REPORT)  # 阶段3：解析 LLM 输出
    try:
        normalized = evaluation.normalize_llm_result(data)
    except evaluation.EvaluationDataError as exc:
        raise AiProviderError(f"evaluation JSON invalid: {exc}") from None
    _stage(progress.STAGE_SCORING)  # 阶段4：evaluation 模块评分换算
    return evaluation.assemble_result(normalized)
