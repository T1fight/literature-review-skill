#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多源学术论文检索工具（纯 Python 标准库，无需 pip install 任何依赖）

支持来源:
  s2        Semantic Scholar Graph API（默认：覆盖面广，含被引量、摘要、OA PDF 链接，免费无需 key）
  openalex  OpenAlex（2.5 亿+ 学术作品元数据，含被引量与 OA 链接，免费无需 key）
  arxiv     arXiv API（预印本，PDF 可直接下载，仅英文）
  crossref  CrossRef（DOI 官方元数据，期刊论文为主）
  wos       Web of Science Starter API（需要 Clarivate API key，见 --api-key）

用法示例:
  python search_papers.py "large language model code generation" --limit 10
  python search_papers.py "federated learning privacy" --source openalex --year-from 2022
  python search_papers.py "transformer attention" --source arxiv --limit 5
  python search_papers.py "graph neural network" --source wos --api-key <KEY>

输出:
  终端打印 Markdown 结果表（快速筛选用），并把含摘要的完整结果写入 --output 的 JSON
  （默认 results/search_<source>.json，供 download_paper.py 下载、以及后续解读对比使用）
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {
    "User-Agent": "literature-review-skill/1.0 (academic course use)",
    "Accept": "application/json",
}

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def http_get(url, headers=None, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # Semantic Scholar 等免费接口会限流（429），等待后重试
            if e.code in (429, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            if e.code == 429:
                raise RuntimeError(
                    f"HTTP 429 限流: {url}\n{detail}\n"
                    "可能是本机 IP 的免费额度被共享用尽（OpenAlex 无 key 时按 IP 共享每日额度，UTC 午夜重置）。\n"
                    "解决办法: 稍后再试 / 换 --source s2 / 到 https://openalex.org 免费申请 API key 后传 --api-key") from e
            raise RuntimeError(f"HTTP {e.code}: {url}\n{detail}") from e
        except urllib.error.URLError as e:
            last_err = e
            if attempt < 2:
                time.sleep(2)
                continue
    raise RuntimeError(f"网络错误: {last_err} ({url})")


def clean(text):
    """压缩空白并去掉 CrossRef 摘要里的 JATS XML 标签"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def record(source, title, year, venue, authors, citations, doi, arxiv_id, pdf_url, url, abstract):
    doi = (doi or "").strip().removeprefix("https://doi.org/")
    return {
        "source": source,
        "title": clean(title),
        "year": year,
        "venue": clean(venue) if isinstance(venue, str) else venue,
        "authors": [clean(a) for a in (authors or []) if a][:8],
        "citations": citations,
        "doi": doi or None,
        "arxiv_id": arxiv_id,
        "pdf_url": pdf_url,
        "url": url,
        "abstract": clean(abstract),
    }


def search_s2(q, limit, yf, yt, email):
    params = {
        "query": q,
        "limit": min(limit, 100),
        "fields": "title,abstract,year,venue,citationCount,authors,externalIds,openAccessPdf,url",
    }
    if yf or yt:
        params["year"] = f"{yf or 1900}-{yt or 3000}"
    data = json.loads(http_get("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)))
    out = []
    for p in data.get("data") or []:
        ext = p.get("externalIds") or {}
        out.append(record(
            "semantic_scholar", p.get("title"), p.get("year"), p.get("venue"),
            [a.get("name") for a in (p.get("authors") or [])],
            p.get("citationCount"), ext.get("DOI"), ext.get("ArXiv"),
            (p.get("openAccessPdf") or {}).get("url"), p.get("url"), p.get("abstract")))
    return out


def openalex_abstract(inv):
    """OpenAlex 摘要为倒排索引，还原为正文"""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def search_openalex(q, limit, yf, yt, email, api_key=None):
    params = {"search": q, "per-page": min(limit, 100), "mailto": email}
    if api_key:
        params["api_key"] = api_key
    filters = []
    if yf and yt:
        filters.append(f"publication_year:{yf}-{yt}")
    elif yf:
        filters.append(f"publication_year:>{yf - 1}")
    elif yt:
        filters.append(f"publication_year:<{yt + 1}")
    if filters:
        params["filter"] = ",".join(filters)
    data = json.loads(http_get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    out = []
    for w in data.get("results") or []:
        src = ((w.get("primary_location") or {}).get("source") or {})
        out.append(record(
            "openalex", w.get("display_name"), w.get("publication_year"), src.get("display_name"),
            [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])],
            w.get("cited_by_count"), w.get("doi"), None,
            (w.get("open_access") or {}).get("oa_url"),
            w.get("doi") or (w.get("ids") or {}).get("openalex"),
            openalex_abstract(w.get("abstract_inverted_index"))))
    return out


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def search_arxiv(q, limit, yf, yt, email):
    params = {"search_query": f'all:"{q}"', "start": 0, "max_results": min(limit, 50)}
    text = http_get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))
    root = ET.fromstring(text)
    out = []
    for e in root.findall("a:entry", ATOM):
        m = re.search(r"abs/([^v]+?)(v\d+)?$", e.findtext("a:id", "", ATOM))
        aid = m.group(1) if m else None
        year = (e.findtext("a:published", "", ATOM) or "")[:4]
        out.append(record(
            "arxiv", e.findtext("a:title", "", ATOM),
            int(year) if year.isdigit() else None, "arXiv preprint",
            [a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)],
            None, None, aid,
            f"https://arxiv.org/pdf/{aid}" if aid else None,
            e.findtext("a:id", "", ATOM), e.findtext("a:summary", "", ATOM)))
    # arXiv API 本身不支持年份过滤，取回后本地过滤
    if yf:
        out = [r for r in out if (r["year"] or 0) >= yf]
    if yt:
        out = [r for r in out if (r["year"] or 0) <= yt]
    return out


def search_crossref(q, limit, yf, yt, email):
    params = {"query.bibliographic": q, "rows": min(limit, 100), "mailto": email}
    filters = []
    if yf:
        filters.append(f"from-pub-date:{yf}-01-01")
    if yt:
        filters.append(f"until-pub-date:{yt}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    data = json.loads(http_get("https://api.crossref.org/works?" + urllib.parse.urlencode(params)))
    out = []
    for it in (data.get("message") or {}).get("items") or []:
        year = (((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
        authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x)
                   for a in (it.get("author") or [])]
        out.append(record(
            "crossref", (it.get("title") or [""])[0], year,
            (it.get("container-title") or [""])[0], authors,
            it.get("is-referenced-by-count"), it.get("DOI"), None,
            None, it.get("URL"), it.get("abstract")))
    return out


def search_wos(q, limit, yf, yt, email, api_key=None):
    import os as _os
    key = api_key or _os.environ.get("WOS_API_KEY")
    if not key:
        raise RuntimeError(
            "使用 --source wos 需要 Clarivate Web of Science Starter API key：\n"
            "  申请入口 https://developer.clarivate.com/ （用学校订阅邮箱注册，选 Starter API 免费档）\n"
            "  然后传 --api-key <KEY> 或设置环境变量 WOS_API_KEY\n"
            "  若暂时没有 key，可先用 --source openalex（元数据覆盖与 WoS 接近）")
    params = {"q": q, "limit": min(limit, 50)}
    data = json.loads(http_get(
        "https://api.clarivate.com/apis/wos-starter/v1/documents?" + urllib.parse.urlencode(params),
        headers={"X-ApiKey": key}))
    hits = ((data.get("hits") or {}).get("hits")) or []
    out = []
    for h in hits:
        d = h.get("data") or h
        pub = d.get("pubInfo") or {}
        journal = pub.get("journal")
        if isinstance(journal, dict):
            journal = journal.get("name")
        year = str(pub.get("issueDate") or "")[:4]
        authors_raw = d.get("authors") or d.get("author") or []
        out.append(record(
            "wos", d.get("title"), int(year) if year.isdigit() else None, journal,
            [a.get("name") for a in authors_raw if isinstance(a, dict)],
            d.get("citedCnt") or d.get("timesCited"), d.get("doi"), None,
            None, f"https://doi.org/{d['doi']}" if d.get("doi") else None,
            d.get("abstract") or d.get("abstractPreview")))
    if yf:
        out = [r for r in out if (r["year"] or 0) >= yf]
    if yt:
        out = [r for r in out if (r["year"] or 0) <= yt]
    return out


def trunc(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def print_table(records):
    print(f"\n共 {len(records)} 条结果：\n")
    print("| # | 标题 | 年份 | 期刊/来源 | 被引 | 第一作者 | DOI / arXiv | OA PDF |")
    print("|---|------|------|-----------|------|----------|-------------|--------|")
    for r in records:
        ident = r.get("doi") or r.get("arxiv_id") or "-"
        first_author = (r.get("authors") or ["-"])[0]
        cited = r.get("citations")
        print(f"| {r['index']} | {trunc(r.get('title'), 55)} | {r.get('year') or '-'} | "
              f"{trunc(r.get('venue'), 22) or '-'} | {cited if cited is not None else '-'} | "
              f"{trunc(first_author, 14)} | {trunc(ident, 28)} | {'有' if r.get('pdf_url') else '无'} |")


def main():
    ap = argparse.ArgumentParser(description="多源学术论文检索", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="示例: python search_papers.py \"federated learning\" --source openalex --year-from 2022")
    ap.add_argument("query", help="检索词，如 \"graph neural network\" 或 \"federated learning\"")
    ap.add_argument("--source", default="s2", choices=["s2", "openalex", "arxiv", "crossref", "wos"],
                    help="检索来源（默认 s2 = Semantic Scholar）")
    ap.add_argument("--limit", type=int, default=10, help="返回条数，默认 10")
    ap.add_argument("--year-from", type=int, help="起始年份（含）")
    ap.add_argument("--year-to", type=int, help="截止年份（含）")
    ap.add_argument("--output", help="结果 JSON 保存路径，默认 results/search_<source>.json")
    ap.add_argument("--most-cited", action="store_true", help="按被引量降序排列（快速找经典文献）")
    ap.add_argument("--api-key", help="API key：wos 必填（也可用环境变量 WOS_API_KEY）；openalex 可选（环境变量 OPENALEX_API_KEY）")
    ap.add_argument("--email", default="literature-review@example.com",
                    help="联系邮箱（OpenAlex/CrossRef 礼貌池建议填真实邮箱）")
    args = ap.parse_args()

    kwargs = dict(q=args.query, limit=args.limit, yf=args.year_from, yt=args.year_to, email=args.email)
    if args.source == "wos":
        results = search_wos(api_key=args.api_key, **kwargs)
    elif args.source == "openalex":
        results = search_openalex(api_key=args.api_key or os.environ.get("OPENALEX_API_KEY"), **kwargs)
    else:
        results = {"s2": search_s2, "arxiv": search_arxiv, "crossref": search_crossref}[args.source](**kwargs)

    if args.most_cited:
        results.sort(key=lambda r: r.get("citations") or 0, reverse=True)
    for i, r in enumerate(results, 1):
        r["index"] = i

    out_path = args.output or f"results/search_{args.source}.json"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print_table(results)
    print(f"\n完整结果（含摘要全文）已保存 → {out_path}")
    print("下一步: 用 download_paper.py --from-results 该文件 --index 编号 下载 PDF；")
    print("        或直接把 JSON 交给 agent 做筛选、文献卡片与对比分析。")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        sys.exit(1)
