#!/usr/bin/env python3
"""BB Deadline Notifier — Blackboard 截止日期邮件提醒（单文件，仅标准库）。

两种数据平面，自动降级：
  full  : sustech-cli (`bb deadlines --json`) —— 带课程名、可过滤已提交（全保真）
  ics   : Blackboard 日历 ICS feed —— 无需认证，永不挂（降级模式）

两种运行模式：
  escalate : 检查哪些作业进入了 48/24/12 小时提醒窗口，首次进入才发信（按状态去重）
  digest   : 每日汇总所有临近未提交作业（每天最多一封）

状态持久化在 state/sent.json（由 CI 回写仓库），邮件经 QQ 邮箱 SMTP 授权码发出。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

# ---------------------------------------------------------------- 配置

DEFAULTS = {
    "ICS_URL": "",                # Blackboard 日历 feed（secret）
    "SMTP_HOST": "smtp.qq.com",
    "SMTP_PORT": "465",
    "SMTP_USER": "",              # 发件 QQ 邮箱
    "SMTP_PASS": "",              # SMTP 授权码（不是邮箱密码）
    "FROM_ADDR": "",              # 信头 From 显示地址（如英文别名），默认同 SMTP_USER
    "MAIL_TO": "",                # 收件地址，默认同 SMTP_USER
    "FROM_NAME": "BB Deadline Bot",
    "SCHOOL_PASSWORD": "",        # 学校统一认证密码；留空 = 纯 ICS 模式
    "SUSTECH_SID": "",            # 学号（SCHOOL_PASSWORD 自动登录所需）
    "LOOKAHEAD_DAYS": "14",       # 汇总展望天数
    "TIER_HOURS": "48,24,12",     # 提醒分档（小时）
    "ENABLE_GRADES": "0",         # 出分提醒开关（仅全保真模式）
    "BB_DEADLINES_FIXTURE": "",   # 测试用：用 JSON 文件代替 CLI 输出
    "BB_GRADES_FIXTURE": "",      # 测试用：成绩数据
    "TEST_NOW": "",               # 测试用：伪造当前时间
}

STATE_PATH = Path(__file__).resolve().parent / "state" / "sent.json"
AUTH_BACKOFF_AFTER_FAILS = 3
AUTH_BACKOFF_HOURS = 12


def load_env() -> dict:
    cfg = dict(DEFAULTS)
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():  # 本地开发用；CI 全部走真实环境变量
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in DEFAULTS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def now(cfg: dict) -> dt.datetime:
    if cfg["TEST_NOW"]:
        return dt.datetime.fromisoformat(cfg["TEST_NOW"])
    return dt.datetime.now(tz=tz())


def tz() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Shanghai")
    except Exception:  # Windows 无 tzdata 时退回固定偏移（中国现行无夏令时）
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai+8")


def as_shanghai(naive: dt.datetime) -> dt.datetime:
    if naive.tzinfo is None:
        return naive.replace(tzinfo=tz())
    return naive.astimezone(tz())


# ---------------------------------------------------------------- ICS 数据平面

def fetch_ics(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "bb-deadline-notifier/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def unfold_ical(text: str) -> list[str]:
    """RFC5545 折行还原：续行以单个空格或制表符开头。"""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


GRADABLE_UID = re.compile(r"_blackboard\.platform\.gradebook2\.GradableItem-_(\d+)_")


def parse_ics(text: str) -> list[dict]:
    events, cur, in_event = [], None, False
    for line in unfold_ical(text):
        name, _, value = line.partition(":")
        prop = name.split(";", 1)[0].upper()
        params = name.split(";", 1)[1] if ";" in name else ""
        if prop == "BEGIN" and value.strip().upper() == "VEVENT":
            in_event, cur = True, {}
            continue
        if prop == "END" and value.strip().upper() == "VEVENT":
            if cur:
                events.append(cur)
            in_event, cur = False, None
            continue
        if not in_event or cur is None:
            continue  # 跳过 VTIMEZONE 等块（其中也有 DTSTART）
        if prop == "SUMMARY":
            cur["title"] = value.strip()
        elif prop == "UID":
            cur["uid"] = value.strip()
        elif prop == "DTSTART":
            cur["start"] = _parse_ical_dt(value.strip(), params)
    items = []
    for ev in events:
        start, title = ev.get("start"), ev.get("title", "(untitled)")
        if start is None:
            continue
        m = GRADABLE_UID.search(ev.get("uid", ""))
        item_id = f"bb-{m.group(1)}" if m else f"ics-{abs(hash((title, start.isoformat())))}"
        items.append({
            "id": item_id, "title": title, "course": None,
            "due": start, "submitted": None, "source": "ics",
        })
    return items


def _parse_ical_dt(value: str, params: str) -> dt.datetime | None:
    params = params.upper()
    if "VALUE=DATE" in params and re.fullmatch(r"\d{8}", value):
        return as_shanghai(dt.datetime.strptime(value, "%Y%m%d") + dt.timedelta(hours=23, minutes=59))
    if value.endswith("Z"):
        try:
            return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(tz())
        except ValueError:
            return None
    try:
        return as_shanghai(dt.datetime.strptime(value, "%Y%m%dT%H%M%S"))
    except ValueError:
        return None


# ---------------------------------------------------------------- 全保真数据平面（sustech-cli）

SUBMITTED_WORDS = ("submitted", "graded", "attempted", "needs_grading_complete", "complete")
NOT_SUBMITTED_WORDS = ("not_", "unsubmitted", "no_attempt", "none")


def looks_submitted(state) -> bool | None:
    """对 CLI 各种可能的提交状态字段做保守判断；判断不了返回 None（不过滤）。"""
    if state is None:
        return None
    if isinstance(state, bool):
        return state
    s = str(state).strip().lower()
    if not s:
        return None
    if any(w in s for w in NOT_SUBMITTED_WORDS):
        return False
    if any(w in s for w in SUBMITTED_WORDS):
        return True
    return None


def _iter_deadline_records(obj, inherited_course: str | None = None):
    """递归找出形似“作业条目”的 dict：含标题类字段 + 截止时间类字段。

    CLI 的 JSON schema 未固化，这里按字段名模糊匹配，宁可多识别再靠内容筛选。
    课程名常见于父级节点（如 {"courseName": ..., "items": [...]}），沿递归向下传递。
    """
    TITLE_KEYS = ("title", "name", "assignment", "assignmentName", "assignment_name", "display")
    DUE_KEYS = ("due", "dueAt", "due_at", "deadline", "dueDate", "due_date", "dueTime", "end")
    COURSE_KEYS = ("course", "courseName", "course_name", "courseId", "course_id",
                   "courseTitle", "course_title", "externalName")
    STATE_KEYS = ("submissionState", "submission_state", "submission", "status", "attempt",
                  "attempted", "submitted", "gradebookStatus")
    if isinstance(obj, dict):
        code = next((obj[k] for k in ("courseCode", "course_code") if isinstance(obj.get(k), str)), "")
        course = next((obj[k] for k in COURSE_KEYS if isinstance(obj.get(k), str) and obj.get(k)),
                      None) or inherited_course
        if code and course and code not in course:
            course = f"{code} {course}"
        title = next((obj[k] for k in TITLE_KEYS if isinstance(obj.get(k), str) and obj.get(k)), None)
        due_raw = next((obj[k] for k in DUE_KEYS if obj.get(k) not in (None, "")), None)
        if title and due_raw is not None:
            due = _coerce_due(due_raw)
            if due is not None:
                st = next((obj[k] for k in STATE_KEYS if k in obj), None)
                ident = next((str(obj[k]) for k in ("id", "itemId", "uid", "columnId", "contentId")
                              if obj.get(k) not in (None, "")), "")
                yield {"id": ident or None, "title": title, "course": course,
                       "due": due, "submitted": looks_submitted(st)}
                return  # 本层已消费，不再深入
        for v in obj.values():
            yield from _iter_deadline_records(v, course)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_deadline_records(v, inherited_course)


def _coerce_due(v) -> dt.datetime | None:
    if isinstance(v, dict):
        v = v.get("value") or v.get("iso") or v.get("datetime") or v.get("date")
    if isinstance(v, (int, float)) and v > 10**12:  # epoch 毫秒
        return as_shanghai(dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc))
    if isinstance(v, (int, float)) and v > 10**9:  # epoch 秒
        return as_shanghai(dt.datetime.fromtimestamp(v, dt.timezone.utc))
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    try:  # ISO 8601（含 +08:00 / Z / 毫秒）
        return as_shanghai(dt.datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return as_shanghai(dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) or re.fullmatch(r"\d{4}/\d{2}/\d{2}", s):
        d = dt.datetime.strptime(s.replace("/", "-"), "%Y-%m-%d")
        return as_shanghai(d + dt.timedelta(hours=23, minutes=59))  # 纯日期按当天死线算
    return None


def _native_deadlines(raw_text: str, state: str = "") -> list[dict] | None:
    """按 sustech-cli bb deadlines 的已固化 schema（schemaVersion 1）解析。

    state 为本次拉取的 --submission-state 值，写入条目用于分流：
    日报只收未提交的；分档提醒已提交也发（防状态误标/漏交的保险）。
    返回 None 表示不是该 schema（退回启发式）；返回 [] 是合法空集，
    绝不能当失败处理。
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not (isinstance(data, dict) and data.get("ok") is True
            and isinstance(data.get("data"), dict)
            and isinstance(data["data"].get("deadlines"), list)):
        return None
    items = []
    for d in data["data"]["deadlines"]:
        due = _coerce_due(d.get("dueAt"))
        if not due or not d.get("title"):
            continue
        course = " ".join(str(x) for x in (d.get("courseCode"), d.get("courseName")) if x)
        ident = d.get("columnId") or d.get("contentId") or d.get("courseId")
        items.append({"id": f"col-{ident}", "title": str(d["title"]), "course": course or None,
                      "due": due, "submitted": state == "submitted",
                      "submissionState": state, "source": "cli"})
    return items


