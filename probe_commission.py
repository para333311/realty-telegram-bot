"""(임시) commission.eseoul.go.kr 도시건축위원회 일정/결과 구조 조사. 조사 후 삭제."""

import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://commission.eseoul.go.kr"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def get(url, **kw):
    try:
        r = S.get(url, timeout=30, verify=False, **kw)
        r.encoding = "utf-8"
        print(f"### GET {url[:95]} -> {r.status_code}, {len(r.text)}b, 최종={r.url[:80]}")
        return r
    except Exception as e:
        print(f"### GET {url[:95]} -> ERROR {e}")
        return None


print("===== 1) 메인 접근성 + 위원회/메뉴 링크 =====")
r = get(BASE + "/mainInitPlatForm.do")
if not r or r.status_code != 200:
    r = get(BASE + "/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    print("  title:", (soup.title.string if soup.title else "")[:60])
    # 위원회/일정/결과 관련 링크
    links = []
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        href = a["href"]
        if any(k in txt for k in ("일정", "결과", "위원회", "심의", "자문")) or \
           any(k in href for k in ("schedule", "result", "list", "cmit", "commit", "meeting")):
            links.append((txt[:20], href[:80]))
    for t, h in links[:40]:
        print(f"    '{t}' -> {h}")
    # onclick / js 함수로 이동하는 경우
    for m in re.findall(r"(fn\w*(?:List|Move|Go|Schedule|Result)\w*)\s*\(", r.text)[:15]:
        print("    js함수:", m)
    # .do 엔드포인트
    dos = sorted(set(re.findall(r'["\'](/[A-Za-z0-9_/]+\.do)["\']', r.text)))
    print("  .do 엔드포인트:", dos[:30])

print("\n===== 2) 흔한 일정/결과 목록 경로 시도 =====")
for path in ("/schedule/list.do", "/result/list.do", "/cmitList.do", "/meeting/list.do",
             "/front/schedule/scheduleList.do", "/committee/scheduleList.do",
             "/selectScheduleList.do", "/selectResultList.do"):
    get(BASE + path)

print("\n끝")
