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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

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

BOARDS_FILE = "boards.txt"
SEEN_FILE = "seen_boards.json"
SEEN_KEEP = 300  # 게시판별로 보관할 확인한 공고 수
FETCH_WORKERS = 5
FETCH_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5

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


TITLE_KEYS = ("TITLE", "POST_TITLE", "SJ", "NTT_SJ", "SUBJECT", "DOC_NM", "NEWS_TITLE", "TIT")
DATE_RE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}")
# 한 글 행에서 여러 날짜(공고일·게시기간 종료일 등)를 모두 뽑기 위한 패턴(2자리 연도도 허용)
DATE_ALL_RE = re.compile(r"\d{2,4}[-./]\d{1,2}[-./]\d{1,2}")


def _parse_date(s):
    parts = re.split(r"[-./]", s)
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def pick_posting_date(candidates):
    """게시판 한 행에서 찾은 날짜 후보들 중 실제 '공고일'을 고른다.

    고시공고 목록은 공고일과 함께 게시기간 종료일(마감일, 미래 날짜)을 같이 보여주는
    경우가 많다. 스크래퍼가 실행마다 다른 칸을 잡으면 알림 날짜가 틀리거나(예: 8월로 표시)
    같은 글이 날짜별로 중복 알림되므로, 미래 날짜(마감일)는 배제하고 오늘까지의 날짜 중
    가장 최근(공고일)을 택한다. 판단이 불가하면 첫 후보를 그대로 쓴다.
    """
    if not candidates:
        return ""
    today = date.today()
    limit = today + timedelta(days=1)  # 러너(UTC)/게시판(KST) 시차 흡수용 하루 여유
    parsed = [(d, raw) for raw in candidates if (d := _parse_date(raw))]
    if not parsed:
        return candidates[0]
    past = [(d, raw) for d, raw in parsed if d <= limit]
    if past:
        return max(past, key=lambda p: p[0])[1]  # 오늘까지 중 가장 최근 = 공고일
    return min(parsed, key=lambda p: p[0])[1]     # 전부 미래면 가장 이른 날짜

# 서울 자치구 법정동 코드 앞 5자리 → 구 이름
SEOUL_GU_CODE = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}


def scrape_seoul_api(url, keywords, row_keywords=(), name=""):
    """서울 열린데이터광장 OpenAPI(JSON)에서 글 목록을 추출한다.

    boards.txt의 주소에 {KEY} 자리에는 SEOUL_API_KEY 환경변수 값이 들어간다.
    """
    key = os.environ.get("SEOUL_API_KEY", "").strip()
    if not key:
        key = "sample"  # 발급 전 테스트용 (5건 제한)
        logger.warning("SEOUL_API_KEY 미설정: sample 키로 호출합니다 (%s)", name or url)
    response = requests.get(url.replace("{KEY}", key), timeout=(15, 40))
    response.raise_for_status()
    data = json.loads(response.text)

    # 응답에서 row 목록 찾기: {서비스명: {list_total_count, RESULT, row: [...]}}
    rows = []
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("row"), list):
            rows = value["row"]
            break
    if not rows:
        result = data.get("RESULT") or next(
            (v.get("RESULT") for v in data.values() if isinstance(v, dict)), None
        )
        raise RuntimeError(f"API 응답에 row 없음: {result}")

    posts = []
    for row in rows:
        values = {k: str(v).strip() for k, v in row.items() if v is not None}
        title = next((values[k] for k in TITLE_KEYS if values.get(k)), "")
        if not title:  # 제목 칸을 못 찾으면 가장 긴 문자열을 제목으로
            texts = [v for v in values.values()
                     if v and not v.startswith("http") and not DATE_RE.fullmatch(v)]
            title = max(texts, key=len, default="")
        if len(title) < 3:
            continue

        if keywords and not any(k in title for k in keywords):
            continue
        if row_keywords:
            # 본문 필드는 제외하고 부서명 등 메타 필드에서만 찾는다 (본문 언급 오탐 방지)
            row_text = " ".join(
                v for k, v in values.items()
                if not any(x in k.upper() for x in ("CONTENT", "EXCERPT", "DESC"))
            )
            if not any(k in row_text for k in row_keywords):
                continue

        link = next((v for v in values.values() if v.startswith("http")), "")
        if not link and values.get("POST_ID"):
            # 서울시 보도자료(SeoulNewsList)는 링크 필드가 없어 직접 구성
            link = f"https://mediahub.seoul.go.kr/archives/{values['POST_ID']}"
        date_val = next((m.group() for v in values.values()
                         for m in [DATE_RE.search(v)] if m), "")
        posts.append({"title": title, "link": link, "date": date_val})

    logger.info("%s: API 행 %d개, 필터 통과 %d건", name or url, len(rows), len(posts))
    return posts


