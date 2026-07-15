"""GitHub Actions 등에서 주기적으로 1회 실행되는 서울정보소통광장 결재문서 알림 스크립트.

서울정보소통광장(opengov.seoul.go.kr) 결재문서는 해외(GitHub Actions)에서 직접
접속이 차단되고 공개 API도 없어, 네이버 웹문서 검색 오픈API로 네이버가 색인한
opengov 결재문서(/sanction/) 중 지정 키워드가 든 글을 찾아 텔레그램으로 알린다.
확인한 글 링크는 seen_opengov.json에 저장한다.

키워드: 후보지 · 재개발 · 재건축 · 신속통합 · 모아타운 · 정비사업

필요한 환경변수:
- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET : 네이버 개발자센터 검색 API 인증정보(카페 감시와 공용)
- BOARD_BOT_TOKEN : 알림용 텔레그램 봇 토큰(재재보드봇, 게시판 알림과 공용)
- TELEGRAM_CHAT_ID : 알림을 받을 채팅 ID (다른 봇과 공용)

한계: 네이버 검색 색인에 의존하므로 실시간이 아니며(색인까지 수시간~수일 지연 가능),
색인되지 않은/비공개 결재문서는 잡히지 않는다. opengov가 해외 차단이라 이것이
서버리스로 가능한 유일한 우회 방법이다.
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

SEARCH_URL = "https://openapi.naver.com/v1/search/webkr.json"
SEEN_FILE = "seen_opengov.json"
SEEN_KEEP = 3000

# opengov 결재문서 상세 경로만 대상으로 삼는다
LINK_HINT = "opengov.seoul.go.kr/sanction"
# 키워드
KEYWORDS = ["후보지", "재개발", "재건축", "신속통합", "모아타운", "정비사업"]

TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return html.unescape(TAG_RE.sub("", text or "")).strip()


def search(keyword, client_id, client_secret):
    """opengov로 한정해 웹문서를 검색한다(최대 1000건까지 페이지네이션)."""
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    query = f"{keyword} site:opengov.seoul.go.kr"
    items = []
    for start in range(1, 1001, 100):
        params = {"query": query, "display": 100, "start": start, "sort": "date"}
        r = requests.get(SEARCH_URL, headers=headers, params=params, timeout=(15, 30))
        r.raise_for_status()
        page = r.json().get("items", [])
        items.extend(page)
        if len(page) < 100:
            break
    return items


def is_sanction(item):
    return LINK_HINT in (item.get("link") or "")


def format_message(item, keyword):
    title = clean(item.get("title")) or "(제목 없음)"
    link = item.get("link") or ""
    return (
        f"📄 [서울시 결재문서] '{keyword}' 관련\n"
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
    missing = [k for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "BOARD_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        logger.info("결재문서 감시 시크릿 미설정으로 건너뜀: %s", ", ".join(missing))
        return

    client_id = os.environ["NAVER_CLIENT_ID"]
    client_secret = os.environ["NAVER_CLIENT_SECRET"]
    token = os.environ["BOARD_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    found = {}   # link -> (item, keyword)
    for kw in KEYWORDS:
        try:
            items = search(kw, client_id, client_secret)
        except Exception as e:
            logger.warning("'%s' 검색 실패: %s", kw, e)
            continue
        hits = [x for x in items if is_sanction(x)]
        logger.info("'%s' 검색 %d건 중 결재문서 %d건", kw, len(items), len(hits))
        for x in hits:
            link = x.get("link")
            if link and link not in found:
                found[link] = (x, kw)

    logger.info("결재문서 대상 글 총 %d건", len(found))

    seen = load_seen()
    seen_set = set(seen)
    first_run = not seen

    new_links = [lk for lk in found if lk not in seen_set]

    if first_run:
        for lk in found:
            seen.append(lk)
        save_seen(seen)
        send_message(
            token, chat_id,
            f"📄 서울시 결재문서 감시를 시작했습니다. "
            f"(현재 조건 글 {len(found)}건을 기준선으로 저장) "
            f"'{'·'.join(KEYWORDS)}' 관련 새 문서가 색인되면 알려드릴게요.",
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
