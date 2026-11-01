---
name: literature-review
description: 文献检索、下载、解读与对比的一站式技能。当用户需要查文献、检索论文、下载论文 PDF、精读/解读某篇论文、生成文献卡片、比较多篇论文的指标与效果、提炼论文创新点、或写文献综述时使用——即使用户只说"帮我找几篇 xx 方向的论文""这篇论文讲了什么/创新点在哪"。支持 Web of Science、知网(CNKI)、Semantic Scholar、OpenAlex、arXiv、CrossRef 等来源。
---

# 文献检索与解读（Literature Review）

## 能力与边界

本技能能自动完成的：

- 多源检索论文：Semantic Scholar / OpenAlex / arXiv / CrossRef 免费、无需 key；Web of Science 需 API key
- IEEE Xplore 检索与全文下载：检索走 CrossRef 免费 API（10.1109 前缀过滤），PDF 走校园网 IP 授权直下（无需登录）；网络无订阅时会如实报错
- 知网检索与下载（网络可直连知网时）：脚本直连出结果表与 PDF，体验同公开数据源
- 下载开放获取（OA）PDF 到 `papers/`
- 解读单篇文献：研究问题、方法、实验设置、指标结果、创新点、局限
- 多篇对比：指标/效果对比表、技术演进脉络、研究空白

需要用户配合的（不要硬编造，如实说明）：

- Web of Science：需 Clarivate Starter API key（学校订阅邮箱在 developer.clarivate.com 申请）
- 知网（CNKI）：无公开 API。网络可直连知网时优先 Route A 脚本；被风控（验证码/403）时转浏览器/手动路线（见「知网检索流程」），本技能负责后续的解读、对比与综述

## 文件说明

- `scripts/search_papers.py`：多源检索（英文库），打印 Markdown 结果表并把含摘要的完整结果存为 JSON
- `scripts/search_ieee.py`：IEEE Xplore 检索与下载（CrossRef 元数据 → doi.org 反查 arnumber → IP 授权 PDF 端点）
- `scripts/search_cnki.py`：知网检索与下载（kns8s 接口，需可直连知网的网络；`--selftest` 可离线自测）
- `scripts/download_paper.py`：下载 OA PDF 到 `papers/`
- `references/paper-card-template.md`：单篇文献解读卡片模板
- `references/comparison-table-template.md`：多篇对比报告模板

脚本与本文件在同一技能目录下，调用时使用技能目录的绝对路径。

## 工作流程

按步骤执行，每步产物落盘（`papers/`、`results/`、`report/`），不要只留在对话里。

### 第 1 步：明确检索需求

用户没说清时，一次性问齐（不要多轮追问）：

1. 研究主题/关键词（英文库用英文词，可帮用户翻译）
2. 年份范围、需要的篇数
3. 目标来源（未指定则默认 Semantic Scholar；提到知网/WoS 见下方专门小节）
4. 最终产物：只要文献列表？单篇解读卡片？还是多篇对比报告？

### 第 2 步：检索

```bash
python <技能目录>/scripts/search_papers.py "large language model code generation" \
    --limit 10 --year-from 2023 --source s2
# --source 可选: s2 | openalex | arxiv | crossref | wos
# --most-cited 按被引量排序，适合快速找经典文献
```

IEEE Xplore（校园网 IP 授权，检索+下载一条命令）：

```bash
python <技能目录>/scripts/search_ieee.py "large language model code generation" --limit 10 --download --index 2
```

同一个主题可以多个来源各检索一次，交叉去重（按 DOI/标题）。

### 第 3 步：筛选

把结果表展示给用户，结合摘要按相关度、被引量、年份给出推荐下载名单，等用户确认或直接取 top-N。不要跳过筛选就全量下载。

### 第 4 步：下载 PDF

```bash
python <技能目录>/scripts/download_paper.py --from-results results/search_s2.json --index 3
```

下载失败的论文会给出 DOI——提示用户走学校图书馆 / 知网 / WoS 手动下载并放入 `papers/`，然后继续第 5 步。不要反复重试失败链接。

### 第 5 步：单篇解读（文献卡片）

逐篇读取 `papers/` 中的 PDF（用 pdf 技能或 pdftotext 提取全文），严格按 `references/paper-card-template.md`
的结构输出卡片，保存到 `report/cards/<序号>-<短标题>.md`。卡片里的每个实验数字必须来自论文原文
（标注表号/图号），禁止凭记忆或摘要脑补数值。

### 第 6 步：多篇对比与综述

全部卡片完成后，按 `references/comparison-table-template.md` 汇总：
总览对比表 → 指标横向对比 → 技术演进脉络 → 创新点提炼 → 研究空白，保存到 `report/comparison.md`。

## 知网检索流程（三条路线，按序尝试）

### Route A：脚本直连（所在网络可直连知网时首选）

`scripts/search_cnki.py` 复刻知网新版前端(kns8s)的内部检索接口，像公开数据源一样出结果表 + JSON：

```bash
python <技能目录>/scripts/search_cnki.py "大语言模型 代码生成" --limit 10   # 简单词自动拼成 SU AND SU
python <技能目录>/scripts/search_cnki.py "SU='联邦学习' AND SU='隐私保护'" --expert  # 专业检索式直传
python <技能目录>/scripts/search_cnki.py "大模型" --db thesis             # 限硕博学位论文库
python <技能目录>/scripts/search_cnki.py "大模型" --download --index 2    # 下载第 2 篇 PDF
```

