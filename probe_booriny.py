"""(임시) booriny 매물 상세/단계 필드 확인. 조사 후 삭제."""

import json
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

r = S.get(BASE + "/api/listings", params={"limit": 3}, timeout=30, verify=False)
listings = r.json().get("data", {}).get("listings", [])
lid = listings[0]["id"] if listings else None
atcl = listings[0].get("atcl_no") if listings else None
print("샘플 id:", lid, "atcl_no:", atcl)

print("\n===== 1) 매물 상세 엔드포인트 (단계 필드 있나?) =====")
for ep in (f"/api/listings/{lid}", f"/api/listing/{lid}", f"/api/maemul/{lid}",
           f"/api/listings/{atcl}"):
    try:
        rr = S.get(BASE + ep, timeout=15, verify=False)
        if rr.status_code == 200:
            d = rr.json()
            print(f"  {ep} -> 200, 키: {sorted(d.get('data', d).keys())[:40] if isinstance(d.get('data', d), dict) else type(d)}")
            s = json.dumps(d, ensure_ascii=False)
            for kw in ("stage", "단계", "초기", "중기", "후기", "step", "phase", "progress"):
                if kw in s:
                    i = s.find(kw)
                    print(f"    '{kw}' 발견: ...{s[max(0,i-50):i+50]}...")
        else:
            print(f"  {ep} -> {rr.status_code}")
    except Exception as e:
        print(f"  {ep} -> ERR {e}")

print("\n===== 2) division 파라미터가 서버 필터인지 (limit=100 분포) =====")
from collections import Counter
r2 = S.get(BASE + "/api/listings", params={"limit": 100, "division": "마포구"}, timeout=30, verify=False)
ls2 = r2.json().get("data", {}).get("listings", [])
print("  division=마포구 요청 시 실제 구 분포:", Counter(x.get("division") for x in ls2).most_common(5))

print("\n===== 3) 페이지네이션 파라미터 =====")
for p in ({"limit": 5, "offset": 100}, {"limit": 5, "page": 2}, {"limit": 5, "cursor": "1"}):
    rr = S.get(BASE + "/api/listings", params=p, timeout=20, verify=False)
    ls = rr.json().get("data", {}).get("listings", [])
    print(f"  {p} -> {len(ls)}건, 첫 id={ls[0]['id'] if ls else None}")

print("\n===== 4) 재개발 구역/단계 데이터 (지도용) =====")
r = S.get(BASE + "/", timeout=20, verify=False).text
apis = set(re.findall(r"/api/[A-Za-z0-9_/\-]{3,45}", r))
print("  홈 참조 API 전체:", sorted(apis))

print("\n===== 끝 =====")
