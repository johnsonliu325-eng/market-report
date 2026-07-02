# 美股晨报

自动生成的美股盘面晨报，每日更新，发布在 GitHub Pages。

- `build_site.py` — 拉取 CNBC 行情，生成 `site/index.html`
- `lib/cnbc.py` — 数据引擎
- `lib/symbols.py` — 指数、板块 ETF、重点个股配置
- `.github/workflows/deploy.yml` — 每日自动构建并发布

数据为隔夜收盘行情。新闻与深度解读在本地用 Claude Code 补充。
