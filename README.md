# 每日一报 · Daily Brief

静态资讯网站，每天自动采集全球科技 / 互联网 / AI / 开发者生态新闻，经 AI 整理为中英双语日报。正式域名：`https://daily.fs.kg`。

无数据库、无常驻服务器、无 Vercel Functions / Cron / Cloudflare 依赖。GitHub Actions 只负责生成内容，Vercel 只负责托管静态文件。

## 1. 工作方式

```
GitHub Actions（每天 UTC 22:30 / 北京时间次日 06:30，可手动触发）
  → Python 采集 RSS + Hacker News + GitHub Search API
  → 清洗、时间归一、相关性过滤、URL/标题去重、事件预聚合、精选
  → DeepSeek（OpenAI 兼容接口）生成双语标题/摘要、分类、评分、重点、趋势
  → JSON 校验 → 写入 public/data/ → 生成全部静态 HTML
  → 自动提交 main 分支 → Vercel 自动部署
```

## 2. 目录结构

```
config/sources.yaml        数据源与运行参数（超时/重试/频率/启用状态）
scripts/
  run_daily.py             总入口（采集→处理→校验→生成）
  fetch_news.py            RSS / HN / GitHub / 演示数据采集
  clean_news.py            清洗、相关性过滤、启发式分类评分
  deduplicate.py           URL 规范化、标题相似度去重、事件聚合、精选
  ai_process.py            AI 双语处理与降级
  generate_site.py         JSON + 静态页面 + sitemap/robots
  validate_data.py         生成前数据校验
  utils.py                 HTTP 重试、时间、文件写入等
templates/                 Jinja2 页面模板
public/                    Vercel Output Directory（静态站点）
  data/YYYY-MM-DD.json     每日独立数据（不覆盖历史）
  data/latest.json         最新一期完整数据
  data/archives.json       历史日期索引
  data/generation_status.json 最近一次生成状态
  data/source_history.json    各数据源累计成功率
  daily/YYYY-MM-DD/index.html 每日详情页
  categories/*/index.html  六大分类页
  archives/ about/ 404.html sitemap.xml robots.txt assets/
.github/workflows/daily.yml 定时生成与自动提交
tests/test_pipeline.py      核心逻辑单元测试
```

## 3. 本地开发

需要 Python 3.9+（GitHub Actions 使用 3.11）。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 模拟数据，验证静态页面与交互（不联网、不调用 AI）
python scripts/run_daily.py --demo --date 2026-11-21

# 真实采集 + AI（需设置环境变量）
export AI_API_KEY=sk-xxxx
export AI_BASE_URL=https://api.deepseek.com      # 可省略，默认即此值
export AI_MODEL=deepseek-chat                    # 可省略，默认即此值
python scripts/run_daily.py

# 不配置任何密钥：自动翻译补齐双语，仍然正常生成
python scripts/run_daily.py

# 想关闭自动翻译，仅保留原文
TRANSLATE_ENABLED=false python scripts/run_daily.py

# 指定日期 / 指定配置文件
python scripts/run_daily.py --date 2026-11-21 --config config/sources.yaml
```

本地预览静态站点：

```bash
python3 -m http.server 8080 -d public
# 打开 http://localhost:8080/
```

测试：

```bash
python -m unittest discover -s tests -v
```

## 4. AI 配置（完全可选，不配置也能用）

**不配置任何密钥时，网站照常运行**：采集、去重、分类、评分、静态页面与中英双语内容都会正常生成。此时使用无需密钥的公开翻译接口自动补全另一语言的标题与摘要，并在卡片上标注“自动翻译 / Auto-translated”；翻译接口不可用时回退为原文并标注“原文摘要”。

| 环境变量 | 必填 | 说明 |
| --- | --- | --- |
| `AI_API_KEY` | 否 | DeepSeek API Key。不填则使用上面的零配置翻译回退 |
| `AI_BASE_URL` | 否 | OpenAI 兼容接口根地址，默认 `https://api.deepseek.com` |
| `AI_MODEL` | 否 | 默认 `deepseek-chat` |
| `AI_TIMEOUT` | 否 | 单次请求超时秒数，默认 90 |
| `TRANSLATE_ENABLED` | 否 | 默认 `true`；设为 `false` 可关闭自动翻译，仅保留原文 |
| `SITE_URL` | 否 | Canonical / sitemap 域名，默认 `https://daily.fs.kg` |
| `GITHUB_TOKEN` | 否 | 用于提高 GitHub Search API 限额；Actions 内已自动提供 |

如果愿意配置 AI，密钥只能放在 GitHub Secrets 或本地环境变量中；代码中没有任何硬编码密钥，前端 JS / JSON 也不包含密钥。

AI 请求使用结构化 JSON 输出与字段校验。AI 失败、返回非法 JSON 或部分条目缺失时，先尝试自动翻译补齐双语，再回退原文；不会导致整份日报丢失。摘要基于原始标题与 RSS 摘要生成，不转载全文。

## 5. GitHub 配置（需你手动完成）

1. 新建 GitHub 仓库（建议 public），将本项目推送到 `main` 分支。
2. Settings → Actions → General → Workflow permissions：选择 **Read and write permissions**，允许工作流提交代码。
3. **可以跳过 Secrets 配置**。直接到下一步手动触发即可，网站会用零配置翻译回退生成双语内容。只有想获得更高质量的 AI 摘要时，才需要添加 `AI_API_KEY`（DeepSeek 控制台创建，聊天补全权限）、`AI_BASE_URL`、`AI_MODEL` 三个 Secret。
4. Actions 页面找到 **Generate Daily Tech Brief**，点击 **Run workflow** 手动触发一次。确认日志显示采集、校验、生成成功，且仓库 `public/` 目录出现新的提交。
5. 定时任务为 `cron: "30 22 * * *"`（UTC）。GitHub 不保证准时，可能排队延迟。

