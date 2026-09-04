#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从原始数据源生成国企校招、编制招录和待处理三个派生列表。

原始 data/jobs_*.js 与 exams.js 始终只读；本脚本只写 board_*.js。
个人资格保存在 Git 忽略的 USER_PROFILE.local.md，派生文件不写入个人资料。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROFILE_FILE = BASE_DIR / "USER_PROFILE.local.md"

TARGET_YEAR = "2027"
DIRECT_MAJOR_TERMS = ("0861", "交通运输", "道路交通运输", "不限专业", "专业不限")
RELATED_MAJOR_TERMS = (
    "0823", "交通运输工程", "物流", "供应链", "交通工程", "交通规划",
    "运输工程", "轨道交通", "城市轨道交通", "工程管理",
)
LIKELY_SOE_TERMS = (
    "中交", "中铁", "中国铁路", "中国邮政", "中国物流集团", "招商局", "国铁",
    "铁路局", "轨道交通集团", "地铁集团", "高速集团", "港口集团", "城投",
    "城市建设集团", "产发", "国有资本", "公用控股", "交通投资", "交投集团",
    "水务集团", "公交集团", "机场集团", "航空工业", "航天科技", "兵器工业",
)
HARD_WORK_PATTERNS = (
    "倒班", "轮班", "夜班", "一线运营", "长期驻站", "驻矿", "野外作业",
    "项目驻地", "乡镇基层服务", "长期外派", "偏远地区分配",
)
OFFICIAL_DOMAINS = (
    "gov.cn", "shandong.gov.cn", "sd-port.com", "sdhsg.com", "china-railway.com.cn",
    "mohrss.gov.cn", "iguopin.com", "sasac.gov.cn",
    "ncss.cn",
)


@dataclass(frozen=True)
class SourceSpec:
    filename: str
    variable: str
    source: str
    kind: str  # soe / public / lead
    evidence: str


SOURCES = (
    SourceSpec("jobs.js", "JOBS", "山东省国资委", "soe", "官方"),
    SourceSpec("jobs_qyzp.js", "JOBS_QYZP", "央企招聘公告", "soe", "官方"),
    SourceSpec("jobs_ncss_soe.js", "JOBS_NCSS_SOE", "国家大学生就业服务平台国企专题", "soe", "官方"),
    SourceSpec("jobs_sasac_central.js", "JOBS_SASAC_CENTRAL", "国务院国资委人才招聘", "soe", "官方"),
    SourceSpec("jobs_sdhsg.js", "JOBS_SDHSG", "山东高速", "soe", "官方"),
    SourceSpec("jobs_sdport.js", "JOBS_SDPORT", "山东港口", "soe", "官方"),
    SourceSpec("jobs_railway.js", "JOBS_RAILWAY", "中国铁路人才招聘网", "soe", "官方"),
    SourceSpec("jobs_local_soe.js", "JOBS_LOCAL_SOE", "济南地方国企官方招聘", "soe", "官方"),
    SourceSpec("jobs_institutions.js", "JOBS_INSTITUTIONS", "中国公共招聘网事业单位", "public", "官方"),
    SourceSpec("jobs_yingjiesheng.js", "JOBS_YINGJIESHENG", "应届生求职网", "lead", "第三方线索"),
    SourceSpec("jobs_haitou.js", "JOBS_HAITOU", "海投网", "lead", "第三方线索"),
    SourceSpec("jobs_manual.js", "JOBS_MANUAL", "手动维护", "lead", "待核验"),
)


def load_js_array(path: Path, variable: str) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"const\s+{re.escape(variable)}\s*=\s*(\[.*\]);", text, re.DOTALL)
    if not match:
        return []
    payload = re.sub(r'(?m)^(\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', match.group(1))
    return json.loads(payload)


