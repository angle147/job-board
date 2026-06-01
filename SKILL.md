# 校招岗位汇总网页搭建 Skill

## 概述

从零搭建一个校招实习岗位汇总 + 国考职位查询 + 线下招聘会追踪的个人求职看板。涵盖数据爬取、GitHub 开源工具借鉴、反爬策略、数据质量标准、每日自动更新全流程。

## 整体工作流

```
用户提需求
  → GitHub 搜索相关项目（借鉴思路/代码）
  → 评估数据源可爬性（手动验证页面结构）
  → 撰写爬虫脚本（参考开源项目的反爬技巧）
  → 接入网页展示
  → 配置定时任务自动更新
  → 设定数据过期清理标准
```

## 一、GitHub 项目借鉴策略

### 搜什么

每类平台用一个通用搜索模板，换成具体平台名即可：

```
site:github.com {平台名} scraper crawler 2025 2026
site:github.com {平台名} spider 爬虫
```

平台名替换：`xiaohongshu` / `weibo` / `yingjiesheng` / `zhaopin` / `51job` / `BOSS直聘` 等。

### 评估标准

拿到一个 GitHub 项目后，按以下顺序快速判断可用性：

| 维度 | 判断标准 |
|---|---|
| **最后更新时间** | 超过 6 个月 → 大概率 API 已过期 |
| **依赖复杂度** | 纯 `requests` → 优先；需要 Playwright/Selenium → 次之；需要 Docker → 最后 |
| **反爬方案** | 纯 HTTP + 签名 → 最理想；Cookie 模拟 → 可行；浏览器自动化 → 万不得已 |
| **平台适配** | 看 README 里写了支持哪些平台/接口 |
| **Stars/活跃度** | 有 Issue 讨论反爬更新的 → 说明作者还在维护 |

### 本次实际采用的 GitHub 项目

| 项目 | 借鉴了什么 | 实际效果 |
|---|---|---|
| **Auto-JobHunter** | 指数退避重试、请求抖动、多字段去重、会话复用 | 融入 `scraper.py` v2 |
| **crawl4weibo** | `search_posts()` 一行代码搜微博，无需 Cookie | `scrape_weibo.py` 核心依赖 |
| **cv-cat/Spider_XHS** | 二维码扫码登录、Cookie 自动管理 | 签名 JS 与 Node v24 不兼容，未采用 |
| **xguox/Spider_XHS** | 完整的小红书 PC 端 API + 签名算法 | 签名算法被服务器拒绝，未采用 |
| **0voice/2026-Computer-Spring-Recruitment** | 校招信息的组织格式参考 | 仅格式参考 |

## 二、数据源选取标准

### 优先级金字塔

```
第一层：政府/高校官方平台（无反爬，结构化好）
    ├── 国资委招聘专栏（gzw.shandong.gov.cn）
    ├── 高校就业服务平台（school.gxjy.sdei.edu.cn）
    └── 国家公务员局职位表

第二层：校招聚合平台（轻度反爬，数据量大）
    ├── 应届生求职网（yingjiesheng.com）→ 移动版 m.yingjiesheng.com
    └── 海投网/牛企直聘（campus.niuqizp.com）

第三层：社交媒体（无反爬或轻度反爬，数据噪声大）
    └── 微博搜索 → crawl4weibo

第四层：商业招聘平台（重度反爬，需浏览器方案）
    ├── 智联招聘 → 需 Playwright
    ├── 51job → 需 Playwright
    └── BOSS 直聘 → 需 Playwright + Stealth

不可行：重度反爬且无开源方案
    └── 小红书 → 签名算法 + 浏览器指纹双重拦截
```

### 判断一个 URL 是否可爬的快速方法

```python
# 1. 先用 requests 直接 GET，看返回状态码和内容
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
# 200 + HTML 中有数据 → ✅ 可直接爬
# 200 + 空壳 HTML（数据由 JS 加载）→ 找 API 接口
# 403/401 → 需要 Cookie 或登录
# 跳转到登录页 → 需要认证

# 2. 如果有 API，尝试 POST
r = requests.post(api_url, json={...})
# 200 + JSON 数据 → ✅ 纯 API 方案
# 403 + WAF 拦截 → ❌ 需要浏览器方案

# 3. 检查移动版
# m.{domain} 或 {domain}/m/
# 移动版通常更简单、少 JS 渲染
```

## 三、爬取技巧与反爬对策

### 本次实践的技巧清单

**1. 优先移动版**

PC 版 `yingjiesheng.com` 全是 JS 加密 → 移动版 `m.yingjiesheng.com` 纯 HTML。

**2. 会话复用（Session）**

```python
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0", ...})
# 后续请求都用 session.get()，自动管理 Cookie 和连接池
```

