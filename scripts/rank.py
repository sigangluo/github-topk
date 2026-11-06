#!/usr/bin/env python3
"""
抓取 GitHub 全站按 star 数排名的前 K 个仓库，写入 data/ranking.json。

    python3 scripts/rank.py            # K 沿用 ranking.json 里上次的值（首次默认 2000）
    python3 scripts/rank.py --k 3000   # 指定 K 值

GitHub 搜索 API 单个查询最多返回 1000 条结果，所以按 star 数区间分片：
首段不设 star 上界；之后的区间保留少量重叠并按仓库名去重，避免抓取期间
star 增长造成漏项。优先用上期快照的 star 门槛作为分片提示；偏离较大时
回退到二分搜索，保证每段结果数不超过 1000。
耗时随 K 和 GitHub 搜索 API 限流情况变化。
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime

from common import GitHub, RANKING_PATH, read_json, write_json

WINDOW_LIMIT = 1000  # 搜索 API 单个查询能翻到的结果上限
WINDOW_TARGET = 950  # 给抓取期间的 star 变化留出余量
WINDOW_OVERLAP = 100  # 相邻 star 区间重叠，避免抓取期间 star 增长造成漏项
DEFAULT_K = 2000


def star_query(lo, hi):
    return f"stars:>={lo}" if hi is None else f"stars:{lo}..{hi}"


def count(gh, lo, hi):
    result = gh.search_repos(star_query(lo, hi), per_page=1)
    if result.get("incomplete_results"):
        raise RuntimeError(f"GitHub 搜索结果不完整：{star_query(lo, hi)}")
    return result["total_count"]


def lowest_bound(gh, hi, unbounded=False, hint=None, minimum=750):
    """选一个足够满、结果数不超过 WINDOW_TARGET 的搜索下界。"""
    upper = None if unbounded else hi
    if hint is not None:
        hint = max(1, min(hint, hi))
        volume = count(gh, hint, upper)
        if minimum <= volume <= WINDOW_TARGET:
            return hint
        if volume > WINDOW_TARGET:
            lo_bad, lo_ok = hint, hi
            if count(gh, hi, upper) > WINDOW_TARGET:
                raise RuntimeError(f"无法按 star 数拆分区间：{star_query(hi, upper)} 超过 {WINDOW_TARGET} 条")
        else:
            lo_ok, lo_bad = hint, 0
            probe = hint
            while probe > 1:
                probe = max(1, probe * 9 // 10)
                if count(gh, probe, upper) <= WINDOW_TARGET:
                    lo_ok = probe
                else:
                    lo_bad = probe
                    break
            if lo_bad == 0:
                return lo_ok
        while lo_ok - lo_bad > 1:
            mid = (lo_ok + lo_bad) // 2
            if count(gh, mid, upper) <= WINDOW_TARGET:
                lo_ok = mid
            else:
                lo_bad = mid
        return lo_ok
    if count(gh, hi, upper) > WINDOW_TARGET:
        raise RuntimeError(f"无法按 star 数拆分区间：{star_query(hi, upper)} 超过 {WINDOW_TARGET} 条")
    lo_ok, lo_bad = hi, 0  # lo_ok 满足条件；lo_bad 不满足（或是哨兵 0）
    # 先指数下探，避免从 1 开始二分浪费请求
    probe = hi
    while probe > 1:
        probe = max(1, probe * 2 // 3)
        if count(gh, probe, upper) <= WINDOW_TARGET:
            lo_ok = probe
        else:
            lo_bad = probe
            break
    if lo_bad == 0:
        return lo_ok
    while lo_ok - lo_bad > 1:
        mid = (lo_ok + lo_bad) // 2
        if count(gh, mid, upper) <= WINDOW_TARGET:
            lo_ok = mid
        else:
            lo_bad = mid
    return lo_ok


def fetch_window(gh, lo, hi):
    query = star_query(lo, hi)
    first = gh.search_repos(query, page=1)
    if first.get("incomplete_results") or first["total_count"] > WINDOW_LIMIT:
        raise RuntimeError(f"GitHub 搜索区间已变化或结果不完整，请重试：{query}")
    items = list(first.get("items", []))
    page_count = min(WINDOW_LIMIT // 100, (first["total_count"] + 99) // 100)
    if page_count <= 1:
        return items
    pages = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(gh.search_repos, query, page=page): page
                for page in range(2, page_count + 1)}
        for job in as_completed(jobs):
            result = job.result()
            if result.get("incomplete_results") or result["total_count"] > WINDOW_LIMIT:
                raise RuntimeError(f"GitHub 搜索区间已变化或结果不完整，请重试：{query}")
            pages[jobs[job]] = result.get("items", [])
    for page in sorted(pages):
        items.extend(pages[page])
    if len(items) < first["total_count"]:
        raise RuntimeError(f"GitHub 搜索分页缺项，请重试：{query}")
    return items


def fetch_top(gh, k, previous=None):
    first = gh.search_repos("stars:>1", per_page=1)
    if first.get("incomplete_results") or not first.get("items"):
        raise RuntimeError("无法取得完整的 GitHub 排名首页")
    top = first["items"][0]["stargazers_count"]
    hi, seen = top, {}
    previous = previous or []
    first_window = True
    while len(seen) < k and hi >= 1:
        upper = None if first_window else hi
        hint = previous[min(len(seen) + 850, len(previous)) - 1]["stars"] if previous else None
        lo = lowest_bound(gh, hi, unbounded=first_window, hint=hint,
                          minimum=min(750, k - len(seen)))
        print(f"区间 {star_query(lo, upper)} ...")
        window = fetch_window(gh, lo, upper)
        if not window:
            raise RuntimeError(f"GitHub 搜索返回空区间：{star_query(lo, upper)}")
        for it in window:
            seen[it["full_name"]] = it["stargazers_count"]
        print(f"  已收集 {len(seen)} 个")
        if lo == 1:
            break
        next_hi = lo + WINDOW_OVERLAP
        if not first_window and next_hi >= hi:
            raise RuntimeError("star 区间未向下推进，请检查搜索结果")
        hi, first_window = next_hi, False
    leaders = gh.search_repos("stars:>1", per_page=20)
    if leaders.get("incomplete_results"):
        raise RuntimeError("GitHub 搜索首页结果不完整")
    missing_leaders = [it["full_name"] for it in leaders["items"] if it["full_name"] not in seen]
    if missing_leaders:
        raise RuntimeError(f"排名漏掉当前前 20 名仓库，请重新抓取：{missing_leaders}")
    ordered = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:k]
    return [{"rank": i + 1, "name": n, "stars": s} for i, (n, s) in enumerate(ordered)]


def main():
    prev = read_json(RANKING_PATH) if RANKING_PATH.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=prev.get("k", DEFAULT_K), help="抓取前 K 名")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("K 必须为正整数")

    repos = fetch_top(GitHub(), args.k, prev.get("repos", []))
    if len(repos) < args.k:
        raise RuntimeError(f"排名抓取不完整：只拿到 {len(repos)} 个，少于 K={args.k}；保留原快照")

    prev_names = {r["name"] for r in prev.get("repos", [])}
    cur_names = {r["name"] for r in repos}
    write_json(RANKING_PATH, {
        "k": args.k,
        "fetched_at": datetime.date.today().isoformat(),
        "source": "GitHub search API, sort=stars desc, 首段无上界并使用重叠 star 区间分片",
        "cutoff_stars": repos[-1]["stars"] if repos else None,
        "repos": repos,
    })
    if prev_names:
        print(f"新进入 Top{args.k}：{len(cur_names - prev_names)} 个；掉出：{len(prev_names - cur_names)} 个")
    print(f"已写入 {RANKING_PATH}（第 {len(repos)} 名 {repos[-1]['stars']} stars）")


if __name__ == "__main__":
    main()