def write_js(path: Path, variable: str, title: str, records: list[dict]) -> None:
    header = (
        f"// {title} — 由 build_personal_board.py 生成\n"
        f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"// 共 {len(records)} 条\n\nconst {variable} = "
    )
    path.write_text(header + json.dumps(records, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def combined_text(item: dict) -> str:
    keys = (
        "companyName", "industry", "recruitType", "targetYears", "location", "positions",
        "notes", "majorReq", "educationReq", "politicalStatus", "workExp", "examInfo",
    )
    return " | ".join(str(item.get(key) or "") for key in keys)


def explicit_target_year(text: str) -> bool:
    return bool(re.search(r"(?:2027|27)\s*(?:届|年毕业)", text))


def has_other_explicit_cohort(text: str) -> bool:
    years = set(re.findall(r"20(2[4-9])\s*届", text))
    years.update(re.findall(
        r"20(2[4-9])\s*(?:年度?|年)?[^|。；]{0,10}(?:春季|秋季|校园|高校毕业生)?招聘",
        text,
    ))
    return bool(years) and "27" not in years


def is_graduate_recruitment(text: str) -> bool:
    """国企正式栏只要求属于应届毕业生或校园招聘，不再限定具体届次。"""
    return explicit_target_year(text) or any(term in text for term in (
        "应届", "校园招聘", "校招", "高校毕业生", "毕业生招聘", "毕业生招录", "管培生",
    ))


def parse_date(value: object) -> date | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})", str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def is_expired(item: dict) -> bool:
    for key in ("deadline", "registrationEnd"):
        parsed = parse_date(item.get(key))
        if parsed:
            return parsed < date.today()
    updated = parse_date(item.get("updateTime"))
    if updated and (date.today() - updated).days > 180 and not explicit_target_year(combined_text(item)):
        return True
    return False


def hard_exclusion_reasons(item: dict, kind: str) -> list[str]:
    text = combined_text(item)
    reasons: list[str] = []
    if is_expired(item):
        reasons.append("已截止")
    if "社招" in text and not any(term in text for term in ("校招", "应届", "校园招聘")):
        reasons.append("纯社会招聘")
    if kind == "public" and has_other_explicit_cohort(text) and not explicit_target_year(text):
        reasons.append("不面向目标届别")
    if re.search(r"(?:须|限|要求)[^。；|]{0,12}(?:中共)?党员", text) and "党员优先" not in text:
        reasons.append("党员硬性限制")
    if re.search(r"(?:仅限|限)[^。；|]{0,5}女(?:性)?", text):
        reasons.append("性别硬性限制")
    if any(pattern in text for pattern in HARD_WORK_PATTERNS):
        reasons.append("工作形态硬性排除")
    if re.search(r"(?:2|两)年(?:及以上|以上)?(?:工作|基层|相关工作)", text):
        reasons.append("要求两年及以上经历")
    if any(term in text for term in ("初次就业", "从未就业", "从未缴纳职工社保")):
        reasons.append("初次就业限制")
    if "博士" in str(item.get("educationReq") or "") and not any(
        term in str(item.get("educationReq") or "") for term in ("硕士", "本科")
    ):
        reasons.append("仅限博士")
    if kind == "lead":
        company_type = str(item.get("companyType") or "")
        company = str(item.get("companyName") or "")
        if any(term in text for term in ("民企", "外企", "中外合资")):
            reasons.append("非国企")
        elif "央国企" not in company_type and not any(term in company for term in LIKELY_SOE_TERMS):
            reasons.append("企业性质无国企线索")
    return sorted(set(reasons))


def major_fit(item: dict, public_strict: bool = False) -> tuple[str, str]:
    major = str(item.get("majorReq") or "").strip()
    text = major or " | ".join(str(item.get(k) or "") for k in ("positions", "notes"))
    direct_text = text
    for related in ("交通运输工程", "交通工程", "物流", "供应链"):
        direct_text = direct_text.replace(related, "")
    if any(term in direct_text for term in DIRECT_MAJOR_TERMS):
        return "已确认适配", "专业要求含目标专业、上级专业或不限专业" if major else "标题或说明含目标专业线索"
    if any(term in text for term in RELATED_MAJOR_TERMS):
        if public_strict:
            return "待核验", "公务员专业代码或官方目录需人工核验"
        return "可尝试", "专业名称或范围相近"
    return "待核验", "尚未取得可验证的专业要求"


def evidence_level(item: dict, spec: SourceSpec) -> str:
    links = [str(item.get("noticeLink") or ""), str(item.get("applyLink") or "")]
    if spec.evidence == "官方" and any(
        any(domain in urlparse(link).netloc for domain in OFFICIAL_DOMAINS) for link in links if link
    ):
        return "官方原文"
    return spec.evidence


def is_specific_position(item: dict) -> bool:
    position = str(item.get("positions") or item.get("position") or "").strip()
    if not position:
        return False
    announcement_terms = ("招聘公告", "校园招聘", "公开招聘", "招聘简章", "招聘启事", "人才招聘")
    return not any(term in position for term in announcement_terms)


