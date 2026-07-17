"""한국 IP 서버(오라클 서울 리전 VM, 집 서버 등)에서 cron으로 돌리는 감시 스크립트.

GitHub Actions(해외 IP)에서 차단·불안정한 한국 정부사이트를 '한국 IP에서 직접'
접속해 감시한다. 현재 대상:
1) 서울정보소통광장(opengov.seoul.go.kr) 결재문서 실시간 — 서울시 본청·사업소
2) 정보공개포털(open.go.kr) 기관장 결재문서 — 서울시 본청 + 감시 대상 14개 자치구

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
from datetime import date, timedelta
from urllib.parse import urlencode

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

# ── 정보공개포털(open.go.kr) 원문정보 검색 ──
# GitHub Actions(해외 IP)에서는 2/3 확률로 타임아웃 나던 사이트라 한국 IP에서 돌린다.
# '기관장 결재문서'(mnstrSanDocList)에는 서울 문서가 없어서, 서울시·자치구 문서가
# 실제로 올라오는 '원문정보' 목록(orginlInfoList)을 검색한다.
# seen_korea.json 안에서 opengov 문서번호와 구분하기 위해 접두사를 붙인다.
OPEN_PORTAL_PAGE = "https://www.open.go.kr/othicInfo/infoList/orginlInfoList.do"
OPEN_PORTAL_AJAX = "https://www.open.go.kr/othicInfo/infoList/orginlInfoList.ajax"
OPEN_PREFIX = "open:"
OPEN_PORTAL_DAYS = 30  # 최근 30일 문서만 검색(중복은 seen 파일로 걸러짐)

# 감시 대상 14개 자치구 (서울시 본청은 항상 포함)
TARGET_GU = (
    "강남구", "강동구", "광진구", "동대문구", "동작구", "마포구", "서대문구",
    "서초구", "성동구", "송파구", "영등포구", "용산구", "종로구", "중구",
)

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


def matches(item):
    return any(k in item["title"] for k in KEYWORDS)


def collect_open_portal():
    """정보공개포털에서 키워드별로 기관장 결재문서를 검색해 서울 기관 것만 반환.

    검색 API는 첨부 본문까지 찾으므로 제목에 키워드가 실제로 있는지 재검사하고,
    기관명이 서울시 본청 또는 감시 대상 자치구인 것만 통과시킨다.
    """
    today = date.today()
    start = today - timedelta(days=OPEN_PORTAL_DAYS)
    session = requests.Session()
    # 검색 화면을 먼저 열어 세션 쿠키를 받는다.
    page = session.get(OPEN_PORTAL_PAGE, headers={"User-Agent": USER_AGENT}, timeout=(15, 40))
    page.raise_for_status()
    # 페이지 폼의 기본 필드(숨은 토큰 포함)를 그대로 싣고, 검색 조건만 덮어쓴다.
    page_soup = BeautifulSoup(page.text, "html.parser")
    base_payload = {}
    for el in page_soup.find_all(["input", "select"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            base_payload.setdefault(name, (opt.get("value") or "") if opt else "")
        else:
            base_payload.setdefault(name, el.get("value") or "")

    if DEBUG:
        logger.info("[DEBUG] 원문정보 페이지 폼 필드(%d개): %s",
                    len(base_payload), json.dumps(base_payload, ensure_ascii=False)[:1200])
        # 본문 안의 orginlInfoList.ajax 호출부를 전부(주변 코드 포함) 출력
        for n, m2 in enumerate(re.finditer(r"orginlInfoList\.ajax", page.text)):
            snippet = page.text[max(0, m2.start() - 1000):m2.start() + 300]
            logger.info("[DEBUG] 본문 ajax 호출부 #%d:\n%s", n + 1, snippet)
        # 검색 로직이 외부 JS에 있을 수 있어 관련 JS 파일도 뒤져본다.
        scripts = [s.get("src") for s in page_soup.find_all("script") if s.get("src")]
        related = [s for s in scripts
                   if any(t in s for t in ("orginl", "infoList", "othic", "search", "cmmn", "common"))]
        logger.info("[DEBUG] 외부 JS %d개 중 관련 후보 %d개: %s", len(scripts), len(related), related)
        for src in related[:8]:
            full = src if src.startswith("http") else "https://www.open.go.kr" + src
            try:
                js = session.get(full, headers={"User-Agent": USER_AGENT}, timeout=(15, 30)).text
            except Exception as e:
                logger.info("[DEBUG] JS 받기 실패 %s: %s", full, e)
                continue
            i = js.find("orginlInfoList.ajax")
            if i >= 0:
                logger.info("[DEBUG] %s 의 ajax 호출부:\n%s", full, js[max(0, i - 2500):i + 800])
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": OPEN_PORTAL_PAGE,
        "X-Requested-With": "XMLHttpRequest",
    }

    items_by_id = {}
    searched_rows = 0
    sample_agencies = {}
    for keyword in KEYWORDS:
        payload = dict(base_payload)
        payload.update({
            "kwd": keyword,
            "preKwds": keyword,
            "reSrchFlag": "off",
            "eduYn": "N",
            "startDate": start.strftime("%Y%m%d"),
            "endDate": today.strftime("%Y%m%d"),
            "viewPage": "1",
            "rowPage": "100",
            "sort": "s",
        })
        response = session.post(OPEN_PORTAL_AJAX, data=payload, headers=headers, timeout=(15, 50))
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            if DEBUG:
                logger.info("[DEBUG] 정보공개포털(%s) JSON 아님, 본문 앞부분: %s",
                            keyword, response.text[:500])
            raise RuntimeError(f"정보공개포털 응답이 JSON이 아님({keyword})")
        result = data.get("result") or data
        if DEBUG and keyword == KEYWORDS[0]:
            logger.info("[DEBUG] 정보공개포털 응답 최상위 키: %s / result 키: %s",
                        list(data.keys()), list(result.keys()) if isinstance(result, dict) else type(result))
        if str(result.get("code")) != "200":
            if DEBUG:
                # 서버가 기대하는 파라미터 이름이 parameterVO/paramJson에 들어있다
                logger.info("[DEBUG] parameterVO: %s",
                            json.dumps(data.get("parameterVO") or result.get("parameterVO") or {},
                                       ensure_ascii=False)[:1500])
                logger.info("[DEBUG] paramJson: %s", str(data.get("paramJson"))[:800])
            raise RuntimeError(
                f"정보공개포털 API 오류({keyword}): {result.get('code')} "
                f"{result.get('message') or result.get('rtnMsg') or ''}"
            )
        rows = result.get("rtnList") or []
        if DEBUG and rows and keyword == KEYWORDS[0]:
            first = {k: str(v)[:60] for k, v in rows[0].items()}
            logger.info("[DEBUG] 정보공개포털 첫 행 필드: %s", first)
        searched_rows += len(rows)
        for row in rows:
            title = str(row.get("INFO_SJ") or "").strip()
            if not title or keyword not in title:
                continue

            agency = str(row.get("PROC_INSTT_NM") or "").strip()
            department = str(row.get("NFLST_CHRG_DEPT_NM") or "").strip()
            sample_agencies[agency] = sample_agencies.get(agency, 0) + 1
            is_seoul = agency == "서울특별시" or any(
                agency == f"서울특별시 {gu}" or f"서울특별시 {gu}" in department
                for gu in TARGET_GU
            )
            if not is_seoul:
                continue

            doc_id = str(row.get("PRDCTN_INSTT_REGIST_NO") or "").strip()
            produced = str(row.get("PRDCTN_DT") or "").strip()
            inst_type = str(row.get("INSTT_SE_CD") or "").strip()
            if not doc_id:
                continue
            query = urlencode({
                "prdnNstRgstNo": doc_id,
                "prdnDt": produced,
                "nstSeCd": inst_type,
                "title": "기관장결재문서",
            })
            date_value = ""
            if len(produced) >= 8 and produced[:8].isdigit():
                date_value = f"{produced[:4]}-{produced[4:6]}-{produced[6:8]}"
            items_by_id[doc_id] = {
                "id": OPEN_PREFIX + doc_id,
                "title": title,
                "agency": agency,
                "date": date_value,
                "link": "https://www.open.go.kr/othicInfo/infoList/infoListDetl3.do?" + query,
            }

    items = sorted(items_by_id.values(), key=lambda x: x["date"])
    logger.info("정보공개포털: 검색 행 %d개, 제목·서울기관 통과 %d건", searched_rows, len(items))
    if DEBUG:
        top = sorted(sample_agencies.items(), key=lambda kv: -kv[1])[:15]
        logger.info("[DEBUG] 정보공개포털 제목매칭 기관 분포: %s", top)
        for x in items[:15]:
            logger.info("[DEBUG]★ %s [%s|%s] %s", x["id"], x["date"], x["agency"], x["title"][:60])
    return items


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


def format_alert(x, source):
    date_part = f" ({x['date']})" if x["date"] else ""
    agency_part = f"[{x['agency']}] " if x.get("agency") else ""
    emoji = "🏛️" if source == "opengov" else "📄"
    label = "결재문서" if source == "opengov" else "결재문서(정보공개포털)"
    return f"{emoji} {agency_part}{label}{date_part}\n{x['title']}\n{x['link']}"


def main():
    session = requests.Session()

    # 1) 서울정보소통광장(opengov) 결재문서
    items = collect(session)
    matched = [x for x in items if matches(x)]
    logger.info("결재문서 링크 %d개, 재개발 키워드 통과 %d개", len(items), len(matched))

    # 2) 정보공개포털(open.go.kr) 기관장 결재문서 — 실패해도 opengov 감시는 계속
    try:
        portal_items = collect_open_portal()
    except Exception as e:
        logger.warning("정보공개포털 조회 실패(이번 회차 건너뜀): %s", e)
        portal_items = []

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
        save_seen([x["id"] for x in matched] + [x["id"] for x in portal_items])
        send_message(
            token, chat_id,
            "🏛️ [서울정보소통광장] 결재문서 실시간 감시를 시작했습니다. "
            "재개발·신속통합·모아타운·도심복합 등 관련 결재문서가 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d개 저장", len(matched) + len(portal_items))
        return

    known = set(seen)
    saved = list(seen)

    # 정보공개포털을 처음 켜는 회차: 알림 없이 기준선만 추가 저장
    portal_first = portal_items and not any(s.startswith(OPEN_PREFIX) for s in known)
    if portal_first:
        saved.extend(x["id"] for x in portal_items)
        save_seen(saved)
        send_message(
            token, chat_id,
            "📄 [정보공개포털] 서울시·자치구 결재문서 감시를 노트북에서 시작했습니다. "
            "같은 키워드(재개발·신속통합·모아타운·도심복합 등)로 새 문서가 올라오면 알려드릴게요.",
        )
        logger.info("정보공개포털 첫 회차: 기준선 %d개 저장", len(portal_items))
        known = set(saved)

    # 오래된 것부터 발송 (opengov 목록은 최신순이라 뒤집고, 포털은 이미 날짜 오름차순)
    to_send = [(x, "opengov") for x in reversed(matched) if x["id"] not in known]
    to_send += [(x, "portal") for x in portal_items if x["id"] not in known]
    try:
        for x, source in to_send:
            send_message(token, chat_id, format_alert(x, source), disable_preview=True)
            saved.append(x["id"])
            logger.info("알림: %s", x["title"][:60])
    finally:
        save_seen(saved)


if __name__ == "__main__":
    main()
