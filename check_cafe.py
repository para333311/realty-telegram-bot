"""GitHub Actions 등에서 주기적으로 1회 실행되는 네이버카페 글 알림 스크립트.

네이버 검색 오픈API(cafearticle)로 지정한 키워드가 든 카페 글을 찾아,
'부동산스터디'(cafe.naver.com/jaegebal) 카페의 글만 골라 텔레그램으로 알린다.
확인한 글 링크는 seen_cafe.json에 저장한다.

감시 대상 카페: 부동산스터디 (https://cafe.naver.com/jaegebal)
키워드: 설명회 · 단톡방 · 동의서 · 카톡방
  (재개발 주민설명회/동의서 징구/단톡·카톡방 안내 관련 글을 잡기 위함)

필요한 환경변수:
- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET : 네이버 개발자센터 검색 API 인증정보
- BOARD_BOT_TOKEN : 알림용 텔레그램 봇 토큰(재재보드봇, 게시판 알림과 공용)
- TELEGRAM_CHAT_ID : 알림을 받을 채팅 ID (다른 봇과 공용)

참고: 네이버 카페는 RSS/공개 목록 API가 없어 로그인 없이 글을 직접 읽을 수 없다.
네이버가 공식 지원하는 검색 오픈API만이 해외 서버(GitHub Actions)에서 접근 가능하며,
검색 색인에 오른 공개 글만 잡힌다(회원 전용 비공개 글은 제외될 수 있음).
"""

import html
import json
import logging
import os
import re

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

SEARCH_URL = "https://openapi.naver.com/v1/search/cafearticle.json"
SEEN_FILE = "seen_cafe.json"
SEEN_KEEP = 3000

# 감시 대상 카페 (부동산스터디)
CAFE_URL_HINT = "cafe.naver.com/jaegebal"
# 키워드
KEYWORDS = ["설명회", "단톡방", "동의서", "카톡방"]

TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    """검색결과의 <b> 태그 및 HTML 엔티티를 제거한다."""
    return html.unescape(TAG_RE.sub("", text or "")).strip()


def search(keyword, client_id, client_secret):
    """키워드로 카페 글을 최신순으로 검색한다.

    네이버 검색 API는 카페를 지정할 수 없어 전체 카페에서 검색되므로,
    부동산스터디 글이 최신 100건 밖으로 밀리지 않도록 start를 늘려가며
    최대 1000건까지(display 100 × 10페이지) 받아온다.
    """
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    items = []
    for start in range(1, 1001, 100):   # start=1,101,...,901 (API 최대 start=1000)
        params = {"query": keyword, "display": 100, "start": start, "sort": "date"}
        r = requests.get(SEARCH_URL, headers=headers, params=params, timeout=(15, 30))
        r.raise_for_status()
        page = r.json().get("items", [])
        items.extend(page)
        if len(page) < 100:   # 마지막 페이지
            break
    return items


def in_target_cafe(item):
    """부동산스터디 카페 글인지 확인."""
    return CAFE_URL_HINT in (item.get("cafeurl") or "") or CAFE_URL_HINT in (item.get("link") or "")


def format_message(item, keyword):
    title = clean(item.get("title")) or "(제목 없음)"
    cafe = clean(item.get("cafename")) or "부동산스터디"
    link = item.get("link") or ""
    return (
        f"📝 [{cafe}] '{keyword}' 관련 새 글\n"
        f"{title}\n"
        f"{link}"
    )


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return []
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen_links):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_links[-SEEN_KEEP:], f, ensure_ascii=False)
        f.write("\n")


def main():
    # 시크릿이 아직 등록되지 않았으면 조용히 건너뛴다
    missing = [k for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "BOARD_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        logger.info("카페 감시 시크릿 미설정으로 건너뜀: %s", ", ".join(missing))
        return

    client_id = os.environ["NAVER_CLIENT_ID"]
    client_secret = os.environ["NAVER_CLIENT_SECRET"]
    token = os.environ["BOARD_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # 키워드별로 검색 → 부동산스터디 글만 수집 (link 기준 중복 제거, 매칭 키워드 기억)
    found = {}   # link -> (item, keyword)
    for kw in KEYWORDS:
        try:
            items = search(kw, client_id, client_secret)
        except Exception as e:
            logger.warning("'%s' 검색 실패: %s", kw, e)
            continue
        hits = [x for x in items if in_target_cafe(x)]
        logger.info("'%s' 검색 %d건 중 부동산스터디 %d건", kw, len(items), len(hits))
        for x in hits:
            link = x.get("link")
            if link and link not in found:
                found[link] = (x, kw)

    logger.info("부동산스터디 대상 글 총 %d건", len(found))

    seen = load_seen()
    seen_set = set(seen)
    first_run = not seen

    new_links = [lk for lk in found if lk not in seen_set]

    if first_run:
        # 첫 실행: 기존 글은 알림 없이 기준선으로 저장
        for lk in found:
            seen.append(lk)
        save_seen(seen)
        send_message(
            token, chat_id,
            f"📝 부동산스터디 카페 감시를 시작했습니다. "
            f"(현재 조건 글 {len(found)}건을 기준선으로 저장) "
            f"'{'·'.join(KEYWORDS)}' 관련 새 글이 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d건 저장", len(found))
        return

    try:
        for lk in new_links:
            item, kw = found[lk]
            send_message(token, chat_id, format_message(item, kw))
            seen.append(lk)
            logger.info("알림: [%s] %s", kw, clean(item.get("title")))
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
    # 같은 네이버 검색 시크릿으로 서울정보소통광장 차단 우회 감시도 이어서 실행한다.
    from check_opengov import main as check_opengov

    check_opengov()
