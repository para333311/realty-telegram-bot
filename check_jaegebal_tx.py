"""재개발닷컴(jaegebal.com) 구역별 실거래 알림 스크립트.

zones_jaegebal.txt 에 적힌 재개발 구역들의 상세 페이지를 읽어, 새로 올라온
실거래가 있으면 텔레그램으로 알린다. 구역 상세(/develops/{id})는 서버
렌더링이라 로그인 없이 최근 실거래 5건이 HTML 에 그대로 들어 있다
(tr.hover-item 행 — 2026-09-01 자양1동 799 로 실측 확인).

구역 매핑이 핵심이다: 국토부 원본 실거래에는 "어느 재개발 구역인지"가
없어서 주소만으로는 못 거른다. 재개발닷컴이 구역별로 묶어놓은 것을
그대로 쓴다.

알림 규칙:
- 구역 내 새 실거래는 전부 알린다.
- 5억 이하는 🔴 로 강조한다 (초기 재개발에서 실투자 가능 금액대).
- 첫 실행(새 구역 등록)은 알림 없이 기준선만 저장한다 — 다른 감시
  스크립트들과 같은 규칙.

필요한 환경변수: BOARD_BOT_TOKEN, TELEGRAM_CHAT_ID (게시판 알림과 공용)
확인한 거래는 seen_jaegebal_tx.json 에 저장한다.
"""

import html as html_mod
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

ZONES_FILE = "zones_jaegebal.txt"
SEEN_FILE = "seen_jaegebal_tx.json"
SEEN_KEEP = 100          # 구역별 보관할 거래 키 수 (페이지엔 5건뿐이라 넉넉)
HIGHLIGHT_MAX = 500_000_000   # 이 금액 이하는 🔴 강조

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DATE_RE = re.compile(r"^2\d\.[01]\d\.[0-3]\d$")


def load_zones():
    if not os.path.exists(ZONES_FILE):
        return []
    zones = []
    with open(ZONES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 2 or not parts[1].isdigit():
                logger.warning("zones_jaegebal.txt 형식 오류, 건너뜀: %s", line)
                continue
            zones.append({"name": parts[0], "id": parts[1]})
    return zones


def parse_price_eok(text):
    """'11.1 억' / '9 억' 같은 표기를 원 단위 정수로. 실패하면 None."""
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*억", text)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", "")) * 100_000_000)
    except ValueError:
        return None


def fetch_transactions(zone_id):
    """구역 상세 페이지의 실거래 행들을 파싱해 dict 목록으로 돌려준다.

    행 텍스트 실측 예 (자양1동 799):
      26.08.22 다세대 2017 년 자양동 611-1 예닮 2층 전용 15.35 평 11.1 억 공주가 4.71 억 1.1 억/평 9.95 평
    순서: 계약일 · 유형 · [건축년도] · 주소/건물/층 · 전용평 · 가격 · 공시가 · 평당가 · 대지지분
    """
    r = requests.get(
        f"https://jaegebal.com/develops/{zone_id}",
        headers={"User-Agent": USER_AGENT},
        timeout=(20, 40),
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    txs = []
    for tr in soup.select("tr.hover-item"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        text = " ".join(c for c in cells if c)
        first = cells[0] if cells else ""
        if not DATE_RE.match(first):
            continue
        date = first
        # 가격: '공주가'(공시가) 앞쪽의 첫 '억' 표기가 매매가
        main = text.split("공주가")[0]
        price = parse_price_eok(main)
        # 유형: 날짜 다음 셀. '다세대 2017 년'처럼 건축년도가 같은 셀에 붙어
        # 오므로 년도는 떼어낸다.
        kind = cells[1] if len(cells) > 1 else ""
        kind = re.sub(r"\s*\d{4}\s*년\s*", "", kind).strip()
        # 주소·건물·층: '년'(건축년도) 뒤 ~ '전용' 앞
        m = re.search(r"(?:\d{4}\s*년\s*)?(.+?)\s*전용", main)
        addr = m.group(1) if m else ""
        addr = re.sub(r"^.*?\d{4}\s*년\s*", "", addr).strip() or addr.strip()
        # 전용면적·대지지분
        m = re.search(r"전용\s*([\d.]+)\s*평", text)
        area = m.group(1) if m else ""
        # 대지지분: 행 마지막 '평' 값
        pyeongs = re.findall(r"([\d.]+)\s*평", text)
        land = pyeongs[-1] if len(pyeongs) >= 2 else ""
        txs.append({
            "date": date, "kind": kind, "addr": addr,
            "area": area, "land": land, "price": price, "raw": text,
        })
    return txs


def tx_key(tx):
    # 같은 날 같은 주소 같은 가격이면 같은 거래로 본다
    return f"{tx['date']}|{tx['addr']}|{tx['price']}"


def format_message(zone, tx):
    eok = f"{tx['price'] / 100_000_000:g}억" if tx["price"] else "가격미상"
    icon = "🔴" if tx["price"] and tx["price"] <= HIGHLIGHT_MAX else "🏠"
    name = html_mod.escape(zone["name"])
    line2 = f"{html_mod.escape(tx['kind'])} {eok}"
    if tx["land"]:
        line2 += f" 대지 {tx['land']}평"
    if tx["area"]:
        line2 += f" 전용 {tx['area']}평"
    line2 += f" {tx['date']}"
    lines = [f"{icon} [{name}] 새 실거래", line2]
    if tx["addr"]:
        lines.append(html_mod.escape(tx["addr"]))
    lines.append(f"https://jaegebal.com/develops/{zone['id']}")
    return "\n".join(lines)


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
    zones = load_zones()
    if not zones:
        logger.info("zones_jaegebal.txt 에 등록된 구역이 없습니다.")
        return

    token = os.environ["BOARD_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    seen = load_seen()
    try:
        for zone in zones:
            try:
                txs = fetch_transactions(zone["id"])
            except Exception as e:
                logger.warning("[%s] 실거래 조회 실패: %s", zone["name"], e)
                continue

            entry = seen.get(zone["id"])
            keys = [tx_key(t) for t in txs]

            if entry is None:
                # 새로 등록된 구역: 기존 거래는 알림 없이 기준선으로 저장
                seen[zone["id"]] = {"name": zone["name"], "keys": keys[:SEEN_KEEP]}
                logger.info("[%s] 감시 시작 (기존 실거래 %d건 기준선)", zone["name"], len(txs))
                continue

            known = set(entry["keys"])
            new_txs = [t for t in txs if tx_key(t) not in known]
            for tx in reversed(new_txs):  # 오래된 거래부터 순서대로 발송
                send_message(token, chat_id, format_message(zone, tx),
                             disable_preview=True)
                entry["keys"].insert(0, tx_key(tx))
                logger.info("알림: [%s] %s", zone["name"], tx["raw"][:80])

            entry["name"] = zone["name"]
            entry["keys"] = entry["keys"][:SEEN_KEEP]
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
