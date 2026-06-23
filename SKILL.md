---
name: find-colleague
description: 根据项目找负责的同事（基于团队周报历史）。当用户问「X 项目该找谁/谁在做 X/谁负责 X」「这活派给谁、开会该喊谁」「某同事在做哪些项目」「某团队都有谁、谁是什么职位」，或需要按项目/同事/团队/职位检索周报里的人-项目归属时使用。本 Skill 是 v2 形态：作为自然语言路由层，把大白话问题路由到 find-colleague CLI 子命令经 Bash 执行，事实源是 CLI 背后的 SQLite + 向量库（由各团队 Confluence 周报抽取而来）。
---

# find-colleague

根据**项目**反查**负责的同事**（也支持同事→项目、团队→人、人→职位）。事实源是各团队
周报，已抽取归一入 **SQLite + 向量库**，由 `find-colleague` CLI 暴露查询。

本 Skill 是 **v2** 形态：**自然语言路由层**。Claude 自己充当 NL 层——把用户的大白话
问题判断意图后，**路由到对应 CLI 子命令经 Bash 执行**，再把命令输出整理成自然语言答复。
**不**自己读库、不另起 `ask` 这类命令；查询逻辑、排序、向量召回都在 CLI 里。

## 何时用

- 「<项目> 该找谁 / 谁在做 <项目> / 谁负责 <模块>」→ **派活/找人查询**
- 「这个活派给谁 / 开会该喊谁 / 谁能接 <议题>」→ **派活/找人查询**（语义召回）
- 「<同事> 在做哪些项目」→ **人→项目查询**
- 「<团队> 都有谁、各是什么职位 / 列一下 <团队> 的人和分工」→ **团队/职位查询**
- 「更新一下数据 / 重新抓周报 / 数据过期了」→ **刷新**

## 能力一：查询（默认，路由到 CLI）

### 第 0 步：先确认提问者是谁（不可省）

找人是为了找「别人」。**每次查询前先认人**：

- 从会话的 `userEmail` 推断姓名（如 `your.name@company.example` → 张三）；
- 推断不出，或不确定 ta 在哪个团队时，**直接问用户「你是谁 / 你在哪个团队」** 再继续。

认定的提问者姓名，会在「派活/找人」类查询里作为 `--exclude` 传给 CLI，把本人从结果剔除。

### 第 1 步：判断意图并路由

按问题类型选一个子命令，用 **Bash** 执行（命令签名以 `find-colleague <cmd> --help` 为准）：

| 用户在问 | 路由到 | 示例 |
|---|---|---|
| 某团队都有谁 / 谁是什么职位 / 团队分工 | `find-colleague people [--team X] [--name 人]` | `find-colleague people --team 工程` |
| 某项目/某活该找谁、该喊谁（**语义**） | `find-colleague query "<议题>" [--team X] [--exclude 提问者]` | `find-colleague query "消息总线" --exclude 张三` |
| 命中明确项目名/别名时（**精确**） | `find-colleague who "<项目>" [--exclude 提问者]` | `find-colleague who "EverOS Cloud" --exclude 张三` |
| 某人在做哪些项目 | `find-colleague projects "<人>"` | `find-colleague projects "张三"` |

路由判断要点：

- **派活/找人**（「该找谁/喊谁/派给谁」）默认走 `query`（向量语义召回，能命中没写死项目名的
  模糊议题），并**默认带 `--exclude <提问者>`**；当用户给的就是一个明确项目名/别名时，
  可改走 `who`（结构化精确）。拿不准就先 `query`。
  - `query` 还支持 `--team X`（限定团队）和 `-k N`（取前 N 条，默认 8）。
  - `query` **没有** `--name` 参数（那是 `people` 的）；按人筛走 `people --name` 或 `projects`。
- **团队/职位**走 `people`，按团队分组逐人输出「姓名（团队）｜ 职位 ｜ 项目→工作清单」。
  `--team` 取值限 `产品/工程/运营/算法`；`--name` 只看某一人。
- **人→项目**走 `projects "<人>"`（精确按姓名汇总该人全部贡献行）。

### 第 2 步：把 CLI 输出整理成自然语言答复

- CLI 输出形如 `· 张三（工程）— EverOS Cloud：搭消息总线 〔ENG〕[0.82]`。把它转成自然语言：
  谁（哪个团队）、做了什么、相关度/依据，命中多人时按 CLI 给的顺序（已排序）说。
