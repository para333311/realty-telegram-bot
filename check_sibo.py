"""GitHub Actions 등에서 주기적으로 1회 실행되는 서울시보 재개발 관련 목차 알림 스크립트.

서울시보(seoul.go.kr) 새 호수가 발행되면 그 PDF의 목차(앞부분 페이지)에서
재개발 관련 키워드가 든 항목만 뽑아 텔레그램으로 알린다.
확인한 호수는 seen_sibo.json에 저장한다.

키워드: 재개발·재건축·정비사업·정비구역·정비계획·지구단위계획·도시관리계획·
        모아타운·신속통합·재정비촉진·후보지

필요한 환경변수:
- BOARD_BOT_TOKEN : 알림용 텔레그램 봇 토큰(재재보드봇, 게시판 알림과 공용)
- TELEGRAM_CHAT_ID : 알림을 받을 채팅 ID (다른 봇과 공용)

한계(확인됨):
- PDF 다운로드 응답이 강제다운로드 Content-Type(application/x-msdownload)로 와서
  "눌렀을 때 해당 페이지로 바로 이동"은 신뢰할 수 없다(다운로드된 파일을 별도 뷰어로
  열면 페이지 정보가 보통 사라짐). 그래서 페이지 이동은 시도하지 않고, 알림에는
  목차 제목만 담고 링크는 서울시보 목록 페이지로 안내한다.
- 같은 다운로드 엔드포인트에 짧은 시간 안에 여러 번 요청하면 이후 요청이 전부
  차단(503)되는 것을 확인했다. 그래서 "새 호수가 있을 때만, 1회만" 다운로드를
  시도하며, 실패하면 다음 실행에서 재시도하되 MAX_ATTEMPTS 이상 실패하면 포기한다.
"""

import io
import json
import logging
import os
import re

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

LIST_URL = "https://www.seoul.go.kr/func/seoulsibo/list.do"
PDF_BASE = "https://www.seoul.go.kr/func/seoulsibo/fileDownload.do?fileName="
SEEN_FILE = "seen_sibo.json"
MAX_ATTEMPTS = 3   # 다운로드 실패 시 재시도 상한(그 이상이면 포기)

KEYWORDS = [
    "재개발", "재건축", "정비사업", "정비구역", "정비계획", "지구단위계획",
    "도시관리계획", "모아타운", "신속통합", "재정비촉진", "후보지",
]

# "제2026-402호  <제목>· · · ... <페이지>" 형태의 목차 항목 파싱
ENTRY_RE = re.compile(r"제(\d{4}-\d+)호\s*(.+?)(?:·\s*){3,}(\d+)(?=제\d{4}-\d+호|◈|$)", re.S)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def fetch_issue_list(session):
    """목록 페이지에서 (호수, 발행일, PDF파일명) 목록을 추출한다."""
    r = session.get(LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=(15, 30), verify=False)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    issues = []
    for row in soup.select("table tbody tr"):
        text = row.get_text(" ", strip=True)
        m = re.search(r"제(\d+)호", text)
        if not m:
            continue
        no = m.group(1)
        date_m = re.search(r"\d{4}\.\d{2}\.\d{2}", text)
        date = date_m.group(0) if date_m else ""

        filename = None
        for tag in row.find_all(attrs={"onclick": True}):
            fm = re.search(r"fileName=([\w\-.]+?\.pdf)", tag["onclick"])
            if fm:
                filename = fm.group(1)
                break
        if filename:
            issues.append({"no": no, "date": date, "filename": filename})
    return issues


def extract_matches(session, filename):
    """PDF 목차에서 재개발 키워드가 든 항목만 뽑는다. 다운로드 실패시 None."""
    url = PDF_BASE + filename
    r = session.get(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": LIST_URL},
        timeout=(15, 60), verify=False,
    )
    if r.content[:4] != b"%PDF":
        return None

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(r.content))

    entries = []
    for idx in range(1, min(10, len(reader.pages))):
        text = reader.pages[idx].extract_text() or ""
        found = ENTRY_RE.findall(text)
        if not found and entries:
            break
        for _, title, _ in found:
            entries.append(title.strip())

    return [t for t in entries if any(k in t for k in KEYWORDS)]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {"done": [], "pending": {}}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    # 완료 순서를 유지해야 실제로 오래된 호수부터 안전하게 정리할 수 있다.
    seen["done"] = list(dict.fromkeys(seen["done"]))[-500:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)
        f.write("\n")


def main():
    missing = [k for k in ("BOARD_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(k)]
    if missing:
        logger.info("서울시보 감시 시크릿 미설정으로 건너뜀: %s", ", ".join(missing))
        return

    token = os.environ["BOARD_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    session = requests.Session()
    try:
        issues = fetch_issue_list(session)
    except requests.RequestException as e:
        # 서울시 서버가 해외 IP 접속을 간헐적으로 막아 타임아웃이 난다.
        # 이번 회차만 건너뛰면 다음 회차에 자연히 따라잡으므로 실패로 처리하지 않는다.
        logger.warning("서울시보 목록 조회 실패(이번 회차 건너뜀): %s", e)
        return
    logger.info("목록에서 호수 %d건 확인", len(issues))

    seen = load_seen()
    done = list(dict.fromkeys(seen["done"]))
    done_set = set(done)
    pending = seen["pending"]

    first_run = not done_set and not pending

    for x in issues:
        if x["no"] not in done_set and x["no"] not in pending:
            pending[x["no"]] = {"attempts": 0, "date": x["date"], "filename": x["filename"]}

    if first_run:
        # 첫 실행: 기존 호수는 다운로드 시도 없이 기준선으로 저장
        for no in pending:
            if no not in done_set:
                done.append(no)
                done_set.add(no)
        pending.clear()
        save_seen({"done": done, "pending": pending})
        send_message(
            token, chat_id,
            "📰 서울시보 재개발 관련 목차 감시를 시작했습니다. "
            "새 호수가 발행되면 목차에서 재개발·재건축·정비사업 등 관련 항목만 알려드릴게요.",
        )
        logger.info("첫 실행: 호수 %d건 기준선 저장", len(done_set))
        return

    for no in list(pending.keys()):
        info = pending[no]
        try:
            matches = extract_matches(session, info["filename"])
        except Exception as e:
            logger.warning("제%s호 PDF 처리 중 오류: %s", no, e)
            matches = None

        if matches is None:
            info["attempts"] += 1
            logger.info("제%s호: PDF 다운로드 실패(시도 %d/%d)", no, info["attempts"], MAX_ATTEMPTS)
            if info["attempts"] >= MAX_ATTEMPTS:
                logger.warning("제%s호: %d회 실패로 포기", no, MAX_ATTEMPTS)
                done.append(no)
                done_set.add(no)
                del pending[no]
            continue

        if matches:
            # 항목마다 번호를 붙이고 빈 줄로 띄워서 읽기 편하게 한다
            # (붙어 있으면 어디서 항목이 끝나고 시작하는지 구분이 안 돼 가독성이 떨어짐).
            titles = "\n\n".join(f"{i}. {t}" for i, t in enumerate(matches, 1))
            send_message(
                token, chat_id,
                f"📰 [서울시보 제{no}호, {info['date']}]\n재개발 관련 목차\n\n{titles}\n\n{LIST_URL}",
            )
            logger.info("제%s호: 재개발 관련 %d건 알림", no, len(matches))
        else:
            logger.info("제%s호: 재개발 관련 항목 없음", no)

        done.append(no)
        done_set.add(no)
        del pending[no]

    save_seen({"done": done, "pending": pending})


if __name__ == "__main__":
    main()
