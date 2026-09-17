"""휴식이형 네이버 프리미엄콘텐츠 2개와 네이버카페 '휴멘'의 새 글을 알린다.

블로그 새 글 알림과 같은 채널로 보내되, 어느 출처인지 한눈에 보이게 이모지를 붙인다.
  🔴 재개발 재건축 추천매물 스터디 (매운맛)
  🟡 아주 쉬운 재개발 재건축 (순한맛)
  🟢 카페 휴멘

읽는 곳 (2026-09-17 확인, 셋 다 로그인 불필요):

  네프콘: https://contents.premium.naver.com/{크리에이터}/{채널}
    채널 홈이 서버렌더 HTML이라 a.channel_content_link 로 글 목록이 그대로 잡힌다.
    제목은 그 안의 span.channel_content_title_text. 같은 페이지의 recommend_item_link
    (추천글)·channel_pick_review_footer_link(픽 댓글)는 남의 글이라 걸러야 해서
    class로 정확히 골라낸다. /contents 하위 페이지는 마크업이 달라 쓰지 않는다.
    글 id(260917133337835uw)는 YYMMDDHHMMSSmmm+2글자라 사전순=시간순이다.

  카페: https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json?search.clubid=...
    비회원도 목록을 준다(제목·게시판명·글번호). 기존 check_cafe.py가 쓰는 검색
    오픈API와 달리 카페를 직접 지정할 수 있고 색인 지연도 없다.

필요한 환경변수:
- TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID : 알림 보낼 봇과 채팅
"""

import json
import logging
import os
import re

import requests
from bs4 import BeautifulSoup

from check_once import send_message

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

PREMIUM_BASE = "https://contents.premium.naver.com"
CAFE_API = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json"
SEEN_FILE = "seen_jeje.json"
SEEN_KEEP = 500  # 출처별로 보관할 글 id 수

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SOURCES = [
    {
        "key": "jejemvp",
        "kind": "premium",
        "emoji": "🔴",
        "name": "재개발 재건축 추천매물 스터디",
        "creator": "jejeguide",
        "channel": "jejemvp",
    },
    {
        "key": "jeje",
        "kind": "premium",
        "emoji": "🟡",
        "name": "아주 쉬운 재개발 재건축",
        "creator": "jejeguide",
        "channel": "jeje",
    },
    {
        "key": "jejeria",
        "kind": "cafe",
        "emoji": "🟢",
        "name": "휴멘",
        "club_id": 31636706,
        "cafe_url": "jejeria",
    },
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch_premium(source):
    url = f"{PREMIUM_BASE}/{source['creator']}/{source['channel']}"
    response = SESSION.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    posts = []
    seen_ids = set()
    for anchor in soup.select("a.channel_content_link"):
        match = re.search(r"/contents/([\w-]+)", anchor.get("href") or "")
        if not match or match.group(1) in seen_ids:
            continue
        seen_ids.add(match.group(1))
        title = anchor.select_one(".channel_content_title_text")
        posts.append({
            "id": match.group(1),
            "sort": match.group(1),
            "title": title.get_text(strip=True) if title else "(제목 없음)",
            "link": f"{PREMIUM_BASE}{anchor['href']}",
            "board": "",
        })
    return posts


def fetch_cafe(source):
    response = SESSION.get(
        CAFE_API,
        params={
            "search.clubid": source["club_id"],
            "search.queryType": "lastArticle",
            "search.page": 1,
            "search.perPage": 30,
        },
        headers={"Referer": f"https://cafe.naver.com/{source['cafe_url']}"},
        timeout=20,
    )
    response.raise_for_status()
    message = response.json().get("message") or {}
    if str(message.get("status")) != "200":
        raise RuntimeError(f"카페 목록 응답 오류: {message.get('error')}")

    posts = []
    for article in message.get("result", {}).get("articleList") or []:
        article_id = article.get("articleId")
        if not article_id:
            continue
        posts.append({
            "id": str(article_id),
            "sort": int(article_id),
            "title": article.get("subject") or "(제목 없음)",
            "link": f"https://cafe.naver.com/{source['cafe_url']}/{article_id}",
            "board": article.get("menuName") or "",
        })
    return posts


FETCHERS = {"premium": fetch_premium, "cafe": fetch_cafe}


def format_message(source, post):
    where = source["name"]
    if post["board"]:
        where += f" · {post['board']}"
    return f"{source['emoji']} [{where}]\n{post['title']}\n{post['link']}"


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("텔레그램 설정이 없어 건너뜁니다.")
        return

    seen = load_seen()
    for source in SOURCES:
        try:
            posts = FETCHERS[source["kind"]](source)
        except Exception as e:
            logger.warning("%s 목록을 가져오지 못했습니다: %s", source["name"], e)
            continue

        # 목록이 통째로 비면 마크업이 바뀐 것이다. 기준선을 비워 덮어쓰면 다음 실행에서
        # 지난 글이 전부 새 글로 쏟아지므로, 아무것도 건드리지 않고 넘어간다.
        if not posts:
            logger.warning("%s: 글이 하나도 안 잡혀 건너뜁니다.", source["name"])
            continue

        known = seen.get(source["key"])
        if known is None:
            seen[source["key"]] = [p["id"] for p in posts][:SEEN_KEEP]
            save_seen(seen)
            send_message(
                token, chat_id,
                f"{source['emoji']} [{source['name']}] 새 글 감시를 시작했습니다. "
                f"(현재 {len(posts)}건을 기준선으로 저장)",
            )
            logger.info("%s 첫 실행: 기준선 %d건", source["name"], len(posts))
            continue

        known_set = set(known)
        new_posts = sorted(
            (p for p in posts if p["id"] not in known_set), key=lambda p: p["sort"]
        )
        try:
            for post in new_posts:
                send_message(token, chat_id, format_message(source, post))
                known.append(post["id"])
                logger.info("알림: [%s] %s", source["name"], post["title"])
        finally:
            seen[source["key"]] = known[-SEEN_KEEP:]
            save_seen(seen)


if __name__ == "__main__":
    main()
