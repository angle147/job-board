#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
每日校招数据更新编排器
======================
协调所有爬虫按顺序执行，记录日志。
用法：
    python daily_update.py                 # 全量更新
    python daily_update.py --quick         # 仅校招（跳过国考和校对）

Windows 定时任务：
    任务计划程序 → 创建基本任务 → 每天 9:00 执行
    程序: D:\Python\python.exe
    参数: D:\hanako\job-board\daily_update.py
    起始于: D:\hanako\job-board
"""

import subprocess
import sys
import os
import json
import urllib.request
import shutil
from datetime import datetime
from pathlib import Path

PYTHON = r"D:\Python\python.exe"
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "daily_update.log"
LOCK_FILE = BASE_DIR / ".daily_update.lock"

# 强制 UTF-8 编码，避免 subprocess 管道使用 GBK 导致 emoji 报错
# 定时任务继承到的系统代理可能指向已停用端口；统一使用工作区 mihomo。
# 子脚本仍可自行选择直连，但不得因失效的环境代理把采集结果覆盖为空。
ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
    "HTTP_PROXY": "http://127.0.0.1:7890",
    "HTTPS_PROXY": "http://127.0.0.1:7890",
    "ALL_PROXY": "",
}

SCRAPERS = [
    {
        "name": "山东省国资委",
        "script": "scraper.py",
        "args": ["--source", "sasac", "--max-pages", "2", "--details", "10"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "央企招聘公告",
        "script": "scrape_mohrss_qyzp.py",
        "args": [],
        "daily": True,
        "timeout": 60,
    },
    {
        "name": "山东高速招聘公告",
        "script": "scrape_sdhsg.py",
        "args": [],
        "daily": True,
        "timeout": 90,
    },
    {
        "name": "山东港口人才需求",
        "script": "scrape_sdport.py",
        "args": [],
        "daily": True,
        "timeout": 90,
    },
    {
        "name": "中国铁路人才招聘网",
        "script": "scrape_railway.py",
        "args": ["--pages", "2", "--page-size", "20"],
        "daily": True,
        "timeout": 120,
    },
    {
        "name": "中国公共招聘网事业单位",
        "script": "scrape_institutions.py",
        "args": ["--max-age", "180"],
        "daily": True,
        "timeout": 60,
    },
    {
        "name": "应届生求职网",
        "script": "scrape_yingjiesheng.py",
        "args": ["--max-pages", "1"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "海投网交通类",
        "script": "scrape_haitou.py",
        "args": ["--max-pages", "3"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "应届生数据校对",
        "script": "enrich.py",
        "args": ["--source", "yingjiesheng"],
        "daily": True,
        "timeout": 300,
    },
    {
        "name": "51job 爬虫采集",
        "script": "run_51job_collector.py",
        "args": [],
        "daily": True,
        "enabled": False,
        "status_reason": "依赖的 D:\\hanako\\Auto-JobHunter-main 已不存在，且原采集多次超过 3 分钟；保持禁用",
        "timeout": 180,
    },
    {
        "name": "51job 数据导出+清理",
        "script": "scrape_51job.py",
        "args": [],
        "daily": True,
        "enabled": False,
        "status_reason": "依赖的 Auto-JobHunter SQLite 数据库已不存在；保持禁用",
        "timeout": 60,
    },
    {
        "name": "过期岗位清理",
        "script": "cleanup_expired_jobs.py",
        "args": [],
        "daily": True,
        "timeout": 60,
    },
    {
        "name": "济南线下招聘活动",
        "script": "scrape_offline_events.py",
        "args": ["--max-details", "120"],
        "daily": True,
        "timeout": 600,
    },
    {
        "name": "国考交通职位",
        "script": "scrape_guokao.py",
        "args": ["--transport-only", "--max-pages-per-dept", "2"],
        "daily": False,  # 仅周日执行
        "timeout": 300,
    },
    {
        "name": "微博校园招聘会",
        "script": "scrape_weibo.py",
        "args": ["--max-pages", "1"],
        "daily": True,
        "enabled": False,
        "status_reason": "公开搜索依赖浏览器临时 Cookie，27 个关键词历史上频繁超过 2 分钟；保持禁用",
        "pipe_safe": False,
        "timeout": 120,  # 微博容易超时，2分钟为限
    },
    {
        "name": "生成个性化国企与编制看板",
        "script": "build_personal_board.py",
        "args": [],
        "daily": True,
        "timeout": 120,
    },
]


WEIBO_LOG = BASE_DIR / "weibo_output.log"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_scraper(name: str, script: str, args: list[str], pipe_safe: bool = True, timeout: int = 180) -> bool:
    cmd = [PYTHON, str(BASE_DIR / script)] + args
    log(f"▶ 开始: {name}")
    log(f"  命令: {' '.join(cmd)}")

    try:
        if pipe_safe:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=timeout, cwd=str(BASE_DIR),
                                    encoding="utf-8", errors="replace",
                                    env=ENV)
            stdout = result.stdout
        else:
            # 输出到文件，避免 PIPE 死锁
            with open(WEIBO_LOG, "w", encoding="utf-8") as log_f:
                result = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                        timeout=timeout, cwd=str(BASE_DIR),
                                        env=ENV)
            # 读回最后几行
            with open(WEIBO_LOG, "r", encoding="utf-8") as log_f:
                stdout = log_f.read()

        # 输出最后几行到日志
        for line in stdout.strip().split("\n")[-5:]:
            if line.strip():
                log(f"  {line.strip()[:120]}")

        if result.returncode != 0:
            log(f"❌ {name} 失败 (code={result.returncode})")
            if result.stderr.strip():
                log(f"  错误: {result.stderr.strip()[:200]}")
            return False

        log(f"✅ {name} 完成")
        return True

    except subprocess.TimeoutExpired:
        log(f"⏰ {name} 超时（>{timeout // 60}分钟），已跳过")
        return False
    except Exception as e:
        log(f"💥 {name} 异常: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="仅校招，跳过校对和国考")
    parser.add_argument("--push-only", action="store_true", help="只重试发送现有摘要，不运行采集与 Git 同步")
    args = parser.parse_args()

    if args.push_only:
        if not SUMMARY_FILE.exists():
            log("⚠️ 摘要文件不存在，无法补发飞书")
            return
        if should_push_today():
            if push_feishu(SUMMARY_FILE.read_text(encoding="utf-8")):
                mark_pushed()
        else:
            log("⏭ 今日已成功推送过飞书，无需补发")
        return

    # 锁文件：防止重复运行，同时记录 PID
    if LOCK_FILE.exists():
        try:
            old_content = LOCK_FILE.read_text().strip()
            # 检查旧进程是否还活着
            if ':' in old_content:
                old_pid = int(old_content.split(':')[-1])
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, old_pid)  # PROCESS_QUERY_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    lock_age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
                    if lock_age < 1800:
                        log("⏭ 已有运行中的更新任务，跳过")
                        return
            # 进程已死但锁还在
        except (ValueError, OSError):
            pass
        log("⚠️ 发现过期锁文件（进程已死或>30分钟），强制继续")
    LOCK_FILE.write_text(f"{datetime.now()}:{os.getpid()}")

    try:
        _run_pipeline(args)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def _run_pipeline(args):
    log("=" * 50)
    log("🚀 每日更新开始")
    log("=" * 50)

    today = datetime.now()
    is_sunday = today.weekday() == 6  # 周日

    success = 0
    fail = 0

    for scraper in SCRAPERS:
        # 禁用的数据源（enabled=False）直接跳过
        if not scraper.get("enabled", True):
            reason = scraper.get("status_reason", "未说明原因")
            log(f"⏭ 跳过: {scraper['name']}（已禁用：{reason}）")
            continue

        # 非周日跳过国考
        if not scraper["daily"] and not is_sunday:
            log(f"⏭ 跳过: {scraper['name']}（仅周日执行）")
            continue

        # quick 模式跳过校对和国考
        if args.quick and not scraper["daily"]:
            continue
        if args.quick and scraper["name"] == "应届生数据校对":
            continue

        if run_scraper(scraper["name"], scraper["script"], scraper["args"],
                       pipe_safe=scraper.get("pipe_safe", True),
                       timeout=scraper.get("timeout", 180)):
            success += 1
        else:
            fail += 1

        # 每完成一个爬虫就更新摘要（即使后续失败也有数据可用）
        _write_incremental_summary()

    log(f"📊 完成: {success} 成功, {fail} 失败, 共 {success + fail} 个任务")

    sync_github()

    log("")

    # 自动同步到 GitHub Pages（增量摘要已在每个爬虫后写入）
    # 最终摘要已在增量写入中完成，这里做最后一次确认
    _write_incremental_summary()

    push_pipeline_notifications()


def _find_git() -> str | None:
    """定位 git.exe；任务计划程序的 PATH 通常不含 Git。"""
    found = shutil.which("git")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
        Path.home() / "AppData/Local/Programs/Git/cmd/git.exe",
    ]
    runtime_root = Path.home() / ".cache/codex-runtimes"
    if runtime_root.exists():
        candidates.extend(sorted(runtime_root.glob("*/dependencies/native/git/cmd/git.exe"), reverse=True))
    return str(next((p for p in candidates if p.exists()), "")) or None


def sync_github(dry_run: bool = False) -> bool:
    """同步数据到 GitHub；返回可供独立验证的成功状态。"""
    log("> 开始: GitHub 同步" + ("（dry-run）" if dry_run else ""))
    git = _find_git()
    if not git:
        log("⚠️ GitHub 同步失败: 未找到 git.exe；请安装 Git for Windows 或配置 PATH")
        return False
    base = [git, "-c", f"safe.directory={BASE_DIR}"]
    try:
        if dry_run:
            push_result = subprocess.run(
                base + ["push", "--dry-run", "origin", "main"], capture_output=True, text=True,
                timeout=120, cwd=str(BASE_DIR), env=ENV, encoding="utf-8", errors="replace")
            if push_result.returncode == 0:
                log("✅ GitHub 同步 dry-run 通过（git.exe、仓库与 remote 均可用）")
                return True
            log(f"⚠️ GitHub push dry-run 失败: {push_result.stderr.strip()[:160]}")
            return False
        add_result = subprocess.run(
            base + ["add", "data/", "index.html"],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), env=ENV,
            encoding="utf-8", errors="replace"
        )
        if add_result.returncode != 0:
            log(f"⚠️ Git add 失败: {add_result.stderr.strip()[:160]}")
            return False
        commit_result = subprocess.run(
            base + ["commit", "-m", f"📊 每日更新 {datetime.now().strftime('%Y-%m-%d')}"],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), env=ENV,
            encoding="utf-8", errors="replace"
        )
        if commit_result.returncode == 0 or "nothing to commit" in commit_result.stdout + commit_result.stderr:
            push_result = subprocess.run(
                base + ["push", "origin", "main"],
                capture_output=True, text=True,
                timeout=120, cwd=str(BASE_DIR), env=ENV,
                encoding="utf-8", errors="replace"
            )
            if push_result.returncode == 0:
                log("✅ GitHub 同步完成 → https://angle147.github.io/job-board/")
                return True
            else:
                log(f"⚠️ GitHub push 失败: {push_result.stderr.strip()[:120]}")
        else:
            log(f"⚠️ Git commit 异常: {commit_result.stderr.strip()[:120]}")
    except Exception as e:
        log(f"⚠️ GitHub 同步异常: {e}")
    return False


def _build_summary(base_dir, today):
    """统计个性化看板条目数，生成不含个人画像内容的推送文案。"""
    import json, re
    from pathlib import Path
    data_dir = base_dir / "data"

    def count_js(path):
        if not path.exists():
            return 0
        text = path.read_text(encoding="utf-8")
        # 数数组里的 { 数量
        return text.count('\n  {') 

    lines = []
    lines.append(f"📬 国企与编制机会已更新 ({today.strftime('%m-%d')})")
    lines.append("")
    soe_count = count_js(data_dir / "board_soe.js")
    public_count = count_js(data_dir / "board_public.js")
    review_count = count_js(data_dir / "board_review.js")
    lines.append(f"🏢 国企校招（已核验）: {soe_count} 条")
    lines.append(f"🏛 国考 / 省考 / 事业编（已核验）: {public_count} 条")
    lines.append(f"🔎 待处理线索: {review_count} 条")

    urgent_review = 0
    review_path = data_dir / "board_review.js"
    if review_path.exists():
        text = review_path.read_text(encoding="utf-8")
        urgent_review = len(re.findall(r'"priorityScore"\s*:\s*(?:[7-9]\d|\d{3,})', text))
    lines.append(f"⚡ 紧急人工核验: {urgent_review} 条")
    if soe_count + public_count == 0:
        lines.append("  当前没有证据完整且确认适配的正式岗位")
    lines.append("")

    event_count = count_js(data_dir / "offline_events.js")
    lines.append(f"📅 济南线下招聘: {event_count} 场")
    health_path = base_dir / ".offline_source_health.json"
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text(encoding="utf-8"))
            source_states = [value for key, value in health.items() if key != "_meta" and isinstance(value, dict)]
            healthy = sum(1 for value in source_states if value.get("lastSuccessAt"))
            alerted = sum(1 for value in source_states if int(value.get("consecutiveFailures", 0)) >= 3)
            lines.append(f"  来源成功覆盖: {healthy}/{len(source_states)}")
            if alerted:
                lines.append(f"  ⚠ 连续失败来源: {alerted} 个")
        except Exception:
            pass
    lines.append("")

    # 过期清理统计（从日志最后一段提取）
    log_file = base_dir / "daily_update.log"
    if log_file.exists():
        log_text = log_file.read_text(encoding="utf-8")
        # 找最后一次过期清理结果
        m = re.search(r'总计: 删除 (\d+) 条, 保留 (\d+) 条', log_text)
        if m:
            lines.append(f"🧹 过期清理: 删 {m.group(1)} 条, 保留 {m.group(2)} 条")

    lines.append("")
    lines.append("📱 https://angle147.github.io/job-board/")

    return '\n'.join(lines)


SUMMARY_FILE = BASE_DIR / ".daily_summary.txt"
OFFLINE_REMINDER_FILE = BASE_DIR / ".offline_event_reminders.json"


def _load_feishu_cfg():
    cfg_file = BASE_DIR / "feishu_config.json"
    if not cfg_file.exists():
        return None
    try:
        return json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        return None


PUSH_DATE_FILE = BASE_DIR / ".last_push_date.txt"


def should_push_today():
    """当天是否还未推送过（上午推过则下午跳过）"""
    if not PUSH_DATE_FILE.exists():
        return True
    try:
        return PUSH_DATE_FILE.read_text(encoding="utf-8").strip() != datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return True


def mark_pushed():
    PUSH_DATE_FILE.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")


def _load_offline_events():
    path = BASE_DIR / "data" / "offline_events.js"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text[text.index("["):text.rindex("]") + 1])
    except Exception:
        return []


def _load_reminder_state():
    if not OFFLINE_REMINDER_FILE.exists():
        return {}
    try:
        return json.loads(OFFLINE_REMINDER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _offline_notifications(now):
    """返回活动提醒正文、成功发送后应保存的状态。"""
    state = _load_reminder_state()
    next_state = json.loads(json.dumps(state))
    blocks = []
    morning = now.hour < 12
    today = now.date()
    for event in sorted(_load_offline_events(), key=lambda item: (item.get("startDate", ""), item.get("timeText", ""))):
        try:
            event_date = datetime.strptime(event["startDate"], "%Y-%m-%d").date()
        except Exception:
            continue
        if event_date < today:
            continue
        event_id = event.get("id")
        if not event_id:
            continue
        saved = next_state.setdefault(event_id, {"sent": [], "exhibitorStatus": ""})
        sent = set(saved.get("sent", []))
        reasons = []
        if "new" not in sent:
            reasons.append("新发现")
            sent.add("new")
        current_exhibitor = event.get("exhibitorStatus", "企业名单未公布")
        if (saved.get("exhibitorStatus") in ("", "企业名单未公布")
                and current_exhibitor != "企业名单未公布" and "exhibitor" not in sent):
            reasons.append("企业名单公布")
            sent.add("exhibitor")
        days_left = (event_date - today).days
        if morning and days_left in (7, 3, 1, 0):
            key = f"d{days_left}"
            if key not in sent:
                reasons.append("今天开展" if days_left == 0 else f"提前 {days_left} 天")
                sent.add(key)
        if reasons:
            exhibitor = current_exhibitor
            if event.get("exhibitorUrl"):
                exhibitor += f": {event['exhibitorUrl']}"
            blocks.append("\n".join([
                f"📍 {event.get('organizer', '')}｜{event.get('eventType', '')}",
                f"{event.get('title', '')}",
                f"🕒 {event.get('startDate', '')} {event.get('timeText', '')}",
                f"🏫 {event.get('location', '')}",
                f"🏢 {exhibitor}",
                f"🔗 {event.get('sourceUrl', '')}",
                f"🔔 {'、'.join(reasons)}",
            ]))
        saved["sent"] = sorted(sent)
        saved["exhibitorStatus"] = current_exhibitor
        saved["lastSeenAt"] = now.isoformat(timespec="seconds")
    return blocks, next_state


def push_pipeline_notifications():
    """早间发送岗位摘要；早晚均可发送线下活动增量提醒。"""
    now = datetime.now()
    blocks, next_state = _offline_notifications(now)
    parts = []
    include_summary = should_push_today()
    if include_summary:
        parts.append(SUMMARY_FILE.read_text(encoding="utf-8"))
    if blocks:
        parts.append("📅 济南线下招聘提醒\n\n" + "\n\n".join(blocks))
    if not parts:
        log("⏭ 无新增活动或到期提醒，飞书不发送空消息")
        return
    if push_feishu("\n\n".join(parts)):
        if include_summary:
            mark_pushed()
        OFFLINE_REMINDER_FILE.write_text(json.dumps(next_state, ensure_ascii=False, indent=2), encoding="utf-8")


def push_feishu(text):
    """推送文本到飞书私聊；依次尝试稳定本地代理、环境代理和直连。"""
    cfg = _load_feishu_cfg()
    if not cfg or not cfg.get("app_secret"):
        log("⚠️ 无飞书配置（feishu_config.json 缺失），跳过推送")
        return False

    stable_proxy = "http://127.0.0.1:7890"
    channels = [
        ("mihomo:7890", urllib.request.build_opener(urllib.request.ProxyHandler({
            "http": stable_proxy, "https": stable_proxy,
        }))),
        ("环境代理", urllib.request.build_opener()),
        ("直连", urllib.request.build_opener(urllib.request.ProxyHandler({}))),
    ]
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    for channel_name, opener in channels:
        try:
            body = json.dumps({
                "app_id": cfg["app_id"], "app_secret": cfg["app_secret"],
            }).encode("utf-8")
            req = urllib.request.Request(
                token_url, data=body, headers={"Content-Type": "application/json"})
            token_resp = json.loads(opener.open(req, timeout=20).read().decode("utf-8"))
            token = token_resp.get("tenant_access_token")
            if not token:
                # 鉴权失败与网络通道无关，不继续重试，也不输出完整响应或凭据。
                log(f"⚠️ 飞书鉴权失败（code={token_resp.get('code', 'unknown')}）")
                return False

            content = json.dumps({"text": text})
            body2 = json.dumps({
                "receive_id": cfg["open_id"], "msg_type": "text", "content": content,
            }).encode("utf-8")
            req2 = urllib.request.Request(msg_url, data=body2, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {token}",
            })
            resp2 = json.loads(opener.open(req2, timeout=20).read().decode("utf-8"))
            if resp2.get("code") == 0:
                log(f"✅ 飞书推送成功（{channel_name}）")
                return True
            log(f"⚠️ 飞书推送失败（{channel_name}, code={resp2.get('code', 'unknown')}）")
            return False
        except Exception as e:
            log(f"⚠️ 飞书通道不可用（{channel_name}）: {type(e).__name__}: {str(e)[:120]}")

    log("❌ 飞书推送失败：所有网络通道均不可用")
    return False

def _write_incremental_summary():
    """每完成一个爬虫后更新摘要文件，确保 pipeline 被中断时也有数据"""
    summary = _build_summary(BASE_DIR, datetime.now())
    SUMMARY_FILE.write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
