#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开放获取（OA）论文 PDF 下载器（纯 Python 标准库，无需 pip install）

下载优先级: 检索结果自带的 pdf_url → Unpaywall（按 DOI 找 OA 副本）→ arXiv PDF → DOI 直连
版权说明: 只下载合法开放获取的副本；付费墙论文不绕过，提示走学校图书馆/知网/WoS 手动获取。

用法示例:
  python download_paper.py --from-results results/search_s2.json --index 3
  python download_paper.py --arxiv 1706.03762
  python download_paper.py --doi 10.1038/s41586-020-2649-2 --email you@example.com
  python download_paper.py --url https://arxiv.org/pdf/2401.12345

输出: PDF 保存到 papers/ 目录，打印保存路径。
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def http_get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "literature-review-skill/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_pdf(url, timeout=120):
    """下载并校验确实是 PDF（防止把登录页/落地页存成 .pdf）"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; literature-review-skill/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF-"):
        raise ValueError("返回内容不是 PDF（可能是出版商落地页或需要登录）")
    return data


def safe_filename(name, maxlen=80):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:maxlen].strip() or "paper"


def load_record(args):
    if args.from_results:
        with open(args.from_results, encoding="utf-8") as f:
            records = json.load(f)
        for r in records:
            if r.get("index") == args.index:
                return r
        if 1 <= args.index <= len(records):
            return records[args.index - 1]
        raise SystemExit(f"[错误] index={args.index} 超出范围，共 {len(records)} 条结果")
    if args.arxiv:
        return {"title": f"arXiv {args.arxiv}", "arxiv_id": args.arxiv.strip()}
    if args.doi:
        return {"title": args.doi, "doi": args.doi.strip().removeprefix("https://doi.org/")}
    if args.url:
        return {"title": args.url, "pdf_url": args.url}
    raise SystemExit("[错误] 请指定 --from-results/--arxiv/--doi/--url 之一")


def build_candidates(rec, email):
    """按下载成功率排序的候选 URL 列表"""
    urls = []
    if rec.get("pdf_url"):
        urls.append(rec["pdf_url"])
    if rec.get("doi"):
        try:
            data = http_get_json(f"https://api.unpaywall.org/v2/{rec['doi']}?email={email}")
            locs = [data.get("best_oa_location")] + (data.get("oa_locations") or [])
            for loc in locs:
                if loc and loc.get("url_for_pdf"):
                    if loc["url_for_pdf"] not in urls:
                        urls.append(loc["url_for_pdf"])
                    break
        except Exception:
            pass
        if f"https://doi.org/{rec['doi']}" not in urls:
            urls.append(f"https://doi.org/{rec['doi']}")  # 少数 OA 出版商直连可解析到 PDF
    if rec.get("arxiv_id"):
        u = f"https://arxiv.org/pdf/{rec['arxiv_id']}"
        if u not in urls:
            urls.append(u)
    return urls


def main():
    ap = argparse.ArgumentParser(description="开放获取论文 PDF 下载器")
    ap.add_argument("--from-results", help="search_papers.py 输出的 JSON 文件路径")
    ap.add_argument("--index", type=int, default=1, help="要下载的条目编号（对应结果表中的 # 列）")
    ap.add_argument("--doi", help="按 DOI 下载（经 Unpaywall 查找 OA 副本）")
    ap.add_argument("--arxiv", help="按 arXiv ID 下载，如 1706.03762")
    ap.add_argument("--url", help="直接给定 PDF URL")
    ap.add_argument("--dir", default="papers", help="保存目录，默认 papers/")
    ap.add_argument("--email", default="literature-review@example.com",
                    help="Unpaywall 要求的联系邮箱，建议填真实邮箱")
    args = ap.parse_args()

    rec = load_record(args)
    candidates = build_candidates(rec, args.email)
    if not candidates:
        print("[失败] 该条目没有可用的 PDF 线索（无 pdf_url/DOI/arXiv ID）。")
        sys.exit(1)

    title = rec.get("title") or f"paper-{args.index or ''}"
    base = safe_filename(title)
    os.makedirs(args.dir, exist_ok=True)
    dest = os.path.join(args.dir, base + ".pdf")
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(args.dir, f"{base}-{n}.pdf")
        n += 1

    errors = []
    for url in candidates:
        try:
            data = fetch_pdf(url)
            with open(dest, "wb") as f:
                f.write(data)
            size_mb = len(data) / 1024 / 1024
            print(f"[成功] {title}")
            print(f"       保存至 {os.path.abspath(dest)} ({size_mb:.2f} MB)")
            print(f"       来源 {url}")
            sys.exit(0)
        except Exception as e:
            errors.append(f"{url}  →  {e}")

    print(f"[失败] 未能自动下载：{title}")
    for e in errors:
        print(f"       尝试 {e}")
    doi = rec.get("doi")
    print("\n该论文可能不在开放获取范围内。请通过以下方式手动获取（约 1 分钟）:")
    if doi:
        print(f"  1. 学校图书馆数据库 / https://doi.org/{doi}")
    print("  2. 知网(WoS同理): 校园网内检索标题 → 下载 PDF/CAJ")
    print(f"  3. 将文件放到 {os.path.abspath(args.dir)} 目录，即可继续交给 agent 做解读与对比")
    sys.exit(1)


if __name__ == "__main__":
    main()
