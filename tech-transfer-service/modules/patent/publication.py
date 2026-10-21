"""公开号形态识别与前缀检索兜底。

背景（真实上游 43.138.138.200:8081 抓包实测，非推测）：

上游 ``/patent_search`` 的 ``q`` 参数是 Google Patents 的全文检索。
它**只在数字段长度恰好为 7 位或 9 位时**才把查询当作公开号做前缀匹配，
其余长度一律退化为全文检索，于是返回语义无关的结果：

===================  ==========================  =======================
查询                  上游行为                    实测结果
===================  ==========================  =======================
CN1100866 (7 位)      前缀匹配                    CN1100866A / CN1100866C
CN110086609 (9 位)    前缀匹配                    CN110086609B
CN110086 (6 位)       **退化为全文检索**          CN1170923C（葡萄酒专利）
CN11008660 (8 位)     **退化为全文检索**          0 条
CN113077 (6 位)       **退化为全文检索**          CN1121865C（无关专利）
===================  ==========================  =======================

原因是中国公开号存在两套号段体系：早期 7 位（CN1100866）、
2003 年后 9 位（CN110086609）。上游只对这两种**完整**号段建了索引，
中间长度的输入被当成普通词去做全文匹配。

本模块提供本地兜底：
1. 识别查询是否为公开号形态（国家码 + 数字段）；
2. 把长度不足的号段**枚举补齐**到上游可识别的长度；
3. 对返回结果做**严格前缀过滤**，杜绝把全文命中的无关专利当成匹配结果。

实测（真实上游）：6 位 CN 前缀枚举 10 个 7 位候选，
10 路并发耗时约 1.2s，严格前缀过滤后命中 20 条真实专利；
而直接透传只会得到 1 条误报。

上游限流约束（实测，决定了枚举规模的上限）：
上游内部转发 Google Patents，吞吐约 2.8~7.5 req/s。
并发 20~40 压测 100~200 次后，上游会持续返回
``{"detail":"search failed: HTTP Error 503: "}``（自身存活，
是它的后端被打挂/限流），需等待其自行恢复。

由此得到两条工程约束：
- 100 候选（7 位→9 位补 2 位）16 并发实测 12.5s，同步接口不可接受；
- 1000 候选（6 位→9 位补 3 位）同理不可行。

所以枚举只做**补 1 位**（10 个候选，约 1.2s）；补 3 位及以上直接放弃枚举，
交给上游按其能识别的长度处理，并在本地做严格前缀过滤兜底。

其他上游实测结论（避免后人重复踩坑）：
- ``num`` 上限 100，超出返回 HTTP 422；
- ``total_pages`` 封顶 100（page=100 起返回空列表）；
- ``total`` 是 Google Patents 的**估算值**，按 125 分桶，不是精确命中数；
- ``PN=`` / ``publication:`` / ``pub:`` / ``intext:`` / ``intitle:`` 等
  公开号字段语法上游均返回 0 条，不可用；
- 其他国家（US/EP/WO）前缀匹配正常，不需要枚举补齐。
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import time
from collections.abc import Callable

logger = logging.getLogger("nanshan.error")

# 国家/地区码 + 数字段，数字段 3~12 位。允许尾随的 kind code（A/B/C/U…）。
_PUB_NO_QUERY_RE = re.compile(
    r"^(?P<country>[A-Za-z]{2})(?P<number>\d{3,12})(?P<kind>[A-Za-z])?$"
)

# 上游可识别为公开号前缀的号段长度。
#   7 位 → 早期中国公开号（如 CN1100866A）
#   9 位 → 2003 年后中国公开号（如 CN110086609B）
# 其余国家的号段长度不固定（US 7~8 位、EP 7 位、WO 10 位…），
# 这些在上游能正常前缀匹配，不做枚举。
_CN_BODY_LENGTHS = (7, 9)

# 枚举补齐时的并发度。上游单次约 200~400ms，10 路并发实测约 1.2s。
_ENUM_WORKERS = 10

# 单次检索最多向上游发出的候选数。9 位号段需要补 3 位（1000 种），
# 代价过高；这种输入直接交给上游按 9 位号段处理，不做枚举。
_ENUM_MAX_CANDIDATES = 10


def parse_publication_query(keyword: str) -> tuple[str, str, str] | None:
    """把查询解析为 (国家码大写, 数字段, kind code 小写)。

    不是公开号形态时返回 ``None``。
    """
    text = (keyword or "").strip()
    if not text:
        return None
    # 去掉常见分隔符：CN 1100866 / CN-1100866 / CN_1100866
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    match = _PUB_NO_QUERY_RE.match(text)
    if not match:
        return None
    country = match.group("country").upper()
    number = match.group("number")
    kind = (match.group("kind") or "").lower()
    return country, number, kind


def is_publication_query(keyword: str) -> bool:
    """查询是否为公开号形态。"""
    return parse_publication_query(keyword) is not None


def needs_prefix_expansion(country: str, number: str) -> bool:
    """该号段长度是否不在上游可识别范围内，需要枚举补齐。"""
    if country != "CN":
        return False
    return len(number) not in _CN_BODY_LENGTHS


def expansion_candidates(country: str, number: str, kind: str = "") -> list[str]:
    """枚举补齐候选号（可直接作为上游 ``q`` 的完整查询串）。

    6 位号段可补齐到 7 位（10 种），8 位号段可补齐到 9 位（10 种），
    代价可控。4 位及以下、或需要补 3 位以上时返回空列表——
    候选数会爆炸，不适合在一次请求里做。

    注意候选必须带国家码：上游只认 ``CN1100860`` 这种完整公开号形态，
    裸数字 ``1100860`` 会被当成普通词做全文检索（实测返回 0 条）。
    """
    if country != "CN":
        return []
    length = len(number)
    targets = [n for n in _CN_BODY_LENGTHS if n > length]
    if not targets:
        return []
    target = min(targets)
    missing = target - length
    if missing < 1 or 10 ** missing > _ENUM_MAX_CANDIDATES:
        return []
    prefix = f"{country.upper()}{number}"
    tail = (kind or "").upper()
    return [prefix + str(i).zfill(missing) + tail for i in range(10 ** missing)]


def _prefix_of(country: str, number: str, kind: str) -> str:
    """构造用于前缀比对的大写前缀。"""
    return f"{country.upper()}{number}"


def matches_prefix(publication_no: str, country: str, number: str, kind: str) -> bool:
    """公开号是否满足查询前缀。

    kind code 存在时要求尾部 kind 一致（CN1100866A 与 CN1100866C 是两件不同专利）。
    """
    pub = (publication_no or "").strip().upper()
    if not pub:
        return False
    head = _prefix_of(country, number, kind)
    if not pub.startswith(head):
        return False
    if kind:
        return pub == head + kind.upper()
    return True


def filter_by_prefix(
    rows: list[dict],
    country: str,
    number: str,
    kind: str,
) -> list[dict]:
    """对上游返回的原始行做严格前缀过滤。

    没有这层过滤时，全文检索命中的无关专利会被当成"匹配结果"返回给用户
    （实测 CN110086 会返回葡萄酒专利 CN1170923C）。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pub = str(row.get("pub_number") or row.get("number") or "").strip()
        if not matches_prefix(pub, country, number, kind):
            continue
        key = pub.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def search_publication_prefix(
    keyword: str,
    search_fn: Callable[[str, int], list[dict]],
    *,
    num: int = 100,
    max_workers: int = _ENUM_WORKERS,
    timeout: float | None = None,
) -> tuple[list[dict], bool]:
    """按公开号前缀检索。

    返回 (命中行列表, 是否走了枚举路径)。

    枚举路径：对每个候选号段并发调用 ``search_fn(candidate, num)``，
    合并后严格前缀过滤。非枚举路径：直接把原查询交给 ``search_fn``，
    再按前缀过滤——这样即便上游退化成全文检索，也不会把无关专利当成匹配结果。

    ``num`` 是每个候选向上游要的条数（上游上限 100）。
    枚举路径下结果的总数会小于真实总量（每个候选只取首页），
    因此调用方应把返回列表当作"已知的全部命中"在本地分页。

    ``timeout`` 是整轮枚举的时间预算（秒）。上游实测单次 200~400ms，
    但上游被限流时会退化到十几秒（实测冷启动一次 22 秒），
    同步接口不能被拖死：超预算后放弃剩余候选，用已拿到的结果返回。
    单个候选失败（超时/上游报错）只丢弃该候选，不影响其余候选。
    """
    parsed = parse_publication_query(keyword)
    if parsed is None:
        return [], False
    country, number, kind = parsed

    candidates = expansion_candidates(country, number, kind)
    if not candidates:
        rows = search_fn(f"{country}{number}{kind}".upper(), num)
        return filter_by_prefix(rows, country, number, kind), False

    merged: list[dict] = []
    deadline = time.monotonic() + timeout if timeout else None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(search_fn, c, num): c for c in candidates}
        for future in concurrent.futures.as_completed(futures, timeout=timeout):
            try:
                merged.extend(future.result() or [])
            except Exception:  # noqa: BLE001 —— 单个候选失败不影响其余候选
                logger.warning(
                    "patent publication candidate failed query=%s",
                    futures[future],
                    exc_info=True,
                )
    except TimeoutError:
        # 超出时间预算：放弃剩余候选，用已拿到的结果返回。
        # 不能走 ThreadPoolExecutor 的默认 shutdown(wait=True)——那会等所有
        # 卡住的请求结束，预算就形同虚设。
        logger.warning(
            "patent publication enumeration exceeded budget=%.1fs candidates=%d",
            timeout or 0.0,
            len(candidates),
        )
    finally:
        # wait=False：不让已经卡住的上游请求拖住返回。
        # 上游请求本身有 PATENT_PROVIDER_TIMEOUT 兜底，不会永久泄漏线程。
        pool.shutdown(wait=False, cancel_futures=True)

    hits = filter_by_prefix(merged, country, number, kind)
    # 并发合并后顺序取决于完成顺序，排序保证结果稳定可复现。
    hits.sort(key=lambda row: str(row.get("pub_number") or row.get("number") or ""))
    return hits, True