不需要提供任何账号密码。`GITHUB_TOKEN` 由 Actions 自动提供，用于推回仓库与提高 GitHub API 限额。

## 6. Vercel 部署（需你手动完成）

1. Vercel → Add New → Project → 导入上述 GitHub 仓库。
2. 配置：Framework Preset = **Other**；Build Command = 留空；Install Command = 留空；Output Directory = `public`。
3. 部署后先验证 Vercel 自动分配的 `*.vercel.app` 默认域名，确认首页、日报页、归档页与 JSON 文件可访问。
4. Project → Settings → Domains → 添加 `daily.fs.kg`。Vercel 会显示其要求的 DNS 记录类型与目标值（通常是 CNAME，但**以控制台实际显示为准**）。
5. 在 `fs.kg` 当前的 DNS 服务商处按 Vercel 给出的值添加记录；不要假设 DNS 服务商是 Cloudflare。
6. 等待 DNS 验证通过，Vercel 自动签发 HTTPS 证书；访问 `https://daily.fs.kg` 验证。
7. 之后每次 GitHub `main` 分支更新，Vercel 自动重新部署。

本地强制使用自定义域名生成链接时，可设置 `SITE_URL=https://daily.fs.kg`（默认值已是该域名）。

## 7. SEO 与前端

- 每页独立 Title / Meta Description / Canonical / Open Graph；每日页正文直接写入静态 HTML，不依赖浏览器 JS 加载。
- `sitemap.xml`、`robots.txt`、`404.html`、语义化标题层级、规范日期/分类 URL。
- 默认中文，右上角地球图标 + `EN / 中文` 一键切换；语言切换只改写已渲染 DOM，不重新请求数据，并记住选择。
- 主题按钮只占一个图标位，点击循环切换「跟随系统 → 日间 → 夜间」；图标分别为显示器 / 太阳 / 月亮，选择持久化保存。跟随系统模式响应 `prefers-color-scheme`。
- 首页 / 日报页支持标题与摘要搜索、分类筛选、按重要性或时间排序；归档页支持月份筛选。
- 时间统一按北京时间（UTC+8）展示；外链使用 `target="_blank" rel="noopener noreferrer"`。
- 原生 HTML / CSS / JavaScript，无前端框架；响应式适配桌面、平板与手机。

## 8. 验收与测试结果（本地实际执行）

- 演示数据端到端：`--demo` 生成 20 条模拟新闻与全部页面，验证双语属性、卡片、归档、分类页。
- 真实采集端到端：7 个数据源全部成功，采集约 165 条原始新闻，清洗后 71 条，去重后 71 条，精选 25 条；JSON 校验通过；首页、日报页、归档页、6 个分类页、sitemap/robots 全部生成。
- 无 AI Key / `--skip-ai` 零配置路径已验证：`ai_status=disabled`，自动生成另一语言标题与摘要，卡片标注“自动翻译”；翻译失败才回退“原文摘要”。
- AI 成功返回与非标准 JSON 失败降级路径已通过单元测试覆盖。
- 单元测试：`python -m unittest discover -s tests` → **13 passed**。
- GitHub Actions 自动提交、Vercel 部署、DNS 绑定与 HTTPS：**未执行**（需要在你的 GitHub / Vercel / DNS 账户中操作），因此不声称已上线。

当前仓库中 `public/data/` 的日报是本地真实采集、零配置自动翻译生成的一期，可用于页面预览；首次 Actions 运行会生成新的日报并成为 `latest.json`。

## 9. 已知问题与限制

- Hacker News Firebase API 偶发超时；单源失败只影响该源，已记录到 `generation_status.json`，可通过手动重跑恢复。
- RSS 字段和链接规则可能随媒体改版变化；若某源长期为 0 条，请在 `config/sources.yaml` 中临时禁用或调整。
- GitHub 数据是近期高星仓库的搜索代理数据，**不是**官方 Trending 排名，页面与 README 均已注明。
- AI 可能达到限额或返回非标准 JSON；此时自动降级为原文内容，摘要质量会下降但不丢新闻。
- 仅收录标题、链接与短摘要，不采集全文；版权归原作者与媒体所有。
- GitHub Actions 定时执行可能排队延迟，不保证精确到分钟。
- 每日 25 条上限与 AI 批量参数在 `config/sources.yaml` 的 `settings` 中调整，用于控制 API 成本。

## 10. 已完成 / 待手动操作

**已完成**：项目目录与依赖、数据源配置、采集/清洗/去重/分类/评分、AI 双语处理与零配置翻译回退、JSON 数据结构与校验、静态站点与全部页面、中英文切换/搜索/筛选/排序、SEO 文件、GitHub Actions 工作流、Vercel 配置、README、单元测试、本地真实采集验证。

**需要你手动完成**：创建 GitHub 仓库并推送；开启 Actions 写权限（**AI Secrets 可以不配**）；手动触发一次 Actions 验证；在 Vercel 导入仓库并部署；在 Vercel 添加 `daily.fs.kg` 域名并在当前 DNS 服务商配置记录；验证 HTTPS 与线上页面。
