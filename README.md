# find-colleague

根据**项目**反查**负责该项目的同事**（也支持反向：某同事在做哪些项目）。  
事实来源是各团队的 **Confluence 周报历史**——把「谁这周在做什么项目」抽取、归一成一张可查询的「同事 ↔ 项目」映射表，帮你快速定位「这个项目该找谁」。

## 版本

| 版本 | 形态 | 存储 | 状态 |
|---|---|---|---|
| v1 | Claude Code Skill | Markdown | 已完成 |
| **v2** | **CLI**（本版） | SQLite + 向量（qwen3-embedding-8b） | **当前** |
| v3 | Service + MCP | SQLite + 向量 | 规划中 |

## 快速开始（一句话安装）

**v2 — CLI（推荐）**
```bash
uv tool install git+https://github.com/JasonJarvan/find-colleague
```

**v1 — Claude Code Skill**（克隆进个人 skills 目录，之后在 Claude Code 里直接问「X 项目该找谁」）
```bash
git clone https://github.com/JasonJarvan/find-colleague.git ~/.claude/skills/find-colleague
```

> ⚠️ 仓库**不含数据**（`data/` 已 gitignore）。装好后首次使用需补一步：填 `config.toml` 的
> `OPENROUTER_API_KEY` + `data/sources.md` 的真实 page-id，再 `find-colleague ingest` 从
> Confluence 重建映射表（需 Atlassian 访问）。详见下方 §配置。

## 安装