def normalize_job(item: dict, spec: SourceSpec) -> dict:
    return {
        "id": f"{slug(spec.source)}_{item.get('id', '')}",
        "boardSection": "国企校招" if spec.kind in ("soe", "lead") else "国考/省考/事业编",
        "source": spec.source,
        "companyName": item.get("companyName") or item.get("department") or "",
        "companyType": item.get("companyType") or ("事业单位" if spec.kind == "public" else "央国企"),
        "industry": item.get("industry") or "",
        "recruitType": item.get("recruitType") or item.get("examType") or "",
        "targetYears": "2027届" if explicit_target_year(combined_text(item)) else (item.get("targetYears") or "待核验"),
        "location": item.get("location") or "",
        "positions": item.get("positions") or item.get("position") or "",
        "status": "新发现",
        "updateTime": item.get("updateTime") or "",
        "deadline": item.get("deadline") or item.get("registrationEnd") or "待核验",
        "applyLink": item.get("applyLink") or "",
        "noticeLink": item.get("noticeLink") or item.get("applyLink") or "",
        "examInfo": item.get("examInfo") or item.get("examDate") or "",
        "companyScale": item.get("companyScale") or "",
        "notes": item.get("notes") or "",
        "majorReq": item.get("majorReq") or "",
        "educationReq": item.get("educationReq") or "",
        "positionCode": item.get("positionCode") or "",
        "recruitmentCount": item.get("recruitmentCount") or "",
        "registrationStart": item.get("registrationStart") or "",
        "registrationEnd": item.get("registrationEnd") or item.get("deadline") or "",
        "examDate": item.get("examDate") or "",
        "competitionRatio": item.get("competitionRatio") or "",
        "pastScoreLine": item.get("pastScoreLine") or "",
        "actualEmployer": item.get("actualEmployer") or item.get("companyName") or "",
        "contractEmployer": item.get("contractEmployer") or "待核验",
        "employmentType": item.get("employmentType") or "待核验",
        "ownershipRelation": item.get("ownershipRelation") or "待核验",
        "ownershipEvidenceUrl": item.get("ownershipEvidenceUrl") or "",
    }


def slug(value: str) -> str:
    aliases = {
        "山东省国资委": "sasac", "央企招聘公告": "qyzp", "山东高速": "sdhsg",
        "山东港口": "sdport", "中国铁路人才招聘网": "railway",
        "中国公共招聘网事业单位": "institution", "应届生求职网": "yingjiesheng",
        "济南地方国企官方招聘": "jinan_local_soe",
        "海投网": "haitou", "手动维护": "manual", "国考职位库": "exam",
    }
    return aliases.get(value, re.sub(r"\W+", "_", value).strip("_").lower())


def source_links(record: dict) -> list[str]:
    return list(dict.fromkeys(link for link in (record.get("noticeLink"), record.get("applyLink")) if link))


def priority_score(record: dict) -> int:
    score = 0
    location = str(record.get("location") or "")
    if "济南" in location:
        score += 50
    elif "山东" in location:
        score += 35
    elif any(city in location for city in ("沧州", "衡水", "邢台", "邯郸", "濮阳", "安阳", "新乡", "徐州", "连云港", "宿迁", "宿州", "淮北")):
        score += 25
    score += {"已确认适配": 30, "可尝试": 20, "待核验": 0}.get(record.get("fitLevel"), 0)
    count = record.get("recruitmentCount")
    try:
        score += min(int(count), 10)
    except (TypeError, ValueError):
        pass
    deadline = parse_date(record.get("deadline"))
    if deadline:
        days = (deadline - date.today()).days
        if 3 <= days <= 14:
            score += 20
        elif 0 <= days < 3:
            score += 10
    return score


def canonical_key(record: dict) -> tuple[str, ...]:
    clean = lambda value: re.sub(r"\s+", "", str(value or "")).lower()
    return tuple(clean(record.get(key)) for key in ("companyName", "positions", "location", "deadline"))


def merge_record(existing: dict, incoming: dict) -> dict:
    evidence_rank = {"官方原文": 3, "官方": 2, "待核验": 1, "第三方线索": 0}
    primary, secondary = (incoming, existing) if evidence_rank.get(incoming.get("evidenceLevel"), 0) > evidence_rank.get(existing.get("evidenceLevel"), 0) else (existing, incoming)
    merged = dict(primary)
    for key, value in secondary.items():
        if not merged.get(key) and value:
            merged[key] = value
    merged["sourceLinks"] = list(dict.fromkeys(existing.get("sourceLinks", []) + incoming.get("sourceLinks", [])))
    merged["discoverySources"] = sorted(set(existing.get("discoverySources", []) + incoming.get("discoverySources", [])))
    merged["reviewReasons"] = sorted(set(existing.get("reviewReasons", []) + incoming.get("reviewReasons", [])))
    return merged


