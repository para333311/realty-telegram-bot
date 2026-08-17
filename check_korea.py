"""한국 IP 서버(오라클 서울 리전 VM, 집 서버 등)에서 cron으로 돌리는 감시 스크립트.

GitHub Actions(해외 IP)에서 차단·불안정한 한국 정부사이트를 '한국 IP에서 직접'
접속해 감시한다. 현재 대상:
- 서울정보소통광장(opengov.seoul.go.kr) 결재문서 — 서버 키워드 검색으로
  서울시 본청 + 사업소 + 25개 자치구 결재문서를 모두 커버한다.

정보공개포털(open.go.kr)은 서울 문서에 한해 opengov와 동일 내용의 중복 창구라
연동하지 않는다(2026-07-17 확인: orginlInfoList.ajax는 브라우저 외 요청을 491로
거부하며, opengov 검색 결과에 자치구 문서까지 포함됨을 확인).

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
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from check_once import send_message, title_matches

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
# 수집 방식이 '전체 목록 스캔' → '서버 키워드 검색'으로 바뀐 뒤 첫 회차에
# 검색이 새로 찾아낸 과거 문서들이 한꺼번에 알림되는 것을 막는 표식.
SEARCH_MARKER = "opengov-search-v1"
# 하루 1회 생존 신호(하트비트) 기록 접두어 — seen 목록에 "hb:YYYY-MM-DD"로 저장.
# 새 문서가 없는 날이라도 이 메시지가 오면 스크립트가 살아있다는 뜻이다.
# (침묵이 '새 소식 없음'인지 'PC 절전/스케줄러 중단'인지 구분하기 위함)
HEARTBEAT_PREFIX = "hb:"
KST = timezone(timedelta(hours=9))
FETCH_PAGES = 5  # 30분마다 도니 최근 몇 페이지만 훑어도 새 문서를 놓치지 않는다
# 요청 사이 간격(초). 실행당 키워드 수만큼(현재 14회) 연속 요청이 나가므로
# 정부 사이트에 몰아치지 않도록 간격을 둔다. 30분 주기라 20초쯤 늘어도 무방하다.
REQUEST_DELAY = 1.5
DEBUG = os.environ.get("DEBUG", "").strip() not in ("", "0", "false", "False")

# 재개발 관련 키워드(제목 기준)
# 키워드마다 서버 검색을 1회씩 보내므로(개당 약 3초) 무한정 늘리지 않고,
# 도시정비 문서에서만 쓰이는 표현 위주로 둔다. '역세권·지구단위계획'처럼
# 일상 결재문서에도 흔한 말은 소음이 커서 뺐다.
KEYWORDS = [
    "재개발", "재건축", "신속통합", "모아타운", "도심복합",
    "정비계획", "정비구역", "정비사업", "후보지", "동의서",
    "재정비촉진", "가로주택", "조합설립", "관리처분",
]

# opengov는 서울시 전용이라(본청+자치구) 별도 '서울' 필터는 필요 없다.
# 상세문서 링크 형식: https://opengov.seoul.go.kr/sanction/{숫자}
SANCTION_RE = re.compile(r"/sanction/(\d+)")
DATE_RE = re.compile(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def fetch_page(session, page, extra_params=None):
    """결재문서 목록 한 페이지를 가져와 (id, 제목, 기관/부서, 날짜, 링크) 목록을 반환.

    extra_params에 {"searchKeyword": "재개발"} 등을 주면 서버단 검색 결과를 받는다
    (목록 페이지 폼 필드로 확인됨: searchField/searchKeyword/startDate/endDate 등).
    """
    params = dict(extra_params or {})
    if page > 1:
        params["page"] = page
    r = session.get(
        LIST_URL, params=params,
        headers={"User-Agent": USER_AGENT, "Referer": LIST_URL},
        timeout=(15, 40),
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

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

        # 실제 페이지 구조(디버그로 확인됨):
        # <li>
        #   <div class="title-area">
        #     <div class="title-wrap"><a><strong class="element-invisible">제목 : </strong>
        #       <span>실제제목</span></a><p class="title-category"><span>공개여부</span><span>기관명</span></p>
        #     </div>
        #   </div>
        #   <p class="title-info">
        #     <span class="date"><strong class="element-invisible">등록일 : </strong> 날짜</span>
        #     <span class="dept"><strong class="element-invisible">부서 : </strong> 담당부서</span>
        #   </p>
        # </li>

        # 제목: "제목 : " 라벨(화면낭독기 전용)은 제외하고 옆 <span> 실제 텍스트만 사용
        title_span = a.find("span")
        title = title_span.get_text(" ", strip=True) if title_span else a.get_text(" ", strip=True)
        title = re.sub(r"^제목\s*[:：]\s*", "", title).strip()
        if len(title) < 5:
            continue

        li_row = a.find_parent("li") or a.find_parent(["tr", "div"]) or a.parent

        agency = ""
        category_p = li_row.find("p", class_="title-category") if li_row else None
        if category_p:
            spans = category_p.find_all("span")
            if spans:
                agency = spans[-1].get_text(strip=True)

        date_val, dept = "", ""
        info_p = li_row.find("p", class_="title-info") if li_row else None
        if info_p:
            date_span = info_p.find("span", class_="date")
            if date_span:
                date_val = re.sub(r"^등록일\s*[:：]\s*", "", date_span.get_text(" ", strip=True)).strip()
            dept_span = info_p.find("span", class_="dept")
            if dept_span:
                dept = re.sub(r"^부서\s*[:：]\s*", "", dept_span.get_text(" ", strip=True)).strip()

        if not date_val:
            # 폴백: 구조가 다른 행이면 li 전체 텍스트에서 정규식으로 날짜를 찾는다.
            row_text = li_row.get_text(" ", strip=True) if li_row else title
            date_m = DATE_RE.search(row_text)
            date_val = date_m.group(0).replace(".", "-") if date_m else ""

        seen_ids.add(doc_id)
        item = {
            "id": doc_id,
            "title": title,
            "agency": dept or agency,  # 부서명이 더 구체적이라 우선 사용
            "date": date_val,
            "link": f"{BASE}/sanction/{doc_id}",
        }
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


def collect_by_search(session):
    """opengov 서버단 키워드 검색으로 수집한다.

    전체 목록을 훑는 방식(collect)은 30분 사이 전체 결재문서가 75건을 넘으면
    사이에 낀 문서를 놓칠 수 있는데, 서버 검색은 키워드별 결과만 받으므로
    그 위험이 없다. 검색이 비정상(전 키워드 0건)이면 None을 반환해 폴백한다.
    """
    all_items = {}
    for index, kw in enumerate(KEYWORDS):
        if index:
            time.sleep(REQUEST_DELAY)  # 연달아 두드리지 않도록 간격을 둔다
        try:
            items = fetch_page(session, 1, {"searchKeyword": kw})
        except Exception as e:
            logger.warning("opengov 검색(%s) 실패: %s", kw, e)
            return None
        if DEBUG:
            logger.info("[DEBUG] opengov 검색 '%s': %d건", kw, len(items))
        for it in items:
            all_items.setdefault(it["id"], it)
    if not all_items:
        # '재개발' 등이 전부 0건일 수는 없으므로 파라미터가 안 먹는 것으로 보고 폴백
        return None
    return list(all_items.values())


def matches(item):
    return title_matches(item["title"], KEYWORDS)


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


def format_alert(x):
    """알림 메시지를 만든다.

    2026-07-28 원인 확정: 링크 자체나 사이트 정책 문제가 아니라 텔레그램
    인앱 브라우저(웹뷰)가 opengov 상세페이지 접근 시 막히는 것이었다
    (카카오톡 웹뷰·외부 브라우저는 정상 동작 확인됨). 그래서 결재문서
    직접 주소를 다시 그대로 보낸다 — 링크를 탭하면 안 열릴 수 있지만,
    길게 눌러 "다른 브라우저에서 열기"를 선택하면 정상적으로 열린다.
    """
    date_part = f" ({x['date']})" if x["date"] else ""
    agency_part = f"[{x['agency']}] " if x.get("agency") else ""
    return f"🏛️ {agency_part}결재문서{date_part}\n{x['title']}\n{x['link']}"


def self_update():
    """실행 시마다 git pull로 최신 코드를 받고, 코드가 바뀌었으면 재실행한다.

    VM/집 PC에 접속해서 수동으로 git pull 할 필요를 없앤다.
    - 저장소가 아니거나 네트워크 오류면 조용히 건너뛴다(감시가 우선).
    - 무한 재실행 방지: 재실행된 프로세스는 환경변수 표식으로 다시 pull하지 않는다.
    - os.execve 대신 subprocess로 새 프로세스를 띄우고 끝날 때까지 기다린다.
      윈도우는 진짜 exec(프로세스 이미지 교체)이 없어 os.execve가 '새 프로세스를
      띄우고 원래 프로세스는 즉시 종료'하는 방식으로 동작하는데, 그러면 PowerShell이
      원래 프로세스 종료를 보고 바로 명령 프롬프트를 돌려줘서 실제 작업(알림 발송)이
      끝나기도 전에 실행이 끝난 것처럼 보인다(작업 스케줄러에서는 새 프로세스가
      부모 종료와 함께 강제 종료될 위험도 있음). subprocess.run으로 자식이 끝날
      때까지 부모가 살아서 기다리면 두 문제 다 없어진다.
    """
    if os.environ.get("KOREA_SELF_UPDATED"):
        return
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir,
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        result = subprocess.run(
            ["git", "pull", "--ff-only"], cwd=repo_dir,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.info("자동 업데이트 건너뜀: %s", (result.stderr or result.stdout).strip()[:200])
            return
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir,
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if before and after and before != after:
            logger.info("코드 업데이트됨 (%s → %s): 새 코드로 재실행", before[:7], after[:7])
            env = dict(os.environ, KOREA_SELF_UPDATED="1")
            completed = subprocess.run(
                [sys.executable, os.path.abspath(__file__)], cwd=repo_dir, env=env,
            )
            sys.exit(completed.returncode)
    except Exception as exc:  # noqa: BLE001 - 업데이트 실패가 감시를 막으면 안 됨
        logger.info("자동 업데이트 실패(무시): %s", exc)


def main():
    self_update()
    session = requests.Session()

    # 서울정보소통광장(opengov) 결재문서 — 서버 검색 우선, 실패시 목록 스캔 폴백
    items = collect_by_search(session)
    if items is None:
        logger.info("opengov 서버 검색 실패 → 전체 목록 스캔으로 폴백")
        items = collect(session)
    matched = sorted(
        (x for x in items if matches(x)),
        key=lambda x: x["date"],
    )
    logger.info("결재문서 링크 %d개, 재개발 키워드 통과 %d개", len(items), len(matched))

    if DEBUG:
        for x in items[:15]:
            hit = "★" if matches(x) else " "
            logger.info("[DEBUG]%s id=%s [%s|%s] %s", hit, x["id"], x["date"], x.get("agency", ""), x["title"][:60])
        logger.info("[DEBUG] 디버그 모드: 알림/저장 생략")
        return

    token = os.environ.get("BOARD_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("BOARD_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다")

    seen = load_seen()
    if seen is None:
        # 첫 실행: 현재 매칭 문서를 알림 없이 기준선으로 저장
        save_seen([SEARCH_MARKER] + [x["id"] for x in matched])
        send_message(
            token, chat_id,
            "🏛️ [서울정보소통광장] 결재문서 실시간 감시를 시작했습니다. "
            "재개발·신속통합·모아타운·도심복합 등 관련 결재문서가 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d개 저장", len(matched))
        return

    known = set(seen)
    # 표식은 항상 목록 끝에 다시 넣어 오래돼도 잘려나가지 않게 한다
    saved = [s for s in seen if s != SEARCH_MARKER]

    if SEARCH_MARKER not in known:
        # 목록 스캔 → 서버 검색 전환 후 첫 회차: 검색이 새로 찾아낸 과거 문서들을
        # 알림 없이 기준선에 흡수한다(전환 직후 수십 건 알림 폭탄 방지).
        absorbed = [x["id"] for x in matched if x["id"] not in known]
        saved.extend(absorbed)
        known.update(absorbed)
        save_seen(saved + [SEARCH_MARKER])
        logger.info("opengov 검색 전환 기준선: %d건 알림 없이 흡수", len(absorbed))

    # 오래된 것부터 발송 (날짜 오름차순 정렬됨)
    to_send = [x for x in matched if x["id"] not in known]
    try:
        for x in to_send:
            send_message(token, chat_id, format_alert(x), disable_preview=True)
            saved.append(x["id"])
            logger.info("알림: %s", x["title"][:60])

        # 하루 1회 생존 신호: 그날(KST) 첫 성공 실행 때 한 번만 발송한다.
        hb_key = HEARTBEAT_PREFIX + datetime.now(KST).strftime("%Y-%m-%d")
        if hb_key not in known:
            send_message(
                token, chat_id,
                "🟢 [서울정보소통광장] 오늘도 정상 감시 중입니다 "
                f"(이번 실행: 결재문서 {len(items)}건 확인, 키워드 통과 {len(matched)}건). "
                "이 메시지가 하루 종일 안 오면 PC 스케줄러/절전 설정을 확인하세요.",
                disable_preview=True,
            )
            saved.append(hb_key)
            logger.info("하트비트 발송: %s", hb_key)
    finally:
        save_seen(saved + [SEARCH_MARKER])


if __name__ == "__main__":
    main()