- 结果 schema 与公开数据源一致（source="cnki"），后续文献卡片、对比流程完全不变
- 退出码 2 = 被知网风控（滑块验证/403，常见于机房/代理 IP）→ 转 Route B
- 请求间隔默认 3 秒，不要调小；教学用途低频调用，禁止批量抓取（违反知网条款且会被封 IP）

### Route B：浏览器人机协作（2026-11 实测全链路跑通）

分工：**人只负责过滑块验证码**（面板可见时拖一下），其余全自动。经实测的完整打法：

1. **过验证**：打开 `kns.cnki.net`，被导到滑块页时请用户拖一次；IAB 的 cookie 跨标签页共享，过一次后续不再弹
2. **直达检索**（关键：绕过首页个性化 AJAX，少触发风控）：直接导航
   `https://kns.cnki.net/kns8s/defaultresult/index?kw=<URL编码的检索词>&korder=SU`
3. **下钻筛选**：点左侧 `link "学位论文 N"` → 子项 `link "博士N"`（每次点击后等 3s 再拍快照确认）
4. **抓取列表**：在页面内执行 evaluate 遍历 `document.querySelectorAll("table tr")`，
   td[1] 标题链接、td[2] 作者、td[3] 机构、td[4] 年份，行内 `a[href*="bar/download/order"]` 即下载直链；存 JSON
5. **触发下载**（三种方式实测结论）：
   - ❌ 合成 `el.click()` —— 浏览器要求真实用户手势，无效
   - ❌ 直接 `goto(下载直链)` —— 缺 Referer，知网报"来源应用不正确(01)"
   - ✅ **在结果页上下文 `evaluate(() => { location.href = 直链 })`** —— 自动带 Referer，
     触发 download 事件且页面不跳走；一次会话可连续下多篇（间隔 3s+）
6. **找文件**：下载落在系统"下载"文件夹；Windows 下可能被 OneDrive 重定向，
   用 `powershell -c "(New-Object -ComObject Shell.Application).Namespace('shell:Downloads').Self.Path"` 解析真实路径
7. **CAJ 转 PDF**（知网学位论文多为 CAJ/HN 私有格式；首次使用先运行一次安装脚本）：
   ```bash
   python <技能目录>/scripts/setup_caj2pdf.py   # 首次：克隆 caj2pdf(GPL) + 依赖 + 免 mutool 补丁
   python <技能目录>/scripts/caj2pdf/caj2pdf convert 输入.caj -o 输出.pdf
   ```
8. **图像版 PDF**（扫描版无文字层，常见于 HN 格式）：用 pymupdf 把"摘要/创新点/结论"页渲染成 PNG，交给视觉模型识读

注意：知网下载消耗机构/个人配额，一次会话建议 ≤5 篇；自动化操作过快会再次触发滑块，届时请用户再拖一次即可。

### Route C：纯手动

把 Route B 的操作指引原样给用户，自己点；产物落位不变（`papers/` 与工作区）。

无论哪条路线拿到的题录/PDF，都进入统一的第 5-6 步解读与对比。

## Web of Science 检索与导出

两条路线，按需选择：

### 路线 1：浏览器（2026-11 实测全链路，校园网 IP 授权、零验证码）

1. 打开 `https://webofscience.com/wos/woscc/basic-search`（自动跳中国镜像 clarivate.cn，
   页脚显示机构名 = IP 授权成功，无需登录）
2. 检索框填词（Topic）→ 点 `button "Search" exact:true`（页面有 5 个同名按钮，必须精确匹配）→ 结果页
3. 左侧 Refine 面板可按 年度/文献类型/高被引/OA/机构 等筛选（各选项自带计数）
4. **导出题录**：`button "Export"` → menuitem 选 Excel（或 BibTeX/RIS/EndNote/Plain text）→
   对话框选记录范围（当前页 50 条 / 自定义，单次上限 1000）→ 内容下拉选 `Full Record` →
   确认键是 `#exportButton`（与工具栏 Export 撞名，用 id 定位）→ download 事件 → 落盘 savedrecs.xls
5. 解析：`pandas.read_excel` → 存 results/search_wos.json（Full Record 含摘要/DOI/Times Cited/机构/基金 72 列）
6. 全文获取：导出的 DOI 喂给 `search_ieee.py` 下载逻辑（IEEE 已打通）或 Unpaywall OA 链接；WoS 本身不存 PDF

### 路线 2：Starter API（全自动，需 key）

`--source wos --api-key <KEY>`（或环境变量 `WOS_API_KEY`），key 在 developer.clarivate.com 免费申请。
没有 key 时元数据可用 `--source openalex` 平替。
注意：WoS 与 OpenAlex 的被引量统计口径不同，对比表中并列时必须注明数据来源。

## 输出规范

```
papers/           下载的 PDF
results/          检索结果 JSON（含摘要）
report/
  cards/          单篇解读卡片，如 01-attention-is-all-you-need.md
  comparison.md   多篇对比报告
```

## 注意事项

- Semantic Scholar 免费接口限流（约 100 次/5 分钟），脚本会自动退避重试；仍失败则换 openalex
- OpenAlex 无 key 时按 IP 共享每日免费额度（UTC 午夜重置），429 时可传 --api-key（openalex.org 免费申请）或换 --source s2
- 解读依据 = PDF 全文 > JSON 里的摘要 > 标题，只能按这个置信度顺序写结论
- 不同数据集上的指标不可直接比较大小，对比表里要标明各自的数据集与实验设置
- 中文文献优先引导用户走知网流程；OpenAlex 对中文期刊覆盖不完整
- 引用信息（作者、年份、期刊、DOI）以检索结果 JSON 为准，卡片末尾给出规范引用格式（如 GB/T 7714 或 APA）
