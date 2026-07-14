"""GitHub Actions 등에서 주기적으로 1회 실행되는 구청 게시판 새 공고 확인 스크립트.

boards.txt에 적힌 게시판들을 확인해서, 처음 보는 공고(키워드 일치)가 있으면
텔레그램으로 알림을 보낸다. 확인한 공고는 seen_boards.json에 저장한다.

boards.txt 형식 (| 로 구분, 키워드는 쉼표로 여러 개, 비우면 전체):
    이름 | 게시판주소 | 키워드1,키워드2

필요한 환경변수:
- TELEGRAM_BOT_TOKEN: BotFather에서 발급받은 봇 토큰
- TELEGRAM_CHAT_ID: 알림을 받을 채팅 ID
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

from check_once import send_message

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOARDS_FILE = "boards.txt"
SEEN_FILE = "seen_boards.json"
SEEN_KEEP = 300  # 게시판별로 보관할 확인한 공고 수
FETCH_WORKERS = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def load_boards():
    if not os.path.exists(BOARDS_FILE):
        return []
    boards = []
    with open(BOARDS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[1].startswith("http"):
                logger.warning("boards.txt 형식 오류로 건너뜀: %s", line)
                continue
            keywords = []
            if len(parts) >= 3 and parts[2]:
                keywords = [k.strip() for k in parts[2].split(",") if k.strip()]
            # 4번째 칸: 부서 필터 (제목이 아니라 글 행 전체 텍스트에서 찾음)
            row_keywords = []
            if len(parts) >= 4 and parts[3]:
                row_keywords = [k.strip() for k in parts[3].split(",") if k.strip()]
            boards.append({
                "name": parts[0], "url": parts[1],
                "keywords": keywords, "row_keywords": row_keywords,
            })
    return boards


def scrape_board(url, keywords, row_keywords=(), name=""):
    """게시판 목록에서 (제목, 링크, 날짜) 목록을 추출한다. jejeboard의 검증된 로직."""
    last_error = None
    for attempt in range(2):  # 느린 사이트를 위해 1회 재시도
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Referer": url},
                verify=False,
                timeout=(15, 40),
            )
            response.encoding = "utf-8"
            response.raise_for_status()
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.info("retrying %s after error: %s", name or url, e)
    else:
        raise last_error
    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.select(
        "table tbody tr, .board-list tr, .bbs-list tr, .list_type li, "
        ".news-list li, .search-result-list li, .list-wrap li"
    )
    if not rows:
        rows = soup.select(".title, .subject, .txt_left, .tit")

    posts = []
    for row in rows:
        title_elem = row.select_one("a, .tit, .subject, .title")
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        if len(title) < 3:
            continue

        if keywords and not any(k in title for k in keywords):
            continue

        # 부서 필터: 제목이 아닌 행 전체 텍스트(부서명 칸 포함)에서 찾는다
        if row_keywords:
            row_text = row.get_text(" ", strip=True)
            if not any(k in row_text for k in row_keywords):
                continue

        link = title_elem.get("href", "")
        if not link or "#" in link or "javascript" in link:
            parent_a = row.find_parent("a") or row.find("a")
            if parent_a:
                link = parent_a.get("href", "")

        full_link = urljoin(url, link) if link else url

        date_val = ""
        for elem in row.select("td, span, .date, .reg_date, .day"):
            txt = elem.get_text(strip=True)
            if re.search(r"\d{2,4}[-./]\d{1,2}[-./]\d{1,2}", txt):
                date_val = txt
                break

        posts.append({"title": title, "link": full_link, "date": date_val})

    # 0건일 때 '읽기 실패'인지 '필터에 걸린 글이 없는 것'인지 구분할 수 있게 남긴다
    logger.info("%s: 행 %d개 파싱, 필터 통과 %d건", name or url, len(rows), len(posts))
    return posts


def post_key(post):
    # 링크는 순번/토큰 등 가변 값이 섞이는 게시판이 있어 제목+날짜로 식별한다
    return f"{post['title']}#{post['date']}"


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch_all(boards):
    results = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = {
            executor.submit(
                scrape_board, b["url"], b["keywords"], b["row_keywords"], b["name"]
            ): b["url"]
            for b in boards
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as e:
                logger.warning("failed to fetch %s: %s", url, e)
                results[url] = None
    return results


def main():
    boards = load_boards()
    if not boards:
        logger.info("boards.txt에 등록된 게시판이 없습니다.")
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    seen = load_seen()
    results = fetch_all(boards)

    started = []
    failed = []
    try:
        for board in boards:
            url, name = board["url"], board["name"]
            entry = seen.get(url)
            posts = results.get(url)

            if posts is None:
                if entry is None:
                    failed.append(name)
                    seen[url] = {"name": name, "keys": [], "error": True}
                continue

            keys = [post_key(p) for p in posts]

            if entry is None or entry.get("error"):
                # 새로 등록된 게시판: 기존 공고는 알림 없이 기준선으로 저장
                seen[url] = {"name": name, "keys": keys[:SEEN_KEEP]}
                started.append(name)
                logger.info("started watching %s (%d posts)", name, len(posts))
                continue

            known = set(entry["keys"])
            new_posts = [p for p in posts if post_key(p) not in known]
            for post in reversed(new_posts):  # 오래된 공고부터 순서대로 발송
                date_part = f" ({post['date']})" if post["date"] else ""
                send_message(
                    token, chat_id,
                    f"📋 [{name}] 새 공고{date_part}\n{post['title']}\n{post['link']}",
                )
                entry["keys"].insert(0, post_key(post))
                logger.info("notified: [%s] %s", name, post["title"])

            entry["name"] = name
            entry["keys"] = entry["keys"][:SEEN_KEEP]

        if started:
            if len(started) == 1:
                text = f"📋 '{started[0]}' 게시판 감시를 시작했습니다. 새 공고가 올라오면 알려드릴게요."
            else:
                text = (
                    f"📋 게시판 {len(started)}개 감시를 시작했습니다: "
                    f"{', '.join(started)}. 새 공고가 올라오면 알려드릴게요."
                )
            send_message(token, chat_id, text)

        if failed:
            send_message(
                token, chat_id,
                f"⚠️ 다음 게시판을 읽지 못했습니다: {', '.join(failed)}\n"
                "boards.txt의 주소를 확인해주세요.",
            )

        # boards.txt에서 지워진 게시판의 기록은 정리
        board_urls = {b["url"] for b in boards}
        seen = {u: seen[u] for u in seen if u in board_urls}
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
