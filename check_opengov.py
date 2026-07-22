"""서울정보소통광장 결재문서를 네이버 공식 검색 API로 보완 감시한다.

정보소통광장 원 서버는 GitHub Actions 해외 IP의 TCP 연결을 차단한다.
검색 API에서 새로 색인된 후보를 찾되, 결과 설명에서 실제 문서 작성일을
확인할 수 있는 최근 문서만 알림으로 인정해 과거 문서 재색인 오탐을 막는다.
"""

import json
import logging
import os
import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from check_once import keyword_in_title, send_message

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SEARCH_URL = "https://openapi.naver.com/v1/search/webkr.json"
SEEN_FILE = "seen_cafe.json"
STATE_PREFIX = "opengov:"
KEYWORDS = [
    "재개발", "재건축", "신속통합", "모아타운", "도심복합",
    "정비계획", "정비구역", "정비사업", "후보지", "동의서",
]
SANCTION_RE = re.compile(r"https?://opengov\.seoul\.go\.kr/sanction/\d+")
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})(?:일)?(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
)
RECENT_DAYS = 45


def clean_html(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def canonical_link(value):
    match = SANCTION_RE.search(value or "")
    return match.group(0).replace("http://", "https://") if match else ""


def extract_recent_date(*texts, today=None):
    """문구 안의 날짜 중 실행일 기준 최근 날짜를 반환한다."""
    today = today or date.today()
    cutoff = today - timedelta(days=RECENT_DAYS)
    candidates = []
    for text in texts:
        for pattern in DATE_PATTERNS:
            for year, month, day in pattern.findall(text or ""):
                try:
                    parsed = date(int(year), int(month), int(day))
                except ValueError:
                    continue
                if cutoff <= parsed <= today + timedelta(days=1):
                    candidates.append(parsed)
    return max(candidates).isoformat() if candidates else ""


def search_keyword(keyword, client_id, client_secret):
    response = requests.get(
        SEARCH_URL,
        params={
            "query": f'"{keyword}" site:opengov.seoul.go.kr/sanction',
            "display": 100,
            "start": 1,
            "sort": "date",
        },
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
        timeout=(15, 40),
    )
    response.raise_for_status()
    return response.json().get("items") or []


def collect_posts(client_id, client_secret):
    posts = {}
    total = 0
    for keyword in KEYWORDS:
        items = search_keyword(keyword, client_id, client_secret)
        total += len(items)
        for item in items:
            link = canonical_link(item.get("link") or item.get("originallink"))
            if not link:
                continue
            title = clean_html(item.get("title"))
            description = clean_html(item.get("description"))
            if not keyword_in_title(title, keyword):
                continue
            written = extract_recent_date(title, description)
            if not written:
                # 색인 최신순만 믿지 않고 실제 작성일 확인이 가능한 문서만 허용한다.
                continue
            posts[link] = {
                "title": title,
                "link": link,
                "date": written,
            }
    result = sorted(posts.values(), key=lambda post: (post["date"], post["link"]), reverse=True)
    logger.info("정보소통광장 검색 %d건, 최근 작성일 확인 %d건", total, len(result))
    return result


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        return None
    return list(dict.fromkeys(
        value[len(STATE_PREFIX):] for value in data if value.startswith(STATE_PREFIX)
    ))


def save_seen(links):
    existing = []
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            existing = [value for value in data if not value.startswith(STATE_PREFIX)]
    opengov = [STATE_PREFIX + link for link in list(dict.fromkeys(links))[:1000]]
    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump((existing + opengov)[-2000:], file, ensure_ascii=False)
        file.write("\n")


def main():
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    token = os.environ.get("BOARD_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not client_id or not client_secret:
        logger.info("NAVER_CLIENT_ID/SECRET 미설정: 정보소통광장 보완 검색을 건너뜁니다.")
        return
    if not token or not chat_id:
        raise RuntimeError("BOARD_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다")

    posts = collect_posts(client_id, client_secret)
    seen = load_seen()
    current_links = [post["link"] for post in posts]
    if seen is None:
        save_seen(current_links)
        logger.info("정보소통광장 보완 검색 기준선 %d건 저장", len(posts))
        return

    known = set(seen)
    new_posts = [post for post in posts if post["link"] not in known]
    saved = list(seen)
    try:
        for post in reversed(new_posts):
            send_message(
                token,
                chat_id,
                f"📋 [서울정보소통광장] 새 결재문서 ({post['date']})\n"
                f"{post['title']}\n{post['link']}",
            )
            saved.insert(0, post["link"])
            logger.info("notified: %s", post["title"])
    finally:
        # Telegram 발송에 성공한 링크만 저장한다.
        save_seen(saved)


if __name__ == "__main__":
    main()
