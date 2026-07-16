"""GitHub Actions 등에서 주기적으로 1회 실행되는 booriny.com 매물 알림 스크립트.

booriny.com에 로그인해 재개발 구역 내 최신 매물을 확인하고,
아래 조건에 맞는 새 매물이 있으면 텔레그램으로 알림을 보낸다.
확인한 매물 id는 seen_booriny.json에 저장한다.

필터:
- 재개발구역 매물만 (is_redevelopment) — /api/listings는 네이버 전체 매물을
  반환하므로 이 필터가 없으면 재개발구역이 아닌 매물까지 섞여 나온다(핵심).
- 14개 구 (강남·강동·광진·동대문·동작·마포·서대문·서초·성동·송파·영등포·용산·종로·중구)
- 다세대(빌라/연립, rlet_tp_cd C02) 유형만
- 매매가 5억 이하

필요한 환경변수:
- BOORINY_ID / BOORINY_PW : booriny.com 로그인 이메일/비밀번호
- BOORINY_BOT_TOKEN : 매물 알림용 텔레그램 봇 토큰
- TELEGRAM_CHAT_ID : 알림을 받을 채팅 ID (다른 봇과 공용)

참고: redevelopment_stage 값은 "초기/중기/후기"가 아니라 세부 진행단계
(조합설립인가·대상지선정·안전진단·주민설명회 등)라 단계로 거르지는 않고,
알림 메시지에 구역명·유형·단계를 함께 표시만 한다.
"""

import json
import logging
import os
import re
import time
from datetime import datetime

import requests
import urllib3

from check_once import send_message

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BASE = "https://booriny.com"
SEEN_FILE = "seen_booriny.json"
SEEN_KEEP = 2000

# ── 필터 조건 ──
GU_ALLOW = {
    "강남구", "강동구", "광진구", "동대문구", "동작구", "마포구", "서대문구",
    "서초구", "성동구", "송파구", "영등포구", "용산구", "종로구", "중구",
}
MAX_PRICE = 500_000_000            # 5억 이하
DASEDAE_TYPE_CODES = {"C02"}       # 다세대(빌라/연립) — booriny rlet_tp_cd

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def login(session):
    email = os.environ["BOORINY_ID"]
    pw = os.environ["BOORINY_PW"]
    r = session.post(
        BASE + "/api/auth/v2/login",
        json={"email": email, "password": pw},
        timeout=(15, 30), verify=False,
    )
    r.raise_for_status()
    if not r.json().get("success"):
        raise RuntimeError("booriny 로그인 실패 — 아이디/비밀번호를 확인하세요")


def fetch_listings(session, limit=2000):
    # /api/listings는 재개발구역 매물뿐 아니라 네이버 전체 매물을 반환하고
    # 서버측 필터 파라미터가 먹지 않으므로, 넉넉히 받아 클라이언트에서 거른다.
    r = session.get(BASE + "/api/listings", params={"limit": limit}, timeout=(15, 60), verify=False)
    r.raise_for_status()
    listings = r.json().get("data", {}).get("listings", [])
    # 첫 매물의 필드 로깅 (날짜 필드 확인용)
    if listings:
        logger.info("첫 매물 필드: %s", list(listings[0].keys()))
    return listings


def matches(item):
    # 재개발구역 매물만 (booriny 사이트가 보여주는 대상). 이 필터가 핵심.
    if not item.get("is_redevelopment"):
        return False
    if item.get("division") not in GU_ALLOW:
        return False
    # 다세대(C02)만
    if item.get("rlet_tp_cd") not in DASEDAE_TYPE_CODES:
        return False
    # 매매(trad_tp_cd A1)만, 전월세 제외
    if item.get("trad_tp_cd") not in (None, "", "A1"):
        return False
    try:
        prc = int(item.get("prc") or 0)
    except (TypeError, ValueError):
        return False
    if prc <= 0 or prc > MAX_PRICE:
        return False
    return True


def format_message(item):
    prc = int(item.get("prc") or 0)
    eok = prc / 100_000_000
    zone = item.get("redevelopment_area") or item.get("atcl_nm") or "매물"
    rtype = item.get("redevelopment_type") or ""
    stage = item.get("redevelopment_stage") or ""
    is_sinsok = "신속통합" in rtype or "신통기획" in rtype or "신속통합" in stage

    if is_sinsok:
        rtype_txt = f"🔥{rtype}" if rtype else ""
    elif "모아타운" in rtype:
        rtype_txt = f"🟢{rtype}"
    else:
        rtype_txt = rtype

    zone_rtype = " ".join(x for x in (zone, rtype_txt) if x)
    badge = " · ".join(x for x in (zone_rtype, stage) if x)
    spc = item.get("spc1")
    spc_txt = f" ({spc}㎡)" if spc and str(spc) not in ("0", "0.00") else ""
    atcl_no = item.get("atcl_no")
    # booriny는 네이버 매물을 취합 — 네이버부동산 상세로 연결
    link = f"https://m.land.naver.com/article/info/{atcl_no}" if atcl_no else BASE

    return (
        f"[{badge}]\n"
        f"{eok:.2f}억{spc_txt}\n"
        f"{link}"
    )


