#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知网(CNKI)检索与下载工具（纯 Python 标准库，无需 pip install）

原理: 知网没有公开 API，本脚本复刻 kns.cnki.net 新版前端(kns8s)的内部检索接口
     （POST /kns8s/brief/grid，返回结果表 HTML 片段），用浏览器式会话请求。
前提: 运行本脚本的机器所在网络可以直连知网（校园网/机构 IP 授权）。
礼貌性: 默认请求间隔 --sleep 秒；请勿加大 pageSize 或循环抓取，教学用途、低频调用。

用法示例:
  python search_cnki.py "大语言模型 代码生成" --limit 10        # 简单词自动拼成 SU 检索式
  python search_cnki.py "SU='联邦学习' AND SU='隐私保护'" --expert   # 直接用专业检索式
  python search_cnki.py "大语言模型" --db thesis --limit 20    # 限硕博学位论文库
  python search_cnki.py "大语言模型" --download --index 2      # 检索并下载第 2 篇 PDF
  python search_cnki.py --selftest                             # 离线自测解析器

输出: 终端 Markdown 结果表 + results/search_cnki.json（与公开数据源脚本同 schema，
     source="cnki"），可直接交给 agent 做文献卡片与对比分析。
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
from html.parser import HTMLParser

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HOME = "https://kns.cnki.net/kns8s/"
GRID = "https://kns.cnki.net/kns8s/brief/grid"

DB_RESOURCE = {"all": "CROSSDB", "journal": "CJFD", "thesis": "CDMD"}
SORT_FIELD = {"relevant": "", "date": "PTIME", "cited": "CITED", "download": "DOWNLOAD"}


class CnkiBlockedError(RuntimeError):
    """知网风控拦截（滑块验证/403），需要换路线"""


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def new_session():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA),
                     ("Accept", "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"),
                     ("Accept-Language", "zh-CN,zh;q=0.9")]
    return op


def warmup(op):
    """访问检索首页建立会话；被风控时给出明确指引"""
    try:
        resp = op.open(HOME, timeout=30)
        url = resp.geturl()
        if "/verify/" in url:
            raise CnkiBlockedError(
                "知网把当前网络出口导去了滑块验证页（常见于机房/代理/境外 IP）。\n"
                "两条出路：\n"
                "  1) 在本机浏览器打开 https://kns.cnki.net 完成一次滑块验证，1-2 分钟内重试本脚本；\n"
                "  2) 换浏览器自动化/手动路线（见 SKILL.md「知网检索流程」Route B/C）。")
    except urllib.error.HTTPError as e:
        if e.code in (403, 412):
            raise CnkiBlockedError(f"知网返回 HTTP {e.code}（风控拦截）。请走浏览器路线，或完成一次滑块验证后重试。") from e
        raise RuntimeError(f"访问知网首页失败 HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接知网（检查网络是否可直连 kns.cnki.net）：{e.reason}") from e


def build_queryjson(expr, db):
    return {
        "Platform": "", "Resource": DB_RESOURCE[db], "Classid": "WD0FTY92", "Products": "",
        "QNode": {"QGroup": [{"Key": "Subject", "Title": "", "Logic": 0,
                              "Items": [{"Key": "Expert", "Title": "", "Logic": 0, "Field": "EXPERT",
                                         "Operator": 0, "Value": expr, "Value2": ""}],
                              "ChildItems": []}]},
        "ExScope": "1", "SearchType": 4, "Rlang": "CHINESE", "KuaKuCode": "",
    }


