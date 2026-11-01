#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键安装 CAJ→PDF 转换能力（知网学位论文后处理依赖）。

做三件事：
1. git clone caj2pdf（第三方项目，GPL-3.0，故不随本仓库分发，运行时拉取）
2. pip 安装依赖：imagesize / PyPDF2==2.2.0 / PyMuPDF
3. 给 cajparser.py 打"免 mutool"补丁：xref 修复改用 PyMuPDF/PyPDF2，
   Windows 上无需再安装 MuPDF 命令行工具

用法：python setup_caj2pdf.py
重复运行安全（已装则跳过）。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAJ_DIR = os.path.join(HERE, "caj2pdf")
REPO = "https://github.com/caj2pdf/caj2pdf.git"

HELPER = '''

def _mupdf_clean(src, dst):
    """xref 修复：优先 PyMuPDF，退回 PyPDF2（替代外部命令 mutool clean）"""
    try:
        import fitz  # PyMuPDF，可修复无 xref 的 PDF
        doc = fitz.open(src)
        doc.save(dst, garbage=3, deflate=True)
        doc.close()
        return
    except ImportError:
        pass
    from PyPDF2 import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(src, strict=False))
    with open(dst, "wb") as f:
        writer.write(f)
'''

ANCHOR = "from utils import fnd, fnd_all, add_outlines, fnd_rvrs, fnd_unuse_no, find_redundant_images"
PATCHES = [
    ('check_output(["mutool", "clean", "pdf.tmp", "pdf_toc.pdf"], stderr=STDOUT)',
     '_mupdf_clean("pdf.tmp", "pdf_toc.pdf")'),
    ('check_output(["mutool", "clean", dest + ".tmp", dest], stderr=STDOUT)',
     '_mupdf_clean(dest + ".tmp", dest)'),
]


def main():
    if not os.path.exists(os.path.join(CAJ_DIR, "cajparser.py")):
        print(f"[1/3] 克隆 caj2pdf → {CAJ_DIR}")
        subprocess.run(["git", "clone", "--depth", "1", REPO, CAJ_DIR], check=True)
    else:
        print("[1/3] caj2pdf 已存在，跳过克隆")

    print("[2/3] 安装 Python 依赖 (imagesize / PyPDF2 / PyMuPDF)")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "imagesize", "PyPDF2==2.2.0", "PyMuPDF"], check=True)

    print("[3/3] 打免 mutool 补丁")
    path = os.path.join(CAJ_DIR, "cajparser.py")
    src = open(path, encoding="utf-8").read()
    if "_mupdf_clean" in src:
        print("      补丁已存在，无需修改")
        return
    if ANCHOR not in src:
        sys.exit("[错误] caj2pdf 代码结构变化，锚点未找到——请手动参考 README 打补丁")
    src = src.replace(ANCHOR, ANCHOR + HELPER, 1)
    for old, new in PATCHES:
        if old in src:
            src = src.replace(old, new)
        else:
            print(f"[警告] 未找到待替换片段: {old[:50]}…")
    open(path, "w", encoding="utf-8").write(src)
    print("完成。用法：python scripts/caj2pdf/caj2pdf convert 输入.caj -o 输出.pdf")


if __name__ == "__main__":
    main()