def _normalize_date(value):
    """날짜 필드를 '하루' 단위로 정규화한다.

    이 스크립트는 30분마다 실행되는데, 날짜 필드에 시:분:초까지 포함돼 있으면
    (또는 조회 시점 타임스탬프라면) 매 실행마다 값이 달라져 같은 매물이 하루에
    수십 번 알림되는 문제가 생긴다. 그래서 날짜 부분만 추출해 하루 단위로 묶는다.
    """
    s = str(value).strip()
    m = re.match(r"\d{4}[-./]\d{2}[-./]\d{2}", s)
    if m:
        return m.group(0)
    if s.isdigit() and len(s) in (10, 13):  # epoch(초) 또는 epoch(밀리초)
        try:
            ts = int(s) / (1000 if len(s) == 13 else 1)
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            pass
    return s


def get_listing_key(item):
    """매물의 고유 키를 생성 (ID + 날짜 조합으로 같은 매물이라도 새로 올라오면 다시 알림)"""
    item_id = str(item.get("id") or "")
    # 가능한 날짜 필드명들 (첫 번째 존재하는 것 사용)
    for date_field in ["reg_dt", "reg_date", "regDate", "rlet_reg_dt", "created_at", "updated_at"]:
        if date_field in item and item[date_field]:
            return f"{item_id}:{_normalize_date(item[date_field])}"
    # 날짜가 없으면 ID만 사용 (하위호환성)
    return item_id


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return []
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
            # 구 형식 (문자열 리스트)과 신 형식 (혼합) 모두 지원
            if isinstance(data, list):
                return data
            return data.get("items", [])
    except (json.JSONDecodeError, ValueError):
        return []


def save_seen(seen_keys):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_keys[-SEEN_KEEP:], f, ensure_ascii=False)
        f.write("\n")


def main():
    # 시크릿이 아직 등록되지 않았으면 조용히 건너뛴다
    missing = [k for k in ("BOORINY_ID", "BOORINY_PW", "BOORINY_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        logger.info("booriny 시크릿 미설정으로 건너뜀: %s", ", ".join(missing))
        return

    token = os.environ["BOORINY_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT, "Content-Type": "application/json",
        "Origin": BASE, "Referer": BASE + "/",
    })
    login(session)
    listings = fetch_listings(session)
    logger.info("받은 매물 %d건", len(listings))

    matched = [x for x in listings if matches(x)]
    logger.info("필터 통과(재개발구역·14구·다세대·5억이하) %d건", len(matched))

    seen = load_seen()
    seen_set = set(seen)
    first_run = not seen

    if first_run:
        # 첫 실행: 기존 매물은 알림 없이 기준선으로 저장
        for x in matched:
            seen.append(get_listing_key(x))
        save_seen(seen)
        send_message(
            token, chat_id,
            f"🏠 부리니 매물 감시를 시작했습니다. "
            f"(현재 조건 매물 {len(matched)}건을 기준선으로 저장) 새 매물이 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d건 저장", len(matched))
        return

    # 구 형식(ID만) 저장 항목 — ID+날짜 형식 도입 전에 이미 알림을 보냈던 매물.
    # 이번 실행에서 처음 마주치면 재알림 없이 신 형식(ID:날짜)으로 조용히 업그레이드한다.
    legacy_ids = {s for s in seen if ":" not in s}

    to_alert = []
    for x in matched:
        key = get_listing_key(x)
        if key in seen_set:
            continue
        item_id = str(x.get("id") or "")
        if item_id in legacy_ids:
            if item_id in seen:
                seen.remove(item_id)
            seen.append(key)
            legacy_ids.discard(item_id)
            continue
        to_alert.append(x)

    try:
        # 오래된 것부터 발송(리스트는 최신순이므로 뒤집는다)
        for x in reversed(to_alert):
            send_message(token, chat_id, format_message(x), disable_preview=True)
            seen.append(get_listing_key(x))
            logger.info("알림: %s %s %s", x.get("division"), x.get("sector"), x.get("prc"))
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