**3. 指数退避 + 抖动（参考 Auto-JobHunter）**

```python
# 重试间隔：1s → 2s → 4s，每次加随机抖动
backoff = (2 ** attempt) + random.random()
time.sleep(backoff)

# 正常请求间隔也加抖动
time.sleep(0.6 + random.random() * 0.5)
```

**4. UA 轮换池**

```python
USER_AGENTS = [
    "Mozilla/5.0 ... Chrome/130.0 ...",
    "Mozilla/5.0 ... Edg/129.0 ...",
    "Mozilla/5.0 ... Firefox/132.0",
]
session.headers["User-Agent"] = random.choice(USER_AGENTS)
```

**5. 多字段复合去重**

```python
# 不只用标题去重，用 MD5(公司名 + 职位 + URL 域名)
key = hashlib.md5(f"{company}|{position[:30]}|{domain}".encode()).hexdigest()
```

**6. 政府网站特殊规律**

- 山东省国资委：列表页是 `<table><td width=876><a>` 结构，日期在相邻 `<td width=46>`
- 高校就业平台：宣讲会链接统一包含 `TblCareerFairReviewRecord`
- 中公职位库：部门列表 URL 用内部短码而非官方代码，分页格式为 `bmall{code}_{page}.html`

**7. 详情页信息提取**

```python
# 用多个正则依次尝试，政府网站格式多变
patterns = [
    r"工作地点[：:]\s*(.+?)(?:\n|。|；)",   # 中文冒号
    r"工作地址[：:]\s*(.+?)(?:\n|。|；)",    # 同义不同词
    r"地点[：:]\s*(.+?)(?:\n|。|；)",         # 简短版
]
for pat in patterns:
    m = re.search(pat, text)
    if m: break
```

## 四、数据质量标准

### 校招/社招岗位标准

一条**有效**的校招/社招记录必须满足：

| 字段 | 标准 |
|---|---|
| `companyName` | 不为空，长度 ≥ 3，不含导航词（首页/新闻中心等） |
| `updateTime` | 必须是半年内（`cutoff = 2025-11-01`） |
| `noticeLink` | 必须有可访问的公告/投递链接 |
| `recruitType` | 从标题自动推断（校招→春招，实习→实习），无法推断则标记「校招/社招」 |
| `targetYears` | 优先从详情页提取（2027届/2026届），默认「2026届」 |

**去重规则**：公司名 + 职位前30字 + 公告链接域名 → MD5 → 哈希表去重

**过期清理**：
- 爬虫采集时过滤：`updateTime < 2025-11-01` 的直接丢弃
- `deadline` 早于当前日期且非「招满为止」的条目，网页端自动标灰（待实现）
- 国考数据仅周日更新（数据变动频率低）

### 线下招聘会标准

一条**有效**的招聘会记录必须满足：

| 字段 | 标准 |
|---|---|
| 内容关键词 | 必须包含至少一个：招聘会/双选会/宣讲会/校招/春招/秋招 |
| 时效性 | 日期在**近 14 天内**（含当天），过期的丢入折叠区 |
| 日期格式 | 支持三种：`YYYY-MM-DD`、`MM月DD日`、微博发布时间 |

**过期处理**：
- 爬虫端：`_parse_date()` < `now - 14天` 的直接丢弃
- 网页端：再次解析日期，过期条目折叠到「已过期（N场，点击展开）」
- 视觉效果：有效用绿色边框，过期用灰色 + `opacity: 0.6`

**去重规则**：`source_url` 后 40 字符作为唯一 ID

### 国考职位标准

- 仅保留交通相关部委（关键词匹配：交通/铁路/航空/海事/水利/邮政/物流）
- 报名时间为 2025年10-12月的数据标注「2026年度」
- 时间线公告基于近三年（2024-2026）数据预测 2027 年度

## 五、每日自动更新

### 编排器 `daily_update.py`

```python
# 每天 9:00 执行
SCRAPERS = [
    ("山东省国资委",       "scraper.py --source sasac",        每日),
    ("应届生求职网",       "scrape_yingjiesheng.py",           每日),
    ("海投网交通类",       "scrape_haitou.py",                每日),
    ("微博校园招聘会",     "scrape_weibo.py",                 每日),
    ("高校就业平台",       "scrape_university.py",            每日),
    ("应届生数据校对",     "enrich.py",                       每日),
    ("国考交通职位",       "scrape_guokao.py --transport",    仅周日),
]
```

### 定时任务配置

```powershell
# 自动创建 Windows 定时任务
D:\Python\python.exe D:\hanako\job-board\daily_update.py --quick

# 或通过 HanaAgent cron 工具
cron add "0 9 * * *" "校招数据每日自动更新"
```

### 日志与监控

