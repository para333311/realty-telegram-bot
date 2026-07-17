"""한국 IP 서버(오라클 서울 리전 VM, 집 서버 등)에서 cron으로 돌리는 감시 스크립트.

GitHub Actions(해외 IP)에서 차단·불안정한 한국 정부사이트를 '한국 IP에서 직접'
접속해 감시한다. 현재 대상: 서울정보소통광장(opengov.seoul.go.kr) 결재문서 실시간.

GitHub Actions 쪽 스크립트들과 역할이 겹치지 않게 분리돼 있다:
- 상태(확인한 문서)는 이 서버 로컬 파일(seen_korea.json)에만 저장한다. git에 커밋하지
  않으므로 GitHub Actions의 seen_*.json과 충돌하지 않는다.
- 알림은 GitHub Actions와 동일한 텔레그램 봇으로 보낸다
  (BOARD_BOT_TOKEN, TELEGRAM_CHAT_ID) → 사용자는 같은 채팅에서 함께 받는다.
- 첫 실행은 알림 없이 현재 목록을 기준선으로 저장한다.

환경변수:
- BOARD_BOT_TOKEN, TELEGRAM_CHAT_ID (GitHub Actions와 같은 값)

디버그:
- DEBUG=1 로 실행하면 실제 응답 상태·파싱된 항목을 출력한다(알림/저장 안 함).
  opengov 페이지 구조를 VM에서 처음 확인할 때 사용.
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

BASE = "https://opengov.seoul.go.kr"
LIST_URL = BASE + "/sanction/list"
SEEN_FILE = "seen_korea.json"
SEEN_KEEP = 3000
FETCH_PAGES = 5  # 30분마다 도니 최근 몇 페이지만 훑어도 새 문서를 놓치지 않는다
DEBUG = os.environ.get("DEBUG", "").strip() not in ("", "0", "false", "False")

# 재개발 관련 키워드(제목 기준)
KEYWORDS = [
    "재개발", "재건축", "신속통합", "모아타운", "도심복합",
    "정비계획", "정비구역", "정비사업", "후보지", "동의서",
]

# opengov는 서울시 전용이라(본청+자치구) 별도 '서울' 필터는 필요 없다.
# 상세문서 링크 형식: https://opengov.seoul.go.kr/sanction/{숫자}
SANCTION_RE = re.compile(r"/sanction/(\d+)")
DATE_RE = re.compile(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def fetch_page(session, page):
    """결재문서 목록 한 페이지를 가져와 (id, 제목, 기관/부서, 날짜, 링크) 목록을 반환."""
    # opengov 목록의 페이지 파라미터는 서버 확인 후 조정될 수 있다(디버그 모드로 검증).
    params = {"page": page} if page > 1 else {}
    r = session.get(
        LIST_URL, params=params,
        headers={"User-Agent": USER_AGENT, "Referer": LIST_URL},
        timeout=(15, 40),
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    if DEBUG and page == 1:
        logger.info("[DEBUG] HTTP %s, 본문 %d바이트", r.status_code, len(r.text))

    items = []
    seen_ids = set()
    # /sanction/{id} 로 연결되는 링크를 기준으로 각 문서 행을 잡는다.
    for a in soup.find_all("a", href=SANCTION_RE):
        m = SANCTION_RE.search(a.get("href", ""))
        if not m:
            continue
        doc_id = m.group(1)
        if doc_id in seen_ids:
            continue
        # 제목: <strong class="element-invisible">제목 : </strong>는 화면낭독기 전용
        # 숨김 라벨이라 제외하고, 옆의 <span> 실제 제목만 사용한다.
        title_span = a.find("span")
        title = title_span.get_text(" ", strip=True) if title_span else a.get_text(" ", strip=True)
        title = re.sub(r"^제목\s*[:：]\s*", "", title).strip()
        if len(title) < 5:
            continue
        # title-wrap div: 제목 + <p class="title-category">공개여부/기관명</p>
        title_wrap = a.find_parent("div", class_="title-wrap") or a.find_parent(["li", "tr", "div"]) or a.parent
        agency = ""
        category_p = title_wrap.find("p", class_="title-category") if title_wrap else None
        if category_p:
            spans = category_p.find_all("span")
            if spans:
                agency = spans[-1].get_text(strip=True)
        # 날짜는 title-wrap/title-area 안에도 없어서, 두 단계 더 위(행 전체)에서 찾는다.
        outer_row = title_wrap.find_parent(["li", "tr", "div"]) if title_wrap else None  # title-area
        grand_row = outer_row.find_parent(["li", "tr", "div"]) if outer_row else None    # 그 위(행 전체)
        date_source = grand_row or outer_row or title_wrap or a.parent
        row_text = date_source.get_text(" ", strip=True) if date_source else title
        date_m = DATE_RE.search(row_text)
        date_val = date_m.group(0).replace(".", "-") if date_m else ""
        seen_ids.add(doc_id)
        item = {
            "id": doc_id,
            "title": title,
            "agency": agency,
            "date": date_val,
            "link": f"{BASE}/sanction/{doc_id}",
            "row_text": row_text[:250],
        }
        if DEBUG:
            # [DEBUG] 날짜를 못 찾을 때 원인 파악용으로, 더 넓은 범위의 HTML을 남긴다.
            widest = grand_row or outer_row or title_wrap
            item["raw_html"] = str(widest)[:1500] if widest else str(a)[:1500]
        items.append(item)
    return items


def collect(session):
    all_items = {}
    for page in range(1, FETCH_PAGES + 1):
        try:
            items = fetch_page(session, page)
        except Exception as e:
            logger.warning("%d페이지 조회 실패: %s", page, e)
            break
        if not items:
            break
        for it in items:
            all_items.setdefault(it["id"], it)
        if DEBUG:
            logger.info("[DEBUG] %d페이지: 문서 링크 %d개", page, len(items))
    return list(all_items.values())


def matches(item):
    return any(k in item["title"] for k in KEYWORDS)


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return list(json.load(f))
    except (json.JSONDecodeError, ValueError):
        return None


def save_seen(ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids)[-SEEN_KEEP:], f, ensure_ascii=False)
        f.write("\n")


def main():
    session = requests.Session()
    items = collect(session)
    matched = [x for x in items if matches(x)]
    logger.info("결재문서 링크 %d개, 재개발 키워드 통과 %d개", len(items), len(matched))

    if DEBUG:
        for x in items[:15]:
            hit = "★" if matches(x) else " "
            logger.info("[DEBUG]%s id=%s [%s|%s] %s", hit, x["id"], x["date"], x.get("agency", ""), x["title"][:60])
        logger.info("[DEBUG] 첫 행 원본텍스트 예: %s", items[0]["row_text"] if items else "(없음)")
        # [DEBUG] 날짜/제목 파싱 정밀 튜닝을 위해 실제 행 HTML을 그대로 보여준다.
        for i, x in enumerate(items[:3]):
            logger.info("[DEBUG] 행%d 원본HTML: %s", i + 1, x.get("raw_html", ""))
        logger.info("[DEBUG] 디버그 모드: 알림/저장 생략")
        return

    token = os.environ.get("BOARD_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("BOARD_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다")

    seen = load_seen()
    if seen is None:
        # 첫 실행: 현재 매칭 문서를 알림 없이 기준선으로 저장
        save_seen([x["id"] for x in matched])
        send_message(
            token, chat_id,
            "🏛️ [서울정보소통광장] 결재문서 실시간 감시를 시작했습니다. "
            "재개발·신속통합·모아타운·도심복합 등 관련 결재문서가 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d개 저장", len(matched))
        return

    known = set(seen)
    new_items = [x for x in matched if x["id"] not in known]
    saved = list(seen)
    try:
        # 오래된 것부터(목록은 최신순) 발송
        for x in reversed(new_items):
            date_part = f" ({x['date']})" if x["date"] else ""
            agency_part = f"[{x['agency']}] " if x.get("agency") else ""
            send_message(
                token, chat_id,
                f"🏛️ {agency_part}결재문서{date_part}\n{x['title']}\n{x['link']}",
                disable_preview=True,
            )
            saved.append(x["id"])
            logger.info("알림: %s", x["title"][:60])
    finally:
        save_seen(saved)


if __name__ == "__main__":
    main()
