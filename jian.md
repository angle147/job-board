# 校招岗位数据采集与看板

这是汝朝的校招岗位自动化采集、清洗、展示系统。

## 系统流程

```
7 个数据源爬虫 → 数据清洗去重 → NLP 标签分类 → GitHub Pages 看板
```

## 文件结构

| 文件 | 用途 |
|---|---|
| `scrape_*.py` | 各平台爬虫（51job、海投网、应届生、国考、微博、小红书、高校就业网） |
| `daily_update.py` | 每日自动采集主脚本 |
| `enrich.py` | 数据清洗、去重、NLP 行业标签推断 |
| `cleanup_expired_jobs.py` | 过期岗位自动清理 |
| `data/jobs.js` | 合并后的岗位数据（500+ 条活跃记录） |
| `index.html` | GitHub Pages 看板网站 |
| `setup_schedule.ps1` | Windows 定时任务配置 |
| `run_51job_collector.py` | 51job 专项采集 |
| `SKILL.md` | 技能定义文件 |

## 定时任务

- `daily_update.py` 每日自动执行
- 数据清洗后输出到 `data/jobs.js`
- GitHub Pages 自动部署最新的看板

## 数据源覆盖

51job、海投网、应届生网、国考、微博超话、小红书、各高校就业网（7 个）

## 常见操作

- **手动触发采集**：`python daily_update.py`
- **查看采集日志**：`daily_update.log`
- **清理过期数据**：`python cleanup_expired_jobs.py`
- **本地预览看板**：`python -m http.server` 然后打开 `index.html`
- **修改清洗规则**：改 `enrich.py`
- **新增数据源**：参照 `scrape_51job.py` 的结构写新爬虫

## 上次改动

多源去重 + PID 进程互斥锁容错。目前聚焦物流、供应链、交通运输领域岗位。