def scrape_open_portal(url, keywords, row_keywords=(), name=""):
    """정보공개포털의 공개 기관장 결재문서 AJAX 검색 결과를 읽는다.

    정적 목록에는 검색 행이 없지만, 공식 화면이 사용하는 JSON endpoint는
    GitHub Actions에서도 접근할 수 있다. 본문 검색으로 섞인 결과를 막기 위해
    제목과 서울시/감시 대상 자치구를 다시 엄격히 검사한다.
    """
    endpoint = "https://www.open.go.kr/othicInfo/infoList/mnstrSanDocList.ajax"
    today = date.today()
    start = today - timedelta(days=180)
    target_gu = tuple(k for k in row_keywords if k.endswith("구")) or tuple(
        gu for gu in SEOUL_GU_CODE.values()
        if gu in {
            "강남구", "강동구", "광진구", "동대문구", "동작구", "마포구",
            "서대문구", "서초구", "성동구", "송파구", "영등포구", "용산구",
            "종로구", "중구",
        }
    )
    search_terms = tuple(dict.fromkeys(keywords))
    if not search_terms:
        raise ValueError("정보공개포털 검색에는 제목 키워드가 필요합니다")

    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": url,
        "X-Requested-With": "XMLHttpRequest",
    }
    # 검색 화면을 먼저 열어 세션 쿠키를 받는다.
    page = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=(15, 40))
    page.raise_for_status()

    posts_by_id = {}
    searched_rows = 0
    diag_agencies = {}  # [진단] 제목 키워드 통과 행의 실제 기관명 형식 확인용
    for keyword in search_terms:
        payload = {
            "kwd": keyword,
            "preKwds": keyword,
            "reSrchFlag": "off",
            "othbcSeCd": "",
            "insttSeCd": "",
            "eduYn": "N",
            "startDate": start.strftime("%Y%m%d"),
            "endDate": today.strftime("%Y%m%d"),
            "insttCdNm": "",
            "insttCd": "",
            "searchInsttCdNmPop": "",
            "searchMainYn": "",
            "viewPage": "1",
            "rowPage": "100",
            "sort": "s",
        }
        response = session.post(
            endpoint, data=payload, headers=headers, timeout=(15, 50)
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("result") or data
        if str(result.get("code")) != "200":
            raise RuntimeError(
                f"정보공개포털 API 오류({keyword}): {result.get('code')} "
                f"{result.get('message') or result.get('rtnMsg') or ''}"
            )
        rows = result.get("rtnList") or []
        searched_rows += len(rows)
        for row in rows:
            title = str(row.get("INFO_SJ") or "").strip()
            # 검색 API는 첨부파일 본문도 검색하므로 제목을 반드시 재검사한다.
            if not title or keyword not in title:
                continue

            agency = str(row.get("PROC_INSTT_NM") or "").strip()
            department = str(row.get("NFLST_CHRG_DEPT_NM") or "").strip()
            # [진단] 서울 필터 통과가 0건이라, 실제 기관명/부서명 형식을 샘플로 남긴다.
            if "서울" in agency or "서울" in department:
                diag_agencies.setdefault(f"{agency} | {department}", 0)
                diag_agencies[f"{agency} | {department}"] += 1
            is_seoul = agency == "서울특별시" or any(
                agency == f"서울특별시 {gu}"
                or f"서울특별시 {gu}" in department
                for gu in target_gu
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
            detail = (
                "https://www.open.go.kr/othicInfo/infoList/infoListDetl3.do?"
                + query
            )
            date_value = ""
            if len(produced) >= 8 and produced[:8].isdigit():
                date_value = f"{produced[:4]}-{produced[4:6]}-{produced[6:8]}"
            display = f"[{agency or '서울특별시'}] {title}"
            posts_by_id[doc_id] = {
                "title": display,
                "link": detail,
                "date": date_value,
            }

    posts = sorted(
        posts_by_id.values(), key=lambda post: post["date"], reverse=True
    )
    logger.info(
        "%s: 정보공개포털 검색 행 %d개, 제목·서울기관 통과 %d건",
        name or url, searched_rows, len(posts),
    )
    if diag_agencies:
        # [진단] '서울' 포함 기관명/부서명 실제 형식 (통과 0건 원인 파악용)
        logger.info(
            "[진단] 정보공개포털 '서울' 포함 기관명 샘플: %s",
            "; ".join(list(diag_agencies)[:15]),
        )
    return posts


def scrape_urban(url, keywords, row_keywords=(), name=""):
    """서울도시공간포털(urban.seoul.go.kr)의 JSON 목록을 읽는다.

    주소의 쿼리스트링(searchGubun 등)은 POST 본문으로 변환되어 전송된다.
    """
    from urllib.parse import parse_qsl, urlparse

    parsed = urlparse(url)
    body = {"pageNo": 1, "pageSize": 15}
    for k, v in parse_qsl(parsed.query):
        body[k] = int(v) if v.isdigit() else v
    endpoint = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    response = requests.post(
        endpoint,
        json=body,
        headers={"User-Agent": USER_AGENT,
                 "Referer": "https://urban.seoul.go.kr/view/html/PMNU4010100001"},
        timeout=(15, 40),
    )
    response.raise_for_status()
    rows = response.json().get("content") or []

    posts = []
    for row in rows:
        values = {k: str(v).strip() for k, v in row.items()
                  if isinstance(v, (str, int, float)) and str(v).strip()}
        title = values.get("title") or values.get("subject") or ""
        if len(title) < 3:
            continue

        # 구 이름 추출
        # - 결정고시(ntfc): subject "노원구 | 2026-55" 또는 site "노원구청 도시관리과"
        # - 열람공고(wrtanc): readingArea/announceCode 앞 5자리(구 코드)로 판별
        gu = ""
        subj = values.get("subject", "")
        if "|" in subj:
            gu = subj.split("|", 1)[0].strip()
        if not gu.endswith("구"):
            for code_field in ("readingArea", "announceCode", "siteCode"):
                code = values.get(code_field, "")[:5]
                if code in SEOUL_GU_CODE:
                    gu = SEOUL_GU_CODE[code]
                    break
        if not gu:
            gu = values.get("site", "")

        if keywords and not any(k in title for k in keywords):
            continue
        # row_keywords: 구 이름 목록이면 구(gu)로, 그 외(부서명 등)는 메타 필드로 매칭
        if row_keywords:
            if all(k.endswith("구") for k in row_keywords):
                if not any(k in gu for k in row_keywords):
                    continue
            else:
                row_text = " ".join(
                    v for k, v in values.items()
                    if not any(x in k.upper() for x in ("CONTENT", "CONTTXT"))
                )
                if not any(k in row_text for k in row_keywords):
                    continue

        if values.get("announceCode"):  # 열람공고 상세
            link = ("https://urban.seoul.go.kr/view/html/PMNU4010200001"
                    f"?announceCode={values['announceCode']}")
        else:  # 결정고시 등은 목록 페이지로 안내
            link = "https://urban.seoul.go.kr/view/html/PMNU4030100001"

        date_val = ""
        for key in ("announceDate", "noticeDate", "createDatetime"):
            m = DATE_RE.search(values.get(key, ""))
            if m:
                date_val = m.group()
                break

        # 같은 제목이 여러 구에 있을 수 있어 구 이름을 앞에 붙여 구분/중복방지
        display = f"[{gu}] {title}" if gu and gu not in title else title
        posts.append({"title": display, "link": link, "date": date_val})

    logger.info("%s: urban 행 %d개, 필터 통과 %d건", name or url, len(rows), len(posts))
    return posts


def scrape_commission(url, keywords, row_keywords=(), name=""):
    """서울시 도시건축위원회(commission.eseoul.go.kr) 일정·결과 목록을 읽는다.

    각 회의는 <li>(a.CmitList) 안에 회차·위원회명(.col-left)과
    개최일시(.col-right dd)·장소(.place dd)가 담겨 있다.
    """
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT,
                 "Referer": "https://commission.eseoul.go.kr/mainInitPlatForm.do"},
        timeout=(15, 40),
    )
    response.encoding = "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.select("a.CmitList") or soup.select("ul.schdul-list li, .drop-box")
    posts = []
    for row in rows:
        left = row.select_one(".col-left")
        title = left.get_text(" ", strip=True) if left else ""
        title = re.sub(r"^\d+\s+", "", title).strip()  # 앞 번호 제거
        if len(title) < 5:
            continue

        date_val = ""
        right = row.select_one(".col-right")
        if right:
            dd = right.select_one("dd")
            if dd:
                m = DATE_RE.search(dd.get_text(strip=True))
                date_val = m.group() if m else dd.get_text(strip=True)
        if not date_val:
            m = DATE_RE.search(row.get_text(" ", strip=True))
            date_val = m.group() if m else ""

        place_el = row.select_one(".place dd")
        place = place_el.get_text(" ", strip=True) if place_el else ""

        if keywords and not any(k in title for k in keywords):
            continue

        display = f"{title} ({place})" if place else title
        posts.append({"title": display, "link": url, "date": date_val})

    logger.info("%s: 위원회 %d개, 통과 %d건", name or url, len(rows), len(posts))
    return posts


