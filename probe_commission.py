"""(임시) commission cmitSchdulList.do 파라미터/위원회코드 조사. 조사 후 삭제."""

import json
import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://commission.eseoul.go.kr"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
                  "Referer": BASE + "/mainInitPlatForm.do"})


def show(label, r):
    ct = r.headers.get("content-type", "")
    final = r.url.split("/")[-1]
    print(f"### {label} -> {r.status_code}, {len(r.text)}b, ct={ct[:30]}, 최종={final}")
    return r


print("===== 1) 메인 페이지에서 위원회 코드(fnMenualMove/fnMoveMainTab 인자) =====")
home = S.get(BASE + "/mainInitPlatForm.do", timeout=30, verify=False)
home.encoding = "utf-8"
for fn in ("fnMenualMove", "fnMoveMainTab", "fnCmitSchdul", "fnSchedule"):
    for m in re.findall(fn + r"\(([^)]*)\)", home.text)[:12]:
        print(f"  {fn}({m})")
# cmitId / cmit코드 패턴
codes = set(re.findall(r"['\"]([A-Z]{2,}-?\d{2,}|CMIT\w*|\d{6,})['\"]", home.text))
print("  코드 후보:", sorted(codes)[:30])
# 위원회 이름과 코드가 함께 있는 구조
soup = BeautifulSoup(home.text, "html.parser")
for a in soup.find_all(["a", "button"]):
    oc = a.get("onclick", "") or a.get("href", "")
    txt = a.get_text(strip=True)
    if "일정" in txt and oc:
        print(f"  '일정 및 결과' onclick: {oc[:100]}")

print("\n===== 2) cmitSchdulList.do 호출 (로그인 필요?/파라미터) =====")
for params in ({}, {"cmitSeCode": "01"}, {"cmitId": "01"}, {"pageIndex": "1"}):
    for method in ("GET", "POST"):
        try:
            if method == "GET":
                r = S.get(BASE + "/cmitInfo/cmitSchdulList.do", params=params, timeout=20, verify=False)
            else:
                r = S.post(BASE + "/cmitInfo/cmitSchdulList.do", data=params, timeout=20, verify=False)
            r.encoding = "utf-8"
            login = "loginForm" in r.url
            print(f"  {method} {params} -> {r.status_code}, {len(r.text)}b, 로그인이동={login}")
            if not login and r.status_code == 200 and len(r.text) > 500:
                # 표/행 개수
                s = BeautifulSoup(r.text, "html.parser")
                rows = s.select("table tbody tr, .list tr, li")
                print(f"    -> 행 {len(rows)}개, 앞부분: {r.text[:200].strip()[:150]!r}")
            break
        except Exception as e:
            print(f"  {method} {params} -> ERR {e}")

print("\n===== 3) 위원회 소개 상세 (코드 확인용) =====")
r = S.get(BASE + "/cmitInfo/cmitIntrcnDetail.do", timeout=20, verify=False)
print("  cmitIntrcnDetail.do ->", r.status_code, "로그인이동=", "loginForm" in r.url)

print("\n끝")
