"""(임시) 서울시보 목록 페이지의 행(호수)별 PDF 파일명 매칭 구조 확인. 조사 후 삭제."""

import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})

LIST_URL = "https://www.seoul.go.kr/func/seoulsibo/list.do"

r = S.get(LIST_URL, timeout=25, verify=False)
soup = BeautifulSoup(r.text, "html.parser")

print("===== 목록 테이블 tr 구조 확인 (상위 3개 행) =====")
rows = soup.select("table tbody tr")
print(f"tr 개수: {len(rows)}")
for row in rows[:3]:
    print("\n--- ROW HTML ---")
    print(re.sub(r"\s+", " ", str(row))[:1000])

print("\n===== 다른 셀렉터 후보(테이블이 없을 경우) =====")
for sel in ("ul li", ".board-list li", ".list li"):
    items = soup.select(sel)
    if items:
        print(f"[{sel}] {len(items)}개, 첫 항목:")
        print(re.sub(r"\s+", " ", str(items[0]))[:800])

print("\n끝")
