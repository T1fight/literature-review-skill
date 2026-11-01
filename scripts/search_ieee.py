#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IEEE Xplore 检索与下载工具（纯 Python 标准库，无需 pip install）

原理: 检索走 CrossRef 免费 API（取 DOI 前缀为 10.1109 的记录，即 IEEE 出版物），
     下载用 doi.org 302 反查 arnumber，再经 IEEE PDF 端点（stampPDF）取全文。
前提: 运行机器的网络对 IEEE Xplore 有 IP 授权（校园网/机构订阅，无需登录）。
      若网络无授权，PDF 端点会返回登录页而非 PDF，脚本会如实报错。

用法示例:
  python search_ieee.py "large language model code generation" --limit 10
  python search_ieee.py "federated learning" --year-from 2023 --most-cited
  python search_ieee.py "transformer" --download --index 2     # 检索并下载第 2 篇

输出: 终端 Markdown 结果表 + results/search_ieee.json（与其他来源同 schema，source="ieee"）
"""

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def http_get(url, headers=None, timeout=40, binary=False):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", errors="replace")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def search_crossref_ieee(q, limit, yf, yt, email):
    """CrossRef 检索后只保留 DOI 前缀 10.1109（IEEE）的记录"""
    params = {"query.bibliographic": q, "rows": min(limit * 4, 100), "mailto": email}
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
        doi = it.get("DOI") or ""
        if not doi.lower().startswith("10.1109/"):
            continue
        year = (((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
        authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x)
                   for a in (it.get("author") or [])]
        out.append({
            "source": "ieee",
            "title": clean((it.get("title") or [""])[0]),
            "year": year,
            "venue": clean((it.get("container-title") or [""])[0]),
            "authors": authors[:8],
            "citations": it.get("is-referenced-by-count"),
            "doi": doi,
            "arnumber": None,
            "pdf_url": None,
            "url": f"https://doi.org/{doi}",
            "abstract": clean(it.get("abstract") or ""),
        })
        if len(out) >= limit:
            break
    return out


def doi_to_arnumber(doi):
    """doi.org 302 的 Location 里带 /document/<arnumber>"""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    op = urllib.request.build_opener(NoRedirect)
    op.addheaders = [("User-Agent", UA)]
    try:
        op.open(f"https://doi.org/{doi}", timeout=25)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or ""
        m = re.search(r"document/(\d+)", loc)
        if m:
            return m.group(1)
        raise RuntimeError(f"DOI 未重定向到 IEEE Xplore: {doi} → {loc[:120]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"doi.org 访问失败: {e.reason}") from e
    raise RuntimeError(f"DOI 无重定向（可能非 IEEE 收录）: {doi}")


def download_ieee(rec, out_dir, sleep_s):
    arnumber = rec.get("arnumber") or doi_to_arnumber(rec["doi"])
    rec["arnumber"] = arnumber
    rec["url"] = f"https://ieeexplore.ieee.org/document/{arnumber}"
    time.sleep(sleep_s)

    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}&ref="
    try:
        with op.open(pdf_url, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"IEEE PDF 端点返回 HTTP {e.code}（网络可能无 IEEE 订阅授权）") from e
    if not data.startswith(b"%PDF"):
        raise RuntimeError("IEEE 返回的不是 PDF（通常是登录页：当前网络无 IP 授权，或该文献不在线提供）")

    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", rec["title"]).strip()[:80] or f"ieee-{arnumber}"
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, base + ".pdf")
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(out_dir, f"{base}-{n}.pdf")
        n += 1
    with open(dest, "wb") as f:
        f.write(data)
    return dest, len(data)


def trunc(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def print_table(records):
    print(f"\n共 {len(records)} 条 IEEE Xplore 结果：\n")
    print("| # | 标题 | 年份 | 期刊/会议 | 被引 | 第一作者 | DOI |")
    print("|---|------|------|-----------|------|----------|-----|")
    for r in records:
        first = (r.get("authors") or ["-"])[0]
        cited = r.get("citations")
        print(f"| {r['index']} | {trunc(r['title'], 50)} | {r.get('year') or '-'} | "
              f"{trunc(r.get('venue'), 24) or '-'} | {cited if cited is not None else '-'} | "
              f"{trunc(first, 12)} | {trunc(r['doi'], 28)} |")


def main():
    ap = argparse.ArgumentParser(description="IEEE Xplore 检索与下载（需 IP 授权网络）")
    ap.add_argument("query", help="检索词，如 \"large language model code generation\"")
    ap.add_argument("--limit", type=int, default=10, help="返回条数，默认 10")
    ap.add_argument("--year-from", type=int)
    ap.add_argument("--year-to", type=int)
    ap.add_argument("--most-cited", action="store_true", help="按被引量降序")
    ap.add_argument("--output", default="results/search_ieee.json")
    ap.add_argument("--download", action="store_true", help="下载 --index 指定的论文")
    ap.add_argument("--index", type=int, default=1)
    ap.add_argument("--dir", default="papers")
    ap.add_argument("--email", default="literature-review@example.com", help="CrossRef 礼貌池邮箱")
    ap.add_argument("--sleep", type=float, default=2.0, help="请求间隔秒数，默认 2")
    args = ap.parse_args()

    print(f"经 CrossRef 检索 IEEE 出版物: {args.query}")
    recs = search_crossref_ieee(args.query, args.limit, args.year_from, args.year_to, args.email)
    if args.most_cited:
        recs.sort(key=lambda r: r.get("citations") or 0, reverse=True)
    for i, r in enumerate(recs, 1):
        r["index"] = i
    if not recs:
        print("[提示] 未命中 IEEE 文献，可调整检索词或放宽年份。")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    print_table(recs)
    print(f"\n完整结果已保存 → {args.output}")

    if args.download:
        if not (1 <= args.index <= len(recs)):
            print(f"[错误] index={args.index} 超出范围（1-{len(recs)}）")
            sys.exit(1)
        rec = recs[args.index - 1]
        print(f"\n下载: {rec['title']}")
        try:
            dest, size = download_ieee(rec, args.dir, args.sleep)
            print(f"[成功] {os.path.abspath(dest)} ({size/1024/1024:.2f} MB)")
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(recs, f, ensure_ascii=False, indent=2)
        except RuntimeError as e:
            print(f"[失败] {e}")
            sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        sys.exit(1)
