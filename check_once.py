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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import naver_blog

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# 넓은 '정비' 키워드가 도시정비와 무관하게 걸리는 대표적인 업무 영역들.
# (유지보수·단속·환경미화 등 — 실제 알림 기록에서 관측된 오탐 기준)
UNRELATED_MAINTENANCE_WORDS = (
    "광고물", "물놀이", "침수", "하수도", "제설", "가로등", "보도블록",
    "불법주정차", "환경정비", "기간제근로자", "채용", "가지치기", "방역",
)


def keyword_in_title(title, keyword):
    """제목에 특정 키워드가 실제로 매치되는지 확인한다.

    - '재개발'은 '인재개발원/인재개발과' 등 인사·교육 조직명에 흔히 포함돼
      단순 부분일치로는 오탐이 난다(예: "[인재개발원 인재기획과] ..."). 그래서
      '재개발' 앞 글자가 '인'인 경우는 매치로 보지 않는다.
    - '동의서'는 '공무원증 일련번호 및 개인정보 제공 동의서 제출'처럼
      개인정보 수집·이용·제공 동의서(인사·행정용)가 결재문서에 흔해
      오탐이 난다. 제목에 '개인정보'/'개인 정보'가 함께 있으면 재개발
      동의서(조합설립·정비구역 지정 등)가 아니라고 보고 매치하지 않는다.
    - 넓은 '정비'는 도시정비와 무관한 유지보수·단속 업무에도 두루 쓰여
      오탐이 잦다(실제 관측: "불법광고물 정비 기간제근로자 채용",
      "중랑천 물놀이장 휴장 안내(침수정비 및 오후우천)"). 아래 무관어가
      제목에 있으면 매치로 보지 않는다. '정비구역·정비사업' 등 구체적인
      키워드는 이 가드를 타지 않으므로 도시정비 공고는 그대로 걸린다.
    """
    if keyword == "동의서":
        if keyword not in title:
            return False
        return "개인정보" not in title and "개인 정보" not in title
    if keyword == "정비":
        if keyword not in title:
            return False
        return not any(w in title for w in UNRELATED_MAINTENANCE_WORDS)
    if keyword != "재개발":
        return keyword in title
    idx = 0
    while True:
        pos = title.find(keyword, idx)
        if pos == -1:
            return False
        if pos == 0 or title[pos - 1] != "인":
            return True
        idx = pos + 1


def title_matches(title, keywords):
    """제목이 keywords 중 하나라도 (오탐 제외하고) 포함하는지 확인한다."""
    return any(keyword_in_title(title, k) for k in keywords)

BLOGS_FILE = "blogs.txt"
SEEN_FILE = "seen.json"
SEEN_LINKS_KEEP = 200  # 블로그별로 보관할 확인한 글 링크 수
FETCH_WORKERS = 10  # 동시에 확인할 블로그 수
SEND_INTERVAL = 1.0  # 텔레그램 메시지 발송 간 최소 간격(초)
TELEGRAM_SEND_ATTEMPTS = 3

_last_send_at = 0.0


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


def send_message(token, chat_id, text, disable_preview=False, parse_mode=None):
    """텔레그램 메시지를 보낸다. 발송 간격을 지키고, 요청 제한(429)이면 기다렸다 재시도."""
    global _last_send_at
    wait = _last_send_at + SEND_INTERVAL - time.time()
    if wait > 0:
        time.sleep(wait)
    payload = {"chat_id": chat_id, "text": text}
    if disable_preview:
        payload["disable_web_page_preview"] = True
    if parse_mode:
        payload["parse_mode"] = parse_mode
    for attempt in range(TELEGRAM_SEND_ATTEMPTS):
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=30,
        )
        if response.status_code == 429:
            if attempt == TELEGRAM_SEND_ATTEMPTS - 1:
                response.raise_for_status()
            retry_after = 5
            try:
                retry_after = response.json()["parameters"]["retry_after"]
            except Exception:
                pass
            logger.warning("telegram rate limit, retrying in %ss", retry_after)
            time.sleep(retry_after + 1)
            continue
        response.raise_for_status()
        break
    _last_send_at = time.time()


def fetch_all(blog_ids):
    """모든 블로그의 RSS를 동시에 가져온다. 실패한 블로그는 None."""
    results = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = {executor.submit(naver_blog.fetch_posts, bid): bid for bid in blog_ids}
        for future in as_completed(futures):
            blog_id = futures[future]
            try:
                results[blog_id] = future.result()
            except Exception as e:
                logger.warning("failed to fetch %s: %s", blog_id, e)
                results[blog_id] = None
    return results


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    blog_ids = load_blog_ids()
    if not blog_ids:
        logger.info("blogs.txt에 등록된 블로그가 없습니다.")
        return

    seen = load_seen()
    results = fetch_all(blog_ids)

    started = []  # 이번에 새로 감시를 시작한 블로그 이름들
    failed = []  # 새로 추가됐지만 가져오지 못한 블로그 아이디들
    try:
        for blog_id in blog_ids:
            entry = seen.get(blog_id)
            result = results.get(blog_id)

            if result is None:
                if entry is None:
                    # 새로 추가된 블로그가 잘못된 주소일 수 있으니 한 번만 알려준다
                    failed.append(blog_id)
                    seen[blog_id] = {"name": blog_id, "links": [], "error": True}
                continue

            blog_name, posts = result
            links = [p["link"] for p in posts]

            if entry is None or entry.get("error"):
                # 새로 등록된 블로그: 기존 글은 알림 없이 기준선으로 저장
                seen[blog_id] = {"name": blog_name, "links": links[:SEEN_LINKS_KEEP]}
                started.append(blog_name)
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

        if started:
            if len(started) == 1:
                text = (
                    f"✅ '{started[0]}' 블로그 감시를 시작했습니다. "
                    "새 글이 올라오면 알려드릴게요."
                )
            else:
                text = (
                    f"✅ 새 블로그 {len(started)}개 감시를 시작했습니다. "
                    f"(현재 총 {len(blog_ids)}개 감시 중) 새 글이 올라오면 알려드릴게요."
                )
            send_message(token, chat_id, text)

        if failed:
            shown = ", ".join(failed[:20])
            more = f" 외 {len(failed) - 20}개" if len(failed) > 20 else ""
            send_message(
                token, chat_id,
                f"⚠️ 다음 블로그의 정보를 가져오지 못했습니다: {shown}{more}\n"
                "blogs.txt에 적은 주소를 확인해주세요.",
            )

        # blogs.txt에서 지워진 블로그의 기록은 정리 (다시 추가하면 새로 시작)
        seen = {bid: seen[bid] for bid in blog_ids if bid in seen}
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
    # 매일 새벽 04시대(KST) 실행분에서 하루 1회 자가점검 리포트 발송
    try:
        import health_check

        health_check.maybe_report()
    except Exception:
        logger.exception("자가점검 실행 실패 (본 감시에는 영향 없음)")
