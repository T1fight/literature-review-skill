# Literature Review Skill

**一站式文献检索、下载、解读与对比的 Agent Skill。** 对 agent 说一句"帮我找 xx 方向近三年的论文，下载后解读并做指标对比"，即可自动完成：检索 → 下载 PDF → 单篇文献卡片 → 多篇对比报告。

An all-in-one Agent Skill for literature search, full-text download, paper interpretation and cross-paper comparison. Say "find recent papers on X, download and compare them" and the agent runs the whole pipeline.

## 支持的数据源与能力

| 来源 | 检索 | 全文 PDF | 前提 |
|------|:----:|:--------:|------|
| Semantic Scholar / OpenAlex / arXiv / CrossRef | ✅ | OA 部分 ✅ | 免费，无需 key |
| **IEEE Xplore** | ✅ | ✅ 直下 | 校园网/机构 IP 订阅（无需登录） |
| **Web of Science** | ✅（含引文/筛选/导出题录） | ⭕ 经 DOI 到出版商 | IP 授权（浏览器路线零验证码）或 Starter API key |
| **知网 CNKI**（含博士/硕士学位论文库） | ✅ 三路线 | ✅（CAJ 自动转 PDF） | 可直连知网的校园网；滑块验证码需人工拖一次 |

博士论文支持是国内场景的关键：知网 CAJ/HN 私有格式自动转 PDF（经 `setup_caj2pdf.py` 安装的转换器），扫描版无文字层的论文自动用视觉模型识读关键章节。

## 安装

要求：Python 3.8+（脚本纯标准库，零 pip 依赖）。适用于任何支持 Agent Skills 的工具（ZCode / Codex CLI / Claude Code / Cursor …）。

**ZCode / Codex 系**（用户级，全局可用）：

```bash
git clone https://github.com/T1fight/literature-review-skill.git
cp -r literature-review-skill ~/.agents/skills/literature-review
```

**Claude Code**：

```bash
cp -r literature-review-skill ~/.claude/skills/literature-review
```

**项目级**：把文件夹放进你的项目 `.agents/skills/` 或 `.zcode/skills/`。

**可选**（需要知网学位论文 CAJ 转换时跑一次）：

```bash
python ~/.agents/skills/literature-review/scripts/setup_caj2pdf.py
```

## 快速开始

装好后新开会话，直接说：

> 帮我检索近三年"大模型代码生成"方向的论文，下载 3 篇并生成解读卡片和指标对比报告

或手动调脚本：

```bash
S=~/.agents/skills/literature-review/scripts

# 英文公开库（免费直连）
python $S/search_papers.py "large language model code generation" --limit 10 --year-from 2023

# IEEE Xplore（IP 授权网络，检索+下载一条命令）
python $S/search_ieee.py "large language model" --limit 10 --download --index 2

# 知网（需可直连知网的校园网；被风控时见 SKILL.md 三路线）
python $S/search_cnki.py "大语言模型" --db thesis --limit 10
python $S/search_cnki.py --selftest   # 离线自测解析器

# OA PDF 下载（Unpaywall → arXiv → DOI 链）
python $S/download_paper.py --doi 10.1109/5.726791 --email you@example.com
```

## 产出规范

- `papers/` 下载的 PDF
- `results/` 检索结果 JSON（各来源统一 schema）
- `report/cards/` 单篇文献解读卡片（研究问题/方法/实验/指标/创新点/局限，数字强制标注原文出处）
- `report/comparison.md` 多篇对比报告（总览表 / 指标横向对比 / 技术演进脉络 / 研究空白 / GB/T 7714 引用）

模板见 `references/`，保证多次运行输出结构一致、可直接贴进综述。

## 知网三路线设计（Route A/B/C）

知网无公开 API 且有滑块风控，skill 内置降级策略：

- **Route A** 脚本直连：复刻 kns8s 前端接口（`search_cnki.py`），可直连的网络下体验同公开数据源；被风控自动识别（退出码 2）
- **Route B** 浏览器人机协作：人工拖一次滑块 → agent 直达检索 URL → 抓列表 →
  页面内 `location.href` 触发下载（绕过合成点击不被信任 / 直连缺 Referer 两个坑，实测有效）→ CAJ 转 PDF
- **Route C** 纯手动指引

## 合规声明

- 只下载合法可及的内容：OA 论文、机构 IP 订阅范围内的出版商 PDF、你有权访问的知网文献
- 不绕过付费墙、不破解验证码（滑块由人完成）、知网保持低频调用（默认请求间隔 3s），禁止批量抓取
- WoS 被引量与 OpenAlex 口径不同，对比时 skill 会强制注明来源

## 致谢

- 元数据：[Semantic Scholar](https://www.semanticscholar.org/product/api) / [OpenAlex](https://openalex.org) / [arXiv](http://export.arxiv.org) / [CrossRef](https://api.crossref.org) 免费 API
- CAJ 转换：[caj2pdf](https://github.com/caj2pdf/caj2pdf)（GPL-3.0，setup 脚本自动拉取并打免 mutool 补丁）
- License: MIT（本仓库自有代码；caj2pdf 遵循其原 GPL-3.0 协议）