def scrape_board(url, keywords, row_keywords=(), name=""):
    if "open.go.kr/othicInfo/infoList/mnstrSanDocList" in url:
        return scrape_open_portal(url, keywords, row_keywords, name)
    if "openapi.seoul.go.kr" in url:
        return scrape_seoul_api(url, keywords, row_keywords, name)
    if "urban.seoul.go.kr" in url and ".json" in url:
        return scrape_urban(url, keywords, row_keywords, name)
    if "commission.eseoul.go.kr" in url:
        return scrape_commission(url, keywords, row_keywords, name)
    """게시판 목록에서 (제목, 링크, 날짜) 목록을 추출한다. jejeboard의 검증된 로직."""
    last_error = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Referer": url},
                timeout=(20, 40),
            )
            response.encoding = "utf-8"
            response.raise_for_status()
            break
        except Exception as e:
            last_error = e
            if attempt < FETCH_ATTEMPTS - 1:
                delay = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.info(
                    "retrying %s in %ss after error: %s", name or url, delay, e
                )
                time.sleep(delay)
    else:
        raise last_error
    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.select(
        "table tbody tr, .board-list tr, .bbs-list tr, .list_type li, "
        ".news-list li, .search-result-list li, .list-wrap li, "
        ".bdList > ul > li"
    )
    if not rows:
        rows = soup.select(".title, .subject, .txt_left, .tit")

    posts = []
    for row in rows:
        # 제목 전용 칸/클래스를 먼저 사용한다. 일부 고시공고 표의 첫 링크는
        # 제목이 아니라 고시 번호라 단순히 첫 <a>를 고르면 키워드를 놓친다.
        title_elem = row.select_one(".subject a, .tit a, .title a")
        if not title_elem:
            title_elem = row.select_one(".subject, .tit, .title, .s a, a")
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

        if not link or "javascript" in link:
            full_link = url  # 자바스크립트로만 열리는 글은 게시판 주소로 안내
        else:
            full_link = urljoin(url, link)

        # 행에서 날짜를 모두 모아 공고일을 고른다(게시기간 종료일 등 미래 날짜 배제).
        date_candidates = DATE_ALL_RE.findall(row.get_text(" ", strip=True))
        date_val = pick_posting_date(date_candidates)

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
