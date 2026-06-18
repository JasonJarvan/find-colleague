# find-colleague

根据**项目**反查**负责该项目的同事**（也支持反向：某同事在做哪些项目）。  
事实来源是各团队的 **Confluence 周报历史**——把「谁这周在做什么项目」抽取、归一成一张可查询的「同事 ↔ 项目」映射表，帮你快速定位「这个项目该找谁」。

## 版本

| 版本 | 形态 | 存储 | 状态 |
|---|---|---|---|
| v1 | Claude Code Skill | Markdown | 已完成 |
| **v2** | **CLI**（本版） | SQLite + 向量（qwen3-embedding-8b） | **当前** |
| v3 | Service + MCP | SQLite + 向量 | 规划中 |

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

# 查看统计
find-colleague stats

# 查看支持的 embedding 模型
find-colleague models
```

## 数据来源

本工具读取 Confluence 周报页（通过 Atlassian MCP 或 REST API）。来源页登记格式见 `sources.example.md`。

**数据不入仓库**（`data/` 整目录在 `.gitignore`），每次运行 `find-colleague ingest` 从 Confluence 重建。

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

