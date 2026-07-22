"""부동산봇 저장소 자가점검 — check_once.py 실행 끝에 호출된다.

30분 크론(매시 7,37분)이 이 코드를 함께 실행하며,
04:07 KST(19:07 UTC) 실행분에서만 하루 1회 점검 리포트를 텔레그램으로 보낸다.
점검이 실패해도 본래의 블로그 감시에는 영향을 주지 않는다(모두 예외 처리).
"""

import datetime
import glob
import json
import logging
import os
import py_compile

import requests

logger = logging.getLogger(__name__)


def _check_syntax(lines):
    """모든 파이썬 파일 문법 검사. 문제 수를 반환."""
    bad = []
    for f in sorted(glob.glob("*.py")):
        try:
            py_compile.compile(f, doraise=True)
        except Exception:
            bad.append(f)
    lines.append("")
    lines.append("📝 코드 문법")
    if bad:
        lines.append("❌ 문법 오류: " + ", ".join(bad))
        return 1
    lines.append(f"✅ 파이썬 {len(glob.glob('*.py'))}개 파일 전체 정상")
    return 0


def _check_watchlists(lines):
    """감시 목록 파일 존재/개수 확인."""
    lines.append("")
    lines.append("📋 감시 목록")
    problems = 0
    for fname, label in (("blogs.txt", "블로그"), ("boards.txt", "게시판")):
        if not os.path.exists(fname):
            lines.append(f"❌ {fname} 없음")
            problems += 1
            continue
        n = sum(
            1
            for l in open(fname, encoding="utf-8")
            if l.strip() and not l.strip().startswith("#")
        )
        lines.append(f"✅ {label} {n}개 감시 중")
    return problems


def _check_seen_files(lines):
    """확인 기록(seen*.json)이 깨지지 않았는지 확인."""
    lines.append("")
    lines.append("🗄 확인 기록")
    problems = 0
    files = sorted(glob.glob("seen*.json"))
    broken = []
    for f in files:
        try:
            json.load(open(f, encoding="utf-8"))
        except Exception:
            broken.append(f)
    if broken:
        lines.append("❌ 깨진 기록 파일: " + ", ".join(broken))
        problems += 1
    else:
        lines.append(f"✅ 기록 파일 {len(files)}개 전부 정상")
    return problems


def _check_rss(lines):
    """네이버 블로그 RSS가 실제로 열리는지 1개 표본 확인."""
    lines.append("")
    lines.append("📡 네이버 RSS 연결")
    try:
        first = None
        for l in open("blogs.txt", encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#"):
                first = l.split()[0]
                break
        if not first:
            lines.append("⚠️ 표본 블로그 없음")
            return 1
        r = requests.get(
            f"https://rss.blog.naver.com/{first}.xml",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.ok and "<rss" in r.text[:200]:
            lines.append("✅ 정상 (표본: %s)" % first)
            return 0
        lines.append(f"❌ HTTP {r.status_code}")
        return 1
    except Exception as e:
        lines.append(f"❌ {e}"[:60])
        return 1


def run_report(token, chat_id):
    """점검을 실행하고 리포트를 텔레그램으로 발송한다."""
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    lines = [f"🩺 부동산봇 자가점검 ({kst:%m-%d %H:%M} KST)"]
    problems = 0
    problems += _check_syntax(lines)
    problems += _check_watchlists(lines)
    problems += _check_seen_files(lines)
    problems += _check_rss(lines)
    lines.append("")
    lines.append(
        "✅ 종합: 모든 시스템 정상"
        if problems == 0
        else f"🚨 종합: 문제 {problems}건 — 확인 필요"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": "\n".join(lines),
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    logger.info("자가점검 리포트 발송 (문제 %d건)", problems)


def maybe_report():
    """새벽 04시대(KST) 실행분에서만 하루 1회 리포트를 보낸다."""
    now = datetime.datetime.utcnow()
    # 크론이 매시 7,37분에 돌므로 19:07 UTC(=04:07 KST) 실행만 해당
    if not (now.hour == 19 and now.minute < 30):
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    run_report(token, chat_id)
