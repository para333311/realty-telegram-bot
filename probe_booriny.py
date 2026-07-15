"""(임시) booriny 필터 설정(다세대/초기 코드) + 매물 API 파라미터 최종. 조사 후 삭제."""

import os
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://booriny.com"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
    "Content-Type": "application/json", "Origin": BASE, "Referer": BASE + "/",
})
S.post(BASE + "/api/auth/v2/login",
       json={"email": os.environ.get("BOORINY_ID", ""), "password": os.environ.get("BOORINY_PW", "")},
       timeout=30, verify=False)

home = S.get(BASE + "/", timeout=20, verify=False).text
scripts = [s if s.startswith("http") else BASE + s
           for s in re.findall(r'<script[^>]+src="([^"]+)"', home)]

print("===== 1) 전체 JS에서 필터 라벨↔값 매핑 =====")
for js in scripts:
    try:
        t = S.get(js, timeout=20, verify=False).text
    except Exception:
        continue
    for label in ("다세대", "초기", "중기", "후기", "단독/다가구", "5억", "최저가"):
        idx = 0
        while True:
            i = t.find(label, idx)
            if i < 0:
                break
            seg = t[max(0, i-90):i+50]
            print(f"  [{js.rsplit('/',1)[1][:18]}] '{label}': ...{seg!r}...")
            idx = i + 1
            break  # 파일당 라벨 첫 매치만

print("\n===== 2) /api/listings 호출부 + URLSearchParams 키 =====")
for js in scripts:
    try:
        t = S.get(js, timeout=20, verify=False).text
    except Exception:
        continue
    if "listings" not in t:
        continue
    for m in re.finditer(r"api/listings", t):
        seg = t[m.start()-20:m.end()+600]
        keys = set(re.findall(r'(?:set|append|get)\(["\']([a-zA-Z_][a-zA-Z0-9_]{1,25})["\']', seg))
        keys |= set(re.findall(r'([a-z_]{3,25})=\$?\{?', seg))
        print(f"  [{js.rsplit('/',1)[1][:18]}] listings 근처 키: {sorted(k for k in keys if len(k)<26)[:30]}")

print("\n===== 3) 후보 파라미터 실제 효과 테스트 =====")
def count(params):
    try:
        return S.get(BASE + "/api/listings", params={**params, "limit": 1},
                     timeout=20, verify=False).json().get("data", {}).get("count")
    except Exception as e:
        return f"ERR {e}"

print("  기준 (limit=1):", count({}))
for p in ({"rlet_tp_cd": "C02"}, {"realEstateType": "다세대"}, {"type": "다세대"},
          {"stage": "초기"}, {"step": "1"}, {"phase": "early"}, {"redevelopment_stage": "초기"},
          {"division": "마포구"}, {"gu": "마포구"}, {"sido": "서울시", "gugun": "마포구"},
          {"max_price": 500000000}, {"maxPrice": 500000000}, {"price_max": 500000000}):
    print(f"  {p} -> count={count(p)}")

print("\n===== 4) 구역-단계 매핑용 별도 엔드포인트 탐색 =====")
for ep in ("/api/redevelopment-zones", "/api/zones", "/api/cortars", "/api/regions",
           "/api/redevelopment/stages", "/api/areas", "/api/districts"):
    try:
        rr = S.get(BASE + ep, timeout=15, verify=False)
        if rr.status_code != 404:
            print(f"  {ep} -> {rr.status_code}: {rr.text[:200]!r}")
    except Exception as e:
        print(f"  {ep} -> ERR {e}")

print("\n===== 끝 =====")
