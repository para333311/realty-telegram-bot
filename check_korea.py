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
# 수집 방식이 '전체 목록 스캔' → '서버 키워드 검색'으로 바뀐 뒤 첫 회차에
# 검색이 새로 찾아낸 과거 문서들이 한꺼번에 알림되는 것을 막는 표식.
SEARCH_MARKER = "opengov-search-v1"
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
    for kw in KEYWORDS:
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

    # 기관유형(insttSeCd) 체크박스: 사이트 JS가 체크된 값들을 콤마로 합쳐 보낸다.
    # 빈값이면 서버가 491(파라미터 오류)을 내는 것으로 보여, 전체 유형을 선택해 보낸다.
    instt_vals = [el.get("value") for el in page_soup.find_all("input", attrs={"name": "insttSeCd"})
                  if el.get("value")]
    if instt_vals:
        base_payload["insttSeCd"] = ",".join(dict.fromkeys(instt_vals))

    if DEBUG:
        logger.info("[DEBUG] insttSeCd 체크박스 값: %s", instt_vals)
        # 전송 방식(폼/JSON) 확인용 — 실제 사이트의 util_ajax 정의를 덤프
        try:
            js = session.get("https://www.open.go.kr/js/ops-common.js",
                             headers={"User-Agent": USER_AGENT}, timeout=(15, 30)).text
            i = js.find("util_ajax")
            if i >= 0:
                logger.info("[DEBUG] util_ajax 정의:\n%s", js[i:i + 1200])
        except Exception as e:
            logger.info("[DEBUG] ops-common.js 받기 실패: %s", e)
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": OPEN_PORTAL_PAGE,
        "X-Requested-With": "XMLHttpRequest",
    }

    working_mode = []  # 성공한 전송 방식을 기억해 다음 키워드부터 바로 사용

    def search_once(keyword):
        # 사이트 JS(searchFn)의 param 객체와 동일한 구성
        js_param = {
            "kwd": keyword,
            "searchInsttCdNmPop": "",
            "preKwds": keyword,
            "reSrchFlag": "off",
            "othbcSeCd": base_payload.get("othbcSeCd", ""),
            "insttSeCd": base_payload.get("insttSeCd", ""),
            "eduYn": "N",
            "startDate": start.strftime("%Y%m%d"),
            "endDate": today.strftime("%Y%m%d"),
            "insttCdNm": "",
            "insttCd": "",
            "searchMainYn": "",
            "viewPage": 1,
            "rowPage": "100",
            "sort": "s",
        }
        full_form = dict(base_payload)
        full_form.update({k: str(v) for k, v in js_param.items()})
        # form-min: 사이트 JS param만 폼 전송 / json: JSON 본문 / form-full: 폼 기본값 포함
        modes = list(working_mode) or ["form-min", "json", "form-full"]
        last_code = None
        for mode in modes:
            if mode == "json":
                resp = session.post(OPEN_PORTAL_AJAX, json=js_param, headers=headers, timeout=(15, 50))
            elif mode == "form-full":
                resp = session.post(OPEN_PORTAL_AJAX, data=full_form, headers=headers, timeout=(15, 50))
            else:
                resp = session.post(OPEN_PORTAL_AJAX, data=js_param, headers=headers, timeout=(15, 50))
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                if DEBUG:
                    logger.info("[DEBUG] 정보공개포털 %s 방식 JSON 아님, 본문: %s", mode, resp.text[:300])
                last_code = "non-json"
                continue
            result = data.get("result") or data
            last_code = str(result.get("code"))
            if DEBUG:
                logger.info("[DEBUG] 정보공개포털 '%s' %s 방식 → 코드 %s", keyword, mode, last_code)
            if last_code == "200":
                if not working_mode:
                    working_mode.append(mode)
                    logger.info("정보공개포털 전송 방식 확정: %s", mode)
                return result
        raise RuntimeError(f"정보공개포털 API 오류({keyword}): 모든 전송 방식 실패(마지막 코드 {last_code})")

    items_by_id = {}
    searched_rows = 0
    sample_agencies = {}
    for keyword in KEYWORDS:
        result = search_once(keyword)
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

    # 1) 서울정보소통광장(opengov) 결재문서 — 서버 검색 우선, 실패시 목록 스캔 폴백
    items = collect_by_search(session)
    if items is None:
        logger.info("opengov 서버 검색 실패 → 전체 목록 스캔으로 폴백")
        items = collect(session)
    matched = sorted(
        (x for x in items if matches(x)),
        key=lambda x: x["date"],
    )
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
        save_seen([SEARCH_MARKER] + [x["id"] for x in matched] + [x["id"] for x in portal_items])
        send_message(
            token, chat_id,
            "🏛️ [서울정보소통광장] 결재문서 실시간 감시를 시작했습니다. "
            "재개발·신속통합·모아타운·도심복합 등 관련 결재문서가 올라오면 알려드릴게요.",
        )
        logger.info("첫 실행: 기준선 %d개 저장", len(matched) + len(portal_items))
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

    # 정보공개포털을 처음 켜는 회차: 알림 없이 기준선만 추가 저장
    portal_first = portal_items and not any(s.startswith(OPEN_PREFIX) for s in known)
    if portal_first:
        saved.extend(x["id"] for x in portal_items)
        save_seen(saved + [SEARCH_MARKER])
        send_message(
            token, chat_id,
            "📄 [정보공개포털] 서울시·자치구 결재문서 감시를 노트북에서 시작했습니다. "
            "같은 키워드(재개발·신속통합·모아타운·도심복합 등)로 새 문서가 올라오면 알려드릴게요.",
        )
        logger.info("정보공개포털 첫 회차: 기준선 %d개 저장", len(portal_items))
        known = set(saved)

    # 오래된 것부터 발송 (둘 다 날짜 오름차순 정렬됨)
    to_send = [(x, "opengov") for x in matched if x["id"] not in known]
    to_send += [(x, "portal") for x in portal_items if x["id"] not in known]
    try:
        for x, source in to_send:
            send_message(token, chat_id, format_alert(x, source), disable_preview=True)
            saved.append(x["id"])
            logger.info("알림: %s", x["title"][:60])
    finally:
        save_seen(saved + [SEARCH_MARKER])


if __name__ == "__main__":
    main()
