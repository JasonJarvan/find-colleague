# 周报来源登记（占位模板）

> 复制本文件为 `data/sources.md`，填入你团队真实的 Confluence 站点、space key 和 page-id。
> `data/sources.md` 已在 `.gitignore`，不会提交到版本控制。

## 格式说明

| 字段 | 说明 |
|---|---|
| `site` | Confluence 站点域名（如 `yourcompany.atlassian.net`） |
| `space` | Confluence Space Key |
| `page_id` | 周报页面 ID（从页面 URL 或「...」→「页面信息」获取） |
| `folder_id` | 周报目录页 ID（v3 遍历目录时用；v1/v2 填 `null`） |
| `team` | 团队标签（与映射表 section 对应，如 `工程和产品` / `算法`） |
| `version` | 适用版本（`v1` = 手动指定页；`v2+` = 遍历目录） |
| `last_fetched` | 最后抓取时间（由工具自动更新） |

## 示例条目

```yaml
sources:
  - site: "yourcompany.atlassian.net"
    space: "TEAM1"
    page_id: "<page-id-team1-weekly>"
    folder_id: null
    team: "工程和产品"
    label: "Team1 工程和产品周报"
    version: v1
    last_fetched: null

  - site: "yourcompany.atlassian.net"
    space: "TEAM2"
    page_id: "<page-id-team2-weekly>"
    folder_id: null
    team: "算法"
    label: "Team2 算法团队周报"
    version: v1
    last_fetched: null

  # v2+ 遍历目录时额外填 folder_id
  - site: "yourcompany.atlassian.net"
    space: "TEAM1"
    page_id: null
    folder_id: "<folder-id-team1-history>"
    team: "工程和产品"
    label: "Team1 历史周报目录"
    version: v2
    last_fetched: null
```

## 如何找到 page-id

1. 打开 Confluence 页面。
2. 点击右上角「...」→「页面信息」（Page information）。
3. 地址栏 URL 中 `/pages/` 后面的数字即为 `page_id`。
   例：`https://yourcompany.atlassian.net/wiki/spaces/TEAM1/pages/1234567890/周报` → page_id = `1234567890`