def classify_record(item: dict, spec: SourceSpec) -> tuple[str, dict]:
    record = normalize_job(item, spec)
    exclusions = hard_exclusion_reasons(item, spec.kind)
    record["exclusionReasons"] = exclusions
    if exclusions:
        record["status"] = "已排除"
        return "excluded", record

    public_strict = spec.kind == "public" and str(item.get("examType") or "") in ("国考", "省考")
    fit, fit_reason = major_fit(item, public_strict=public_strict)
    record["fitLevel"] = fit
    record["fitReason"] = fit_reason
    record["evidenceLevel"] = evidence_level(item, spec)
    record["sourceLinks"] = source_links(record)
    record["discoverySources"] = [spec.source]

    review_reasons = []
    if spec.kind == "lead":
        review_reasons.append("第三方来源仅作线索，需反查官方原文和国企控制关系")
    if record["evidenceLevel"] != "官方原文":
        review_reasons.append("缺少可验证的官方原文")
    if spec.kind == "soe":
        # 国企正式栏采用宽口径：官方证据 + 应届/校招属性即可。
        # 具体岗位、专业匹配和明确截止日期仍展示，但不再作为入栏门槛。
        if not is_graduate_recruitment(combined_text(item)):
            review_reasons.append("应届毕业生或校园招聘属性尚未确认")
    else:
        if not is_specific_position(item):
            review_reasons.append("当前为公告级记录，职位表尚未拆分")
        if fit == "待核验":
            review_reasons.append(fit_reason)
        if not explicit_target_year(combined_text(item)):
            review_reasons.append("目标届别尚未明确确认")
        if not record.get("deadline") or record.get("deadline") in ("待核验", "以公告为准", "招满为止"):
            review_reasons.append("明确截止日期待核验")
    record["reviewReasons"] = sorted(set(review_reasons))
    record["priorityScore"] = priority_score(record)

    if review_reasons:
        record["status"] = "待处理"
        return "review", record
    return ("public" if spec.kind == "public" else "soe"), record


def iter_exam_records() -> list[tuple[dict, SourceSpec]]:
    spec = SourceSpec("exams.js", "EXAMS", "国考职位库", "public", "第三方线索")
    return [(item, spec) for item in load_js_array(DATA_DIR / spec.filename, spec.variable)]


def main() -> None:
    if not PROFILE_FILE.exists():
        raise FileNotFoundError("缺少本地 USER_PROFILE.local.md，拒绝生成个性化看板")

    buckets: dict[str, list[dict]] = {"soe": [], "public": [], "review": [], "excluded": []}
    records_with_specs: list[tuple[dict, SourceSpec]] = []
    for spec in SOURCES:
        records_with_specs.extend((item, spec) for item in load_js_array(DATA_DIR / spec.filename, spec.variable))
    records_with_specs.extend(iter_exam_records())

    merged: dict[tuple[str, ...], tuple[str, dict]] = {}
    for item, spec in records_with_specs:
        bucket, record = classify_record(item, spec)
        key = canonical_key(record)
        if key in merged:
            old_bucket, old_record = merged[key]
            merged_record = merge_record(old_record, record)
            if merged_record.get("exclusionReasons"):
                merged_bucket = "excluded"
            elif "review" in (old_bucket, bucket):
                merged_bucket = "review"
            else:
                merged_bucket = old_bucket
            merged[key] = (merged_bucket, merged_record)
        else:
            merged[key] = (bucket, record)

    for bucket, record in merged.values():
        buckets[bucket].append(record)
    for name in buckets:
        buckets[name].sort(key=lambda row: (-int(row.get("priorityScore") or 0), str(row.get("deadline") or "9999"), str(row.get("companyName") or "")))

    write_js(DATA_DIR / "board_soe.js", "SOE_JOBS", "国企校招岗位", buckets["soe"])
    write_js(DATA_DIR / "board_public.js", "PUBLIC_JOBS", "国考省考事业编岗位", buckets["public"])
    write_js(DATA_DIR / "board_review.js", "REVIEW_JOBS", "待人工核验队列", buckets["review"])
    (BASE_DIR / ".board_excluded.json").write_text(
        json.dumps(buckets["excluded"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {name: len(rows) for name, rows in buckets.items()}
    print("个性化看板生成完成: " + ", ".join(f"{name}={count}" for name, count in summary.items()))


if __name__ == "__main__":
    main()
