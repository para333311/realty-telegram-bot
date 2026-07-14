"""GitHub Actions 등에서 주기적으로 1회 실행되는 새 글 확인 스크립트.

blogs.txt에 적힌 블로그들의 RSS를 확인해서, 처음 보는 글이 있으면
텔레그램으로 알림을 보낸다. 확인한 글 링크는 seen.json에 저장한다.

필요한 환경변수:
- TELEGRAM_BOT_TOKEN: BotFather에서 발급받은 봇 토큰
- TELEGRAM_CHAT_ID: 알림을 받을 채팅 ID
"""

import json
import logging
import os

import requests

import naver_blog

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BLOGS_FILE = "blogs.txt"
SEEN_FILE = "seen.json"
SEEN_LINKS_KEEP = 200  # 블로그별로 보관할 확인한 글 링크 수


def load_blog_ids():
    if not os.path.exists(BLOGS_FILE):
        return []
    blog_ids = []
    with open(BLOGS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            blog_id = naver_blog.extract_blog_id(line)
            if blog_id and blog_id not in blog_ids:
                blog_ids.append(blog_id)
    return blog_ids


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
        f.write("\n")


def send_message(token, chat_id, text):
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    response.raise_for_status()


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    blog_ids = load_blog_ids()
    if not blog_ids:
        logger.info("blogs.txt에 등록된 블로그가 없습니다.")
        return

    seen = load_seen()
    try:
        for blog_id in blog_ids:
            entry = seen.get(blog_id)
            try:
                blog_name, posts = naver_blog.fetch_posts(blog_id)
            except Exception as e:
                logger.warning("failed to fetch %s: %s", blog_id, e)
                if entry is None:
                    # 새로 추가된 블로그가 잘못된 주소일 수 있으니 한 번만 알려준다
                    send_message(
                        token, chat_id,
                        f"⚠️ '{blog_id}' 블로그 정보를 가져오지 못했습니다. "
                        "blogs.txt에 적은 주소를 확인해주세요.",
                    )
                    seen[blog_id] = {"name": blog_id, "links": [], "error": True}
                continue

            links = [p["link"] for p in posts]

            if entry is None or entry.get("error"):
                # 새로 등록된 블로그: 기존 글은 알림 없이 기준선으로 저장
                seen[blog_id] = {"name": blog_name, "links": links[:SEEN_LINKS_KEEP]}
                send_message(
                    token, chat_id,
                    f"✅ '{blog_name}' 블로그 감시를 시작했습니다. "
                    "새 글이 올라오면 알려드릴게요.",
                )
                logger.info("started watching %s (%s)", blog_name, blog_id)
                continue

            known = set(entry["links"])
            new_posts = [p for p in posts if p["link"] not in known]
            for post in reversed(new_posts):  # 오래된 글부터 순서대로 발송
                send_message(
                    token, chat_id,
                    f"🔔 [{blog_name}] 새 글 등록\n{post['title']}\n{post['link']}",
                )
                entry["links"].insert(0, post["link"])
                logger.info("notified: [%s] %s", blog_name, post["title"])

            entry["name"] = blog_name
            entry["links"] = entry["links"][:SEEN_LINKS_KEEP]

        # blogs.txt에서 지워진 블로그의 기록은 정리 (다시 추가하면 새로 시작)
        seen = {bid: seen[bid] for bid in blog_ids if bid in seen}
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