- **提问者本人是主力时**：`--exclude` 已把本人剔除；若发现这块本就是提问者自己在做，
  明确点出「你自己就是这块主力」，再给可对接的协作方/相邻 owner（即 `query` 排在你之后的人），
  而不是把 ta 指回自己。
- **诚实边界**：只回答 CLI 返回的；命中为空（CLI 提示「数据中未见匹配」）时直说「数据中未见」，
  可建议换个说法或先**刷新**，不要臆测。

### 三个典型场景（示例问法）

- **新同事认识团队**：「我刚入职工程团队，这边都有谁、各做什么？」
  → `find-colleague people --team 工程`，逐人念「姓名｜职位｜在做的项目」。
- **派活给谁**：「这个『离线推理加速』的活该派给谁？」
  → `find-colleague query "离线推理加速" --exclude <你>`，给最相关的 1-3 人 + 依据。
- **开会喊谁**：「要开个 EverOS Cloud 的对齐会，该喊哪些人？」
  → 命中明确项目名，`find-colleague who "EverOS Cloud" --exclude <你>`，列全部相关贡献者。

## 能力二：刷新（按需，会读外部）

重抓周报并重建库。**有外部读取副作用**，执行前向用户确认。事实源是 **DB**（不再是 v1 的
`colleague-project.md`）。流程 = 「MCP 抓原文落盘」+「`find-colleague crawl` 编排抽取入库」：

1. 读 `data/sources.md`，取要刷新的页面（page-id/space/cloudId 全在该文件，gitignored，
   含真实值——本 Skill 不硬编码这些值，单一事实源 = `sources.md`）。可先
   `find-colleague crawl --plan --space <S> --since <YYYY-MM>` 打印抓取计划核对。
2. **拉原文**：对每个目标页经 Atlassian MCP 读取
   （`mcp__claude_ai_Atlassian_Rovo__getConfluencePage`，`contentFormat=markdown`），
   把原文**落 `data/raw/<team>-<period>.md` 快照**（保证可重跑、可追溯）。
   这一步是 `crawl` 之外的、由 agent 经 MCP 执行的拉取。
3. **抽取入库**：跑 `find-colleague crawl`——它增量扫 `data/raw/` 新快照 → LLM 抽取
   （LLM#1 抽结构化 rows、LLM#2 富化 `embed_text`，规范见 `prompts/extract.md`）→
   `ingest` → `embed`。可先 `find-colleague crawl --dry-run` 只列待抽取快照不调 LLM。
   - **抽取的 LLM 不用 Opus**：crawl 走 config `[provider].llm`（OpenRouter 便宜 chat 模型）。
   - `crawl` 含私域访问逻辑（`crawl.py` 未随仓库发布）；公开 clone 里跑会优雅提示「未随仓库
     发布」，其余命令照常。
4. 鉴权失效（headless/cron 常见）时停下来报告，不要伪造数据。
5. 刷新后可 `find-colleague stats` 看库概况确认。

## 命令速查（事实源：`find-colleague <cmd> --help`）

| 命令 | 用途 |
|---|---|
| `find-colleague query "<议题>" [--team X] [--exclude 人] [-k N]` | 语义召回：该找谁/喊谁 |
| `find-colleague who "<项目>" [--exclude 人]` | 结构化：某项目/别名该找谁 |
| `find-colleague projects "<人>"` | 某同事在做哪些项目 |
| `find-colleague people [--team X] [--name 人]` | 逐人列 姓名（团队）｜职位｜项目清单 |
| `find-colleague stats` | DB 概况（人数/项目数/向量数/团队分布） |
| `find-colleague crawl [--plan ... \| --dry-run]` | 刷新编排：plan→抽取→ingest→embed |
| `find-colleague init / ingest / embed / models` | 建表 / 入库 / 补向量 / 列 embedding 模型 |

## 边界与演进

- v2 不臆测：只复述 CLI 返回的；查询走 CLI（DB + 向量），不直接读 `data/raw/` 原文。
- 版本：v1（Skill + Markdown）→ **v2（CLI + SQLite + 向量，当前；本 Skill 接此层）** →
  v3（Service + MCP + 定期爬虫）。升级触发与整体设计见仓库根 `CLAUDE.md`。