依赖 [uv](https://github.com/astral-sh/uv)（或 pip）：

```bash
git clone <repo-url> find-colleague
cd find-colleague
uv sync
# 或：pip install -e .
```

## 配置

复制示例配置并填入 OpenRouter API key：

```bash
cp config.example.toml config.toml
# 编辑 config.toml，填入 OPENROUTER_API_KEY
# 或直接设环境变量（env 优先级更高）：
export OPENROUTER_API_KEY=sk-or-...
```

数据来源（Confluence 周报页）登记在 `sources.example.md`，复制并填写你团队的真实 page-id：

```bash
cp sources.example.md data/sources.md
# 编辑 data/sources.md，填入真实 space / page-id / folder-id
```

## CLI 用法

```bash
# 初始化数据库
find-colleague init

# 从 Confluence 抓取周报并抽取入库（需要 Atlassian MCP 或手动提供原文）
find-colleague ingest

# 生成/刷新向量 embedding（首次 ingest 后需跑一次）
find-colleague embed

# 查询：某项目该找谁
find-colleague who "EverOS Cloud"
find-colleague query "agent 消息总线"

# 查询：某同事在做哪些项目
find-colleague projects "张三"

# 职位/人物表：逐人列「姓名（团队）｜ 职位 ｜ 项目→工作清单」，按团队分组
# 例：列出工程团队每个人的职位和在做的项目
find-colleague people --team 工程
find-colleague people --name "张三"   # 只看某一个人

# 爬取编排（把 refresh 流程固化的子命令）
find-colleague crawl --plan --space DD --since 2026-06   # 读 sources.md 打印抓取计划
find-colleague crawl --dry-run                            # 扫 data/raw 列出待抽取快照，不调 LLM
find-colleague crawl                                      # 默认：增量 scan→LLM 抽取→ingest→embed

# 查看统计
find-colleague stats

# 查看支持的 embedding 模型
find-colleague models
```

> **关于 `crawl`**：它把 refresh 流程固化为一个子命令——`--plan` 读 `data/sources.md` 打印抓取计划，
> 默认增量扫描 `data/raw/` 新快照 → LLM 抽取 → ingest → embed。注意：从 Confluence **拉取原文**
> 这一步仍依赖 Atlassian MCP（由 agent 执行），`crawl` 自身只负责 plan + 抽取入库。此外，**`crawl`
> 的访问逻辑模块 `crawl.py` 含私域信息（page/folder id、人名等），不随仓库发布**（已 gitignore）——
> 公开 clone 里没有它，跑 `find-colleague crawl` 会优雅提示「未随仓库发布」，其余命令照常可用。

## 数据来源

本工具读取 Confluence 周报页（通过 Atlassian MCP 或 REST API）。来源页登记格式见 `sources.example.md`。

**数据不入仓库**（`data/` 整目录在 `.gitignore`），每次运行 `find-colleague ingest` 从 Confluence 重建。

## 刷新数据（端到端 runbook）

把一批最新周报抽取入库、刷新「同事↔项目」映射，v2 的完整流程如下。

> 这套流程主要面向**有 Confluence 访问权限的数据持有者**：其中「fetch 原文」一步要读你团队的私有周报页，
> 且 `crawl` 的访问逻辑模块未随仓库发布（见步骤 4 注）。**公开 clone 的用户**通常拿到的是别人建好的 DB，
> 直接用查询命令（query / who / people）即可，不必跑刷新。

### 0. 一次性配置（只做一次）

```bash
cp config.example.toml config.toml
# 编辑 config.toml：填 OPENROUTER_API_KEY（embedding 用）；
#   并填 [provider].llm（抽取/富化用的便宜 chat 模型，不用 Opus）。

cp sources.example.md data/sources.md
# 编辑 data/sources.md：填你团队真实的 site / space / page-id / folder-id。
# 占位格式见 sources.example.md。
```

### 1. 出抓取计划

读 `data/sources.md`，打印该抓哪些 page-id 及对应 CQL，不调任何 LLM：

```bash
find-colleague crawl --plan                       # 全部来源
find-colleague crawl --plan --space TEAM1         # 只看某 space
find-colleague crawl --plan --since 2026-06        # 只看某年月起的来源
```

### 2. fetch 原文（agent 步，用 Atlassian MCP）

按上一步的计划，在 Claude Code 里**由 agent 用 Atlassian MCP** 抓取对应周报页，落到
`data/raw/<team>-<period>.md`（文件头带 `page_id` 注释，供下一步增量识别），并在 `data/sources.md`
登记本次抓取记录（`last_fetched` 等）。

> **边界**：v2 的「从 Confluence 拉原文」这一步**仍由 Atlassian MCP（agent）执行，不在 CLI 里**。
> CLI 只负责出计划（步骤 1）和落库（步骤 4）。完整的 REST 自动爬虫规划在 v3。

### 3. 预演（可选）

不调 LLM、不写库，先看 `data/raw/` 里有哪些新快照会被处理：

```bash
find-colleague crawl --dry-run
find-colleague crawl --dry-run --only team1-2026-06.md   # 只验证某一个文件
```

### 4. 落库

```bash
find-colleague crawl
```

默认行为：增量 scan `data/raw/`（按 `content_hash` 记录在 `crawl_log`，已抽过的快照自动跳过）
→ LLM 抽取（走 `config.toml` 的 `[provider].llm`，**不用 Opus**）→ ingest 入库 → embed 生成向量。
加 `--no-embed` 可只入库、稍后再 `find-colleague embed` 补向量。

> **边界**：`crawl` 的访问逻辑模块 `src/find_colleague/crawl.py` 含私域信息（page/folder id、人名等），
> **不随仓库发布**（已 gitignore）。公开 clone 里没有它，跑 `find-colleague crawl` 会优雅提示
> 「未随仓库发布」并退出，其余命令（query / who / people / stats 等）照常可用。

### 5. 查询

```bash
find-colleague who "EverOS Cloud"      # 某项目该找谁（结构化）
find-colleague query "agent 消息总线"   # 语义召回
find-colleague people --team 工程       # 逐人看职位 + 在做的项目
```

也可在 Claude Code 里经 Skill 用大白话提问（「X 项目该找谁」），由 Skill 路由到上述命令。

## 脱敏说明

`sources.example.md` 为占位版，不含真实站点 URL / page-id / 人名。  
请勿将真实 `data/sources.md` 或 `config.toml`（含 API key）提交到版本控制。

**防泄漏 pre-push hook**：仓库带一个 `hooks/pre-push`，push 前自动扫描待发布文件里的密钥/内部域名/真实人名，命中即阻断。clone 后启用一次：

```bash
git config core.hooksPath hooks
```

通用密钥模式内置在 hook 里；公司专属词（公司名、真实人名、内部 page-id）放在 `data/.leakcheck-denylist`（gitignored，不发布），hook 运行时读取。

## 项目结构

```
find-colleague/
├── src/find_colleague/   # Python 包（CLI 逻辑、DB、向量召回）
├── prompts/extract.md    # LLM 抽取/富化 prompt 规范（单一事实源）
├── SKILL.md              # v1 Skill 定义（Claude Code Skill 格式）
├── config.example.toml   # 配置模板（复制为 config.toml 后填 key）
├── sources.example.md    # 数据来源登记模板（复制为 data/sources.md 后填真实 id）
└── pyproject.toml
```