- 日志文件：`daily_update.log`
- 微信推送：每天 9:05 通知更新结果
- 每个子任务独立捕获异常，一个失败不影响其他

## 六、完整数据架构

```
job-board/
├── index.html                   ← 三标签页前端（校招/国考/招聘会）
├── daily_update.py              ← 每日编排器
│
├── 爬虫脚本
│   ├── scraper.py               ← 山东省国资委 + 人社厅
│   ├── scrape_yingjiesheng.py   ← 应届生求职网（20 关键词）
│   ├── scrape_haitou.py         ← 海投网交通类
│   ├── scrape_weibo.py          ← 微博 27 关键词
│   ├── scrape_university.py     ← 高校就业平台
│   ├── scrape_guokao.py         ← 国考中公职位库
│   └── enrich.py                ← 应届生数据二次校对
│
├── data/
│   ├── jobs.js                  ← 国资委
│   ├── jobs_yingjiesheng.js     ← 应届生求职网
│   ├── jobs_haitou.js           ← 海投网
│   ├── jobs_manual.js           ← 手动维护
│   ├── exams.js                 ← 国考职位
│   ├── weibo_events.js          ← 微博招聘会
│   └── university_events.js     ← 高校官方招聘会
│
└── GitHub 参考项目
    ├── Auto-JobHunter-main/     ← 反爬技巧参考
    ├── Spider_XHS-master/       ← 小红书（未成功）
    ├── crawl4weibo-main/        ← 微博依赖库
    └── wechat-article-exporter/ ← 公众号导出工具
```

## 七、当前数据覆盖

| 视图 | 来源 | 条数 |
|---|---|---|
| 🏢 校招/社招 | 国资委 + 应届生 + 海投网 + 手动 | 601 |
| 📋 国考/省考 | 中公职位库（铁路/海事/水利） | 3,884 |
| 📢 招聘会 | 微博 27 关键词 + 济南大学官方 | 20（近两周） |

## 八、可补充的方向

- **国考 Excel 解析器**：每年 10 月国家公务员局发布职位表 Excel，写脚本自动解析并填充 `exams.js`
- **省考爬虫**：山东省人事考试网每年 11 月发布省考职位表
- **山东大学就业平台适配**：`jobcareer.sdu.edu.cn` 独立系统，有结构化双选会数据
- **云就业平台适配**：山东建筑大学等使用 `bysjy.com.cn`，需单独写适配器
- **数据过期可视化**：在网页上对 deadline 已过的校招条目自动标灰/折叠
- **专业匹配功能**：录入用户专业，自动高亮匹配的岗位
- **企业官网直达**：从二手数据溯源到企业官方招聘页面，提高准确度

## 九、补充经验

### 增量 vs 全量策略

| 数据源 | 策略 | 原因 |
|---|---|---|
| 国资委 | 全量覆盖 | 数据量小（<100），每次重抓开销低 |
| 应届生/海投网 | 全量覆盖 | 搜索 API 不保证去重，全量+哈希去重更可靠 |
| 微博 | 全量覆盖 | 搜索结果随时间变化，旧数据自然过期 |
| 国考 | 仅周日全量 | 数据变动频率极低 |

### 失败恢复

```
单个爬虫失败 → 记录日志 + 微信通知 → 不影响其他爬虫
连续 3 天失败 → 标记为「需人工检查」（Cookie 过期/网站改版）
全量失败 → 保留上一次成功的数据文件，不覆盖空文件
```

### Cookie/登录态维护

```
小红书：需手动扫码，登录态约 2 小时过期 ← 不适合自动化
微博：crawl4weibo 自动管理，无需人工干预 ✅
国资委/高校：无需登录 ✅
需要登录的平台除非有自动续期方案，否则不建议加入每日自动更新
```

### 数据源冲突处理

当同一岗位出现在多个数据源时，网页端不做合并，各源独立显示。理由是：
- 不同源的字段完整度不同（国资委有公告链接、应届生有详细描述）
- 用户可以交叉验证（二次校对脚本 `enrich.py` 正是做这个）
- 去重合并会丢失来源信息

### 如何手动添加岗位

编辑 `jobs_manual.js`，复制一条现有记录，改字段即可：

```javascript
{
    id: 9999,
    companyName: "公司名",
    companyType: "央国企/民企/外企/事业单位",
    industry: "港口/航运",
    recruitType: "春招/实习/秋招",
    targetYears: "2027届",
    location: "济南",
    positions: "岗位名称",
    status: "未投递",
    updateTime: "2026-06-01",
    deadline: "2026-06-30",
    applyLink: "https://...",
    noticeLink: "https://...",
    examInfo: "笔试+面试",
    companyScale: "大型（万人以上）",
    notes: "手动添加"
}
```

手动数据文件永不被子爬虫覆盖。