def grid_search(op, expr, db, page, size, sort):
    data = urllib.parse.urlencode({
        "boolSearch": "true",
        "QueryJson": json.dumps(build_queryjson(expr, db), ensure_ascii=False),
        "pageNumber": str(page), "pageSize": str(min(size, 50)),
        "sortField": SORT_FIELD[sort], "sortType": "desc",
        "dstyle": "listmode", "boolSortSearch": "false",
        "userLang": "CH", "etype": "", "topic": "", "searchFrom": "",
    }).encode("utf-8")
    req = urllib.request.Request(GRID, data=data, headers={"Referer": HOME,
                                                           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    try:
        resp = op.open(req, timeout=40)
        body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 412):
            raise CnkiBlockedError(f"检索请求被知网拒绝（HTTP {e.code}，风控）。请走浏览器路线或稍后重试。") from e
        raise RuntimeError(f"检索失败 HTTP {e.code}") from e
    if "/verify/" in body or "captchaType" in body[:2000]:
        raise CnkiBlockedError("检索响应被导向验证码页面。请走浏览器路线，或稍后重试。")
    return body


class GridParser(HTMLParser):
    """解析 brief/grid 返回的结果表：单元格按 class 定位（name/author/source/date/quote/download）"""
    FIELDS = ("name", "author", "source", "date", "quote", "download")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cur, self.cell, self.buf, self.href = [], None, None, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.cur = {}
        elif tag == "td" and self.cur is not None:
            cls = (a.get("class") or "").split()
            self.cell = next((c for c in cls if c in self.FIELDS), None)
            self.buf = []
        elif tag == "a" and self.cell == "name" and a.get("href"):
            self.href = a["href"]

    def handle_data(self, data):
        if self.cell is not None and data.strip():
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            text = clean("".join(self.buf))
            if self.cell == "name":
                self.cur["title"] = text
                self.cur["url"] = self.href or ""
            elif self.cell == "author":
                self.cur["authors"] = [x for x in re.split(r"[;,，；\s]+", text) if x]
            elif self.cell == "source":
                self.cur["venue"] = text
            elif self.cell == "date":
                self.cur["date"] = text
            elif self.cell == "quote":
                self.cur["citations"] = _int(text)
            elif self.cell == "download":
                self.cur["downloads"] = _int(text)
            self.cell, self.buf = None, []
        elif tag == "tr" and self.cur is not None:
            if self.cur.get("title"):
                self.rows.append(self.cur)
            self.cur, self.href = None, None


def _int(text):
    m = re.search(r"\d+", text.replace(",", ""))
    return int(m.group()) if m else None


def parse_grid(html_text):
    p = GridParser()
    try:
        p.feed(html_text)
    except Exception:
        pass
    if p.rows:
        return p.rows
    # 兜底：按行切分 + 正则抽标题链接
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        m = re.search(r'class="name"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', tr, re.S | re.I)
        if not m:
            continue
        rows.append({"title": clean(m.group(2)), "url": m.group(1)})
    return rows


def to_record(i, row):
    url = row.get("url") or ""
    if url.startswith("//"):
        url = "https:" + url
    year = None
    m = re.search(r"(19|20)\d{2}", row.get("date") or "")
    if m:
        year = int(m.group(0))
    return {
        "source": "cnki", "index": i,
        "title": row.get("title", ""),
        "year": year,
        "venue": row.get("venue"),
        "authors": row.get("authors", []),
        "citations": row.get("citations"),
        "downloads": row.get("downloads"),
        "doi": None, "arxiv_id": None, "pdf_url": None,
        "url": url,
        "abstract": "",
    }


def print_table(records):
    print(f"\n共 {len(records)} 条知网结果：\n")
    print("| # | 标题 | 年份 | 期刊/来源 | 被引 | 下载 | 第一作者 |")
    print("|---|------|------|-----------|------|------|----------|")
    for r in records:
        first = (r.get("authors") or ["-"])[0]
        print(f"| {r['index']} | {trunc(r['title'], 48)} | {r.get('year') or '-'} | "
              f"{trunc(r.get('venue') or '-', 20)} | {r.get('citations') if r.get('citations') is not None else '-'} | "
              f"{r.get('downloads') if r.get('downloads') is not None else '-'} | {trunc(first, 10)} |")


def trunc(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def absolutize(href, base):
    if href.startswith("//"):
        href = "https:" + href
    return urllib.parse.urljoin(base, href)


def fetch_detail(op, rec, sleep_s):
    """抓详情页：补摘要/关键词，并收集下载候选链接"""
    if not rec.get("url"):
        return []
    time.sleep(sleep_s)
    try:
        resp = op.open(urllib.request.Request(rec["url"], headers={"Referer": HOME}), timeout=40)
        html_text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[警告] 详情页获取失败: {e}")
        return []

    m = re.search(r'id="ChDivSummary"[^>]*>(.*?)</div>', html_text, re.S)
    if m and not rec.get("abstract"):
        rec["abstract"] = clean(m.group(1))[:2000]
    m = re.search(r'【关键词】[：:]*</b>?([^<【]+)', html_text)
    if m:
        rec["keywords"] = clean(m.group(1))

    cands = []
    for href in re.findall(r'href="([^"]*(?:download|pdf|caj)[^"]*)"', html_text, re.I):
        u = absolutize(href, rec["url"])
        if u not in cands and "javascript" not in u:
            cands.append(u)
    return cands


def safe_filename(name, maxlen=80):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:maxlen].strip() or "paper"


def download_cnki(op, rec, out_dir, sleep_s):
    print(f"\n尝试下载第 {rec['index']} 篇: {rec['title']}")
    print(f"详情页: {rec['url']}")
    cands = fetch_detail(op, rec, sleep_s)
    if not cands:
        print("[失败] 详情页未发现下载入口。请在浏览器打开详情页下载（校园网内一般可直下 PDF），"
              f"文件放入 {os.path.abspath(out_dir)} 后继续解读流程。")
        return False

    base = safe_filename(rec["title"])
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    for url in cands[:6]:
        time.sleep(min(sleep_s, 2))
        try:
            resp = op.open(urllib.request.Request(url, headers={"Referer": rec["url"]}), timeout=120)
            data = resp.read()
            if data.startswith(b"%PDF-"):
                dest = os.path.join(out_dir, base + ".pdf")
                with open(dest, "wb") as f:
                    f.write(data)
                print(f"[成功] PDF 已保存 → {os.path.abspath(dest)} ({len(data)/1024/1024:.2f} MB)")
                return True
            head = data[:8192].decode("utf-8", errors="replace")
            if re.search(r"\.caj|application/x-caj", head, re.I) or url.lower().find("caj") >= 0:
                dest = os.path.join(out_dir, base + ".caj")
                with open(dest, "wb") as f:
                    f.write(data)
                print(f"[部分成功] 下载到 CAJ 格式（需 CAJViewer 打开）→ {os.path.abspath(dest)}")
                print("          建议在浏览器详情页选择『PDF 下载』重新获取 PDF 版本。")
                return True
            errors.append(url)
        except Exception as e:
            errors.append(f"{url} → {e}")

    print("[失败] 自动下载未成功。请在浏览器打开上面的详情页手动下载（校园网内可直接下载），")
    print(f"       文件放入 {os.path.abspath(out_dir)} 目录后，解读与对比流程照常进行。")
    return False


FIXTURE = """
<table class="result-table-list"><thead></thead><tbody>
<tr>
  <td class="seq">1</td>
  <td class="name"><span class="row-first"><input type="checkbox"><a href="//kns.cnki.net/kcms2/article/abstract?v=abc123&amp;dbcode=CJFD&amp;filename=JSJB202403001" target="_blank">基于<font color="red">大语言模型</font>的代码生成方法研究</a></span></td>
  <td class="author">张三;李四;王五</td>
  <td class="source"><a href="//navi.cnki.net">计算机学报</a></td>
  <td class="date">2024-03-15</td>
  <td class="quote">66</td>
  <td class="download">1,234</td>
</tr>
<tr>
  <td class="seq">2</td>
  <td class="name"><span class="row-first"><a href="//kns.cnki.net/kcms2/article/abstract?v=def456&amp;dbcode=CMFD&amp;filename=101文稿">联邦学习中的隐私保护机制研究</a></span></td>
  <td class="author">赵六</td>
  <td class="source"><a>清华大学硕士学位论文</a></td>
  <td class="date">2023-06-01</td>
  <td class="quote">12</td>
  <td class="download">345</td>
</tr>
</tbody></table>
"""


def selftest():
    rows = parse_grid(FIXTURE)
    recs = [to_record(i, r) for i, r in enumerate(rows, 1)]
    print_table(recs)
    assert len(recs) == 2, f"应解析出 2 行，实际 {len(recs)}"
    r1 = recs[0]
    assert r1["title"] == "基于大语言模型的代码生成方法研究", f"标题高亮标签未剥净: {r1['title']}"
    assert r1["venue"] == "计算机学报" and r1["citations"] == 66 and r1["downloads"] == 1234
    assert r1["authors"] == ["张三", "李四", "王五"] and r1["year"] == 2024
    assert r1["url"].startswith("https://kns.cnki.net/kcms2/")
    assert recs[1]["year"] == 2023 and recs[1]["authors"] == ["赵六"]
    print("\n[selftest] 解析器自测全部通过 ✓")


def main():
    ap = argparse.ArgumentParser(description="知网(CNKI)检索与下载")
    ap.add_argument("query", nargs="?", help="检索词；多个词空格分隔自动拼为 SU AND SU")
    ap.add_argument("--expert", action="store_true", help="把 query 当作专业检索式，如 \"SU='联邦学习' AND SU='隐私'\"")
    ap.add_argument("--db", default="all", choices=list(DB_RESOURCE), help="库范围：all 总库 / journal 期刊 / thesis 硕博")
    ap.add_argument("--limit", type=int, default=10, help="每页条数（≤50），默认 10")
    ap.add_argument("--page", type=int, default=1, help="页码，默认 1")
    ap.add_argument("--sort", default="relevant", choices=list(SORT_FIELD), help="排序：relevant/date/cited/download")
    ap.add_argument("--output", default="results/search_cnki.json", help="结果 JSON 保存路径")
    ap.add_argument("--download", action="store_true", help="检索后下载 --index 指定的论文")
    ap.add_argument("--index", type=int, default=1, help="要下载/查看的条目编号")
    ap.add_argument("--dir", default="papers", help="PDF 保存目录")
    ap.add_argument("--sleep", type=float, default=3.0, help="请求间隔秒数（对知网友好），默认 3")
    ap.add_argument("--selftest", action="store_true", help="离线自测 HTML 解析器，不联网")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if not args.query:
        ap.error("请提供检索词，或用 --selftest 离线自测")

    expr = args.query if args.expert else " AND ".join(f"SU='{w}'" for w in args.query.split())

    op = new_session()
    print(f"检索式: {expr}\n库范围: {args.db}    建立知网会话…")
    warmup(op)
    html_text = grid_search(op, expr, args.db, args.page, args.limit, args.sort)

    recs = [to_record(i, r) for i, r in enumerate(parse_grid(html_text), 1)]
    if not recs:
        print("\n[提示] 未解析到结果。可能是：检索式无命中 / 知网改版 / 触发风控。"
              "\n       可先跑 --selftest 确认解析器正常，或走浏览器路线核对检索式。")
        sys.exit(1)

    if args.download and args.index <= len(recs):
        fetch_detail(op, recs[args.index - 1], args.sleep)  # 先补摘要再下载

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    print_table(recs)
    print(f"\n完整结果已保存 → {args.output}")
    if args.download:
        ok = download_cnki(op, recs[args.index - 1], args.dir, args.sleep)
        with open(args.output, "w", encoding="utf-8") as f:  # 回写详情页补到的摘要
            json.dump(recs, f, ensure_ascii=False, indent=2)
        sys.exit(0 if ok else 1)
    print("下一步: 加 --download --index 编号 下载 PDF；或把 JSON 交给 agent 解读对比。")


if __name__ == "__main__":
    try:
        main()
    except CnkiBlockedError as e:
        print(f"\n[知网风控] {e}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        sys.exit(1)
