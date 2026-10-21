"""真实上游端到端验证脚本（低频，避免触发限流）。"""
import json
import sys
import time

sys.path.insert(0, ".")

from modules.patent.provider import search_raw, search_total_pages  # noqa: E402
from modules.patent.service import search_patents  # noqa: E402
from modules.patent.publication import (  # noqa: E402
    expansion_candidates,
    filter_by_prefix,
    parse_publication_query,
)


def probe(q, num=5, page=0, assignee=""):
    t0 = time.time()
    raw = search_raw(keyword=q, assignee=assignee, page=page, page_size=num)
    dt = (time.time() - t0) * 1000
    rows = raw.get("results") or raw.get("items") or raw.get("list") or []
    print(f"--- upstream q={q!r} num={num} page={page}")
    print(f"    http_ok=True total={raw.get('total')} total_pages={raw.get('total_pages')} rows={len(rows)} {dt:.0f}ms")
    for r in rows[:5]:
        print("      ", r.get("pub_number"), "|", (r.get("title") or "")[:40], "|", r.get("assignee"))
    return raw


def local(q, page=1, size=10, assignee=""):
    t0 = time.time()
    meta = search_patents(q, assignee, page, size)
    dt = (time.time() - t0) * 1000
    print(f"--- local search_patents q={q!r} -> total={meta.get('total')} "
          f"totalPages={meta.get('totalPages')} list={len(meta.get('list') or [])} {dt:.0f}ms")
    for it in (meta.get("list") or [])[:5]:
        print("      ", it.get("publicationNo"), "|", (it.get("title") or "")[:36],
              "|", it.get("assignee"), "| hl=", it.get("highlights"))
    return meta


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "health"):
        print("=== 上游健康探测")
        probe("CN1100866", num=3)

    if which in ("all", "s2"):
        print("\n=== 场景2：截图2 的 CN110086（上游曾误返回 CN1170923C 葡萄酒专利）")
        probe("CN110086", num=5)
        local("CN110086")

    if which in ("all", "s1"):
        print("\n=== 场景1：截图1 的 华为")
        probe("华为", num=3)
        local("华为", size=5)

    if which in ("all", "enum"):
        print("\n=== 枚举路径：CN110086 补位到 7 位")
        cands = expansion_candidates("CN", "110086")
        print("    候选:", cands)
        t0 = time.time()
        merged = []
        import concurrent.futures

        def fn(c):
            try:
                raw = search_raw(keyword=c, assignee="", page=0, page_size=20)
                return raw.get("results") or raw.get("items") or raw.get("list") or []
            except Exception as exc:
                print("    ERR", c, exc)
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            for rows in pool.map(fn, cands):
                merged.extend(rows)
        dt = (time.time() - t0) * 1000
        hits = filter_by_prefix(merged, "CN", "110086", "")
        print(f"    合并 {len(merged)} 行 -> 严格前缀命中 {len(hits)} 条, {dt:.0f}ms")
        for h in hits[:10]:
            print("      ", h.get("pub_number"), "|", (h.get("title") or "")[:40])

    if which in ("all", "enum9"):
        print("\n=== 枚举路径：CN1100866 补位到 9 位（10 候选）")
        cands = expansion_candidates("CN", "1100866")
        print("    候选:", cands)
        t0 = time.time()
        merged = []
        import concurrent.futures

        def fn2(c):
            try:
                raw = search_raw(keyword=c, assignee="", page=0, page_size=20)
                return raw.get("results") or raw.get("items") or raw.get("list") or []
            except Exception as exc:
                print("    ERR", c, exc)
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            for rows in pool.map(fn2, cands):
                merged.extend(rows)
        dt = (time.time() - t0) * 1000
        hits = filter_by_prefix(merged, "CN", "1100866", "")
        print(f"    合并 {len(merged)} 行 -> 严格前缀命中 {len(hits)} 条, {dt:.0f}ms")
        for h in hits[:10]:
            print("      ", h.get("pub_number"), "|", (h.get("title") or "")[:40])

    if which == "raw":
        print(json.dumps(sys.argv[2:], ensure_ascii=False))