def run_full_mode(cfg: dict, state: dict) -> tuple[list[dict], str]:
    """返回 (items, detail)。任何失败抛 FullModeError，由调用方降级。"""

    class FullModeError(Exception):
        pass

    # Windows 上 npm 装的是 sustech.cmd，subprocess 需要完整路径（shutil 会按 PATHEXT 解析）
    sustech_bin = shutil.which("sustech")
    if not sustech_bin:
        raise FullModeError("未找到 sustech 命令（未安装或不在 PATH）")

    def sh(args: list[str], stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if cfg["SCHOOL_PASSWORD"]:
            env["SUSTECH_MASTER_PASSWORD"] = cfg["SCHOOL_PASSWORD"]
        return subprocess.run([sustech_bin] + args, input=stdin, capture_output=True, text=True,
                              timeout=timeout, env=env)

    def get_json(args: list[str]) -> str:
        p = sh(args)
        if p.returncode != 0:
            raise FullModeError(f"`{' '.join(args[:3])}...` 退出码 {p.returncode}: "
                                f"{(p.stderr or p.stdout).strip()[:300]}")
        return p.stdout

    def try_login() -> None:
        if not cfg["SUSTECH_SID"]:
            raise FullModeError("自动登录需要学号：请设置 SUSTECH_SID（GitHub Variables 或 .env）")
        p = sh(["auth", "login", "--sid", cfg["SUSTECH_SID"], "--password-stdin"],
               stdin=cfg["SCHOOL_PASSWORD"] + "\n")
        if p.returncode != 0:
            raise FullModeError(f"登录失败（可能触发滑块验证码，需本机续种）: {(p.stderr or p.stdout).strip()[:300]}")

    # 认证退避：连续失败后暂停尝试，避免每小时撞登录
    auth = state.get("auth", {"failures": 0, "until": ""})
    if auth.get("until"):
        until = dt.datetime.fromisoformat(auth["until"])
        if now(cfg) < until:
            raise FullModeError(f"认证退避中，至 {auth['until']}")

    days = cfg["LOOKAHEAD_DAYS"]

    def fetch_parts() -> list[tuple[str, str]]:
        # 按提交状态分批拉取（真实输出不含逐条状态字段）：
        # not_attempted/in_progress → 日报 + 分档提醒；submitted → 仅分档提醒（保险复核）。
        return [(st, get_json(["bb", "deadlines", "--json", "--days", str(days),
                               "--submission-state", st]))
                for st in ("not_attempted", "in_progress", "submitted")]

    if cfg["BB_DEADLINES_FIXTURE"]:
        parts = [("", Path(cfg["BB_DEADLINES_FIXTURE"]).read_text(encoding="utf-8"))]
    else:
        try:
            parts = fetch_parts()
        except FullModeError as first:
            print(f"[full-mode] 首次拉取失败: {first}", file=sys.stderr)  # 保留现场，别被后续错误掩盖
            if not cfg["SCHOOL_PASSWORD"]:
                raise
            try_login()
            parts = fetch_parts()

    items: list[dict] = []
    native_ok = False
    seen_ids: set[str] = set()
    for st, part in parts:
        native = _native_deadlines(part, st)
        if native is None:
            continue
        native_ok = True
        for it in native:
            if it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                items.append(it)
    if not native_ok:
        # 未知 schema：退回启发式解析（老行为），仍解析不出才算失败
        heuristic = _normalize_cli_json("[" + ",".join(part.strip() for _, part in parts) + "]")
        if not heuristic:
            raise FullModeError("sustech-cli 输出无法解析（schema 可能已变化）")
        items = heuristic

    # 出分提醒（可选，仅全保真）
    grades_lines = []
    if cfg["ENABLE_GRADES"] == "1":
        raw_g = Path(cfg["BB_GRADES_FIXTURE"]).read_text(encoding="utf-8") if cfg["BB_GRADES_FIXTURE"] \
            else get_json(["sustech", "bb", "grades", "--json"])
        grades_lines = diff_grades(raw_g, state)

    auth = {"failures": 0, "until": ""}
    state["auth"] = auth
    return items, (grades_lines and "\n".join(grades_lines)) or ""


def _normalize_cli_json(raw: str) -> list[dict]:
    def parse(text: str):
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            objs = []
            for ln in text.splitlines():  # 容忍 JSONL
                ln = ln.strip()
                if ln.startswith("{") and ln.endswith("}"):
                    try:
                        objs.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
            return objs or None
    data = parse(raw)
    if data is None:
        return []
    items = []
    for rec in _iter_deadline_records(data):
        ident = rec["id"] or f"cli-{abs(hash((rec['title'], rec['due'].isoformat())))}"
        items.append({"id": ident, "title": rec["title"], "course": rec["course"],
                      "due": rec["due"], "submitted": rec["submitted"], "source": "cli"})
    return items


def diff_grades(raw: str, state: dict) -> list[str]:
    lines = []
    seen: dict = state.setdefault("grades", {})
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return lines

    def walk(o, inherited_course=None):
        if isinstance(o, dict):
            score = next((o[k] for k in ("score", "grade", "points", "displayGrade", "finalGrade")
                          if isinstance(o.get(k), (str, int, float))), None)
            title = next((o[k] for k in ("title", "name", "assignment", "column") if isinstance(o.get(k), str)), None)
            course = next((o[k] for k in ("course", "courseName", "course_name") if isinstance(o.get(k), str)),
                          None) or inherited_course
            if score is not None and title:
                key = f"{course or ''}|{title}"
                val = str(score)
                if seen.get(key) != val:
                    if seen.get(key) is not None:
                        lines.append(f"[{course or '?'}] {title}: {seen[key]} → {val}")
                    else:
                        lines.append(f"[{course or '?'}] {title}: {val}")
                    seen[key] = val
                return
            for v in o.values():
                walk(v, course)
        elif isinstance(o, list):
            for v in o:
                walk(v, inherited_course)
    walk(data)
    return lines


# ---------------------------------------------------------------- 状态

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"sent": {}, "grades": {}, "auth": {"failures": 0, "until": ""}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 提醒逻辑

def upcoming(items: list[dict], n: dt.datetime, lookahead_days: int) -> list[dict]:
    horizon = n + dt.timedelta(days=lookahead_days)
    return sorted((i for i in items if n <= i["due"] <= horizon),
                  key=lambda i: i["due"])


def pick_escalations(items: list[dict], state: dict, n: dt.datetime, tiers: list[int]) -> list[dict]:
    """跨入某档窗口边界且从未就该 (作业, 截止时刻, 档位) 提醒过的条目。

    档位按小时降序解释为 (下一档, 本档] 的区间，如 48/24/12：
    (24,48] 触发 48h 档，(12,24] 触发 24h 档，(0,12] 触发 12h 档——
    每条作业在每个区间最多提醒一次，deadline 顺延则因截止时刻变化重新触发。
    """
    chosen, sent = [], state.setdefault("sent", {})
    ordered = sorted(set(tiers), reverse=True)
    for item in items:  # 已提交的也提醒（邮件中标注），防 BB 状态误标或漏交
        hours_left = (item["due"] - n).total_seconds() / 3600
        for idx, tier in enumerate(ordered):
            lower = ordered[idx + 1] if idx + 1 < len(ordered) else 0
            if lower < hours_left <= tier:
                key = f"esc:{item['id']}:{item['due'].isoformat()}:{tier}h"
                if key not in sent:
                    sent[key] = n.date().isoformat()
                    chosen.append(item)
                break
    return chosen


def digest_key_today(n: dt.datetime) -> str:
    return f"dig:{n.date().isoformat()}"


# ---------------------------------------------------------------- 邮件

def fmt_due(d: dt.datetime) -> str:
    return d.strftime("%m-%d %H:%M")


def countdown(due: dt.datetime, n: dt.datetime) -> str:
    delta = due - n
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"⚠️ {int(delta.total_seconds() // 60)} 分钟"
    if hours < 24:
        return f"{hours:.1f} 小时"
    return f"{hours / 24:.1f} 天"


def render_email(mode: str, items: list[dict], n: dt.datetime, degraded: bool,
                 grades_note: str) -> tuple[str, str, str]:
    """返回 (subject, html, plain)。"""
    rows = []
    for it in items:
        course = escape(it["course"]) if it["course"] else "<span style='color:#888'>—</span>"
        title = escape(it["title"])
        if mode == "escalate" and it.get("submitted"):  # 已提交仍提醒的保险项，明确标注
            title += " <span style='color:#999;font-size:12px'>（已提交·请复核）</span>"
        rows.append(
            f"<tr><td style='padding:4px 10px'>{course}</td>"
            f"<td style='padding:4px 10px'>{title}</td>"
            f"<td style='padding:4px 10px'>{fmt_due(it['due'])}</td>"
            f"<td style='padding:4px 10px'>{countdown(it['due'], n)}</td></tr>")
    table = ("<table border='1' cellspacing='0' style='border-collapse:collapse;"
             "border-color:#ccc;font-size:14px'>"
             "<tr style='background:#f2f2f2'><th style='padding:4px 10px'>课程</th>"
             "<th style='padding:4px 10px'>作业</th><th style='padding:4px 10px'>截止</th>"
             "<th style='padding:4px 10px'>剩余</th></tr>" + "".join(rows) + "</table>")

    banner = ""
    if degraded:
        banner = ("<p style='color:#a00;font-weight:bold'>⚠ 降级模式：认证层暂不可用，"
                  "本邮件来自 ICS 日历——无课程名、未过滤已提交。"
                  "如持续出现请在电脑上跑一次保育任务（nurse.ps1）。</p>")

    grades_html = ""
    if grades_note:
        grades_html = f"<h3>📬 出分</h3><pre style='font-size:13px'>{escape(grades_note)}</pre>"

    stamp = n.strftime("%Y-%m-%d %H:%M")
    if mode == "escalate":
        nearest = min(items, key=lambda i: i["due"])
        subject = f"⏰ {fmt_due(nearest['due'])} 截止：{nearest['title']} 等 {len(items)} 项"
        head = f"<h2>⏰ 即将截止（{len(items)} 项）</h2>"
    else:
        subject = f"📚 临近截止作业汇总（{len(items)} 项 / 未来窗口内）"
        head = f"<h2>📚 截止日期日报 · {n.date().isoformat()}</h2>"
    if degraded:
        subject = "[降级] " + subject

    html = (f"<div style='font-family:system-ui,-apple-system,sans-serif'>{banner}{head}"
            f"{table}{grades_html}"
            f"<p style='color:#888;font-size:12px'>生成于 {stamp} · "
            f"{'ICS 降级数据源' if degraded else 'sustech-cli 全保真数据源'}</p></div>")
    plain = (("[降级模式] " if degraded else "")
             + (f"即将截止 {len(items)} 项:\n" if mode == "escalate" else f"截止日报 {n.date()}:\n")
             + "\n".join(f"- {(it['course'] + ' · ') if it['course'] else ''}{it['title']}"
                         f"{'（已提交·请复核）' if mode == 'escalate' and it.get('submitted') else ''}"
                         f" 截止 {fmt_due(it['due'])} 剩 {countdown(it['due'], n)}"
                         for it in items)
             + (f"\n\n出分:\n{grades_note}" if grades_note else ""))
    return subject, html, plain


def send_mail(cfg: dict, subject: str, html: str, plain: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg['FROM_NAME']} <{cfg['FROM_ADDR'] or cfg['SMTP_USER']}>"
    msg["To"] = cfg["MAIL_TO"] or cfg["SMTP_USER"]
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(cfg["SMTP_HOST"], int(cfg["SMTP_PORT"]), timeout=60) as s:
        s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        s.sendmail(cfg["SMTP_USER"], [msg["To"]], msg.as_string())


# ---------------------------------------------------------------- 主流程

def acquire_items(cfg: dict, state: dict) -> tuple[list[dict], bool, str]:
    """返回 (items, degraded, grades_note)。全保真失败自动降级 ICS。"""
    if cfg["SCHOOL_PASSWORD"] or cfg["BB_DEADLINES_FIXTURE"]:
        try:
            items, grades_note = run_full_mode(cfg, state)
            return items, False, grades_note
        except Exception as e:  # noqa: BLE001 —— 任何失败都降级，降级层永不抛
            print(f"[full-mode] 降级到 ICS: {e}", file=sys.stderr)
            auth = state.setdefault("auth", {"failures": 0, "until": ""})
            auth["failures"] = int(auth.get("failures", 0)) + 1
            if auth["failures"] >= AUTH_BACKOFF_AFTER_FAILS:
                auth["until"] = (now(cfg) + dt.timedelta(hours=AUTH_BACKOFF_HOURS)).isoformat()
                print(f"[full-mode] 连续失败 {auth['failures']} 次，认证退避至 {auth['until']}", file=sys.stderr)
    if not cfg["ICS_URL"]:
        raise SystemExit("既无认证通道又无 ICS_URL，无法获取数据（检查 Secrets）")
    text = fetch_ics(cfg["ICS_URL"])
    return parse_ics(text), True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["escalate", "digest"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="打印邮件而不发送（状态不落盘）")
    args = ap.parse_args()

    cfg = load_env()
    for req in ("SMTP_USER", "SMTP_PASS"):
        if not cfg[req] and not args.dry_run:
            raise SystemExit(f"缺少 {req}（Secrets 未配置？）")

    state = load_state()
    n = now(cfg)
    items, degraded, grades_note = acquire_items(cfg, state)
    items = upcoming(items, n, int(cfg["LOOKAHEAD_DAYS"]))

    if args.mode == "escalate":
        tiers = [int(t) for t in cfg["TIER_HOURS"].split(",") if t.strip()]
        chosen = pick_escalations(items, state, n, tiers)  # 含已提交（保险复核）
        if not chosen:
            print(f"[escalate] {n:%F %T} 无新增进入窗口的条目（窗口内共 {len(items)} 项在跟踪）")
            if not args.dry_run:
                save_state(state)  # 顺带持久化认证退避等状态
            return 0
        subject, html, plain = render_email("escalate", chosen, n, degraded, "")
    else:
        items = [i for i in items if not i["submitted"]]  # 日报只看未提交
        key = digest_key_today(n)
        if key in state.get("sent", {}) and not args.dry_run:
            print(f"[digest] {key} 已发送过，跳过")
            return 0
        if not items:
            print(f"[digest] 窗口内无临近作业，跳过发信")
            if not args.dry_run:
                state.setdefault("sent", {})[key] = n.date().isoformat()
                save_state(state)
            return 0
        subject, html, plain = render_email("digest", items, n, degraded, grades_note)
        state.setdefault("sent", {})[key] = n.date().isoformat()

    if args.dry_run:
        print("=" * 60, f"\nDRY-RUN [{args.mode}] degraded={degraded}\nSubject: {subject}\n")
        print(plain)
        print("=" * 60)
        return 0

    send_mail(cfg, subject, html, plain)
    save_state(state)
    print(f"[{args.mode}] 已发送: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
