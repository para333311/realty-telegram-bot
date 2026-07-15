"""(임시) booriny 매물 API 필터 파라미터 최종 확인. 비밀번호 미출력. 조사 후 삭제."""

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

print("===== 1) 매물 1건 전체 필드 =====")
r = S.get(BASE + "/api/listings", params={"limit": 5}, timeout=30, verify=False)
data = r.json().get("data", {})
listings = data.get("listings", [])
print("  총 count:", data.get("count"), "| 응답 filters 키:", list(data.get("filters", {}).keys()))
if listings:
    item = listings[0]
    print("  전체 필드명:", sorted(item.keys()))
    # 단계/구역/유형 관련 필드만 값과 함께
    for k in sorted(item):
        low = k.lower()
        if any(x in low for x in ("tp", "type", "stage", "step", "phase", "cortar", "division",
                                  "sector", "redevelop", "zone", "area", "gu", "prc", "nm", "atcl")):
            print(f"    {k} = {item[k]!r}")

print("\n===== 2) 유형(rlet_tp_cd/atcl_nm) 분포 — 다세대 코드 파악 =====")
r = S.get(BASE + "/api/listings", params={"limit": 100}, timeout=30, verify=False)
ls = r.json().get("data", {}).get("listings", [])
from collections import Counter
print("  atcl_nm 분포:", Counter(x.get("atcl_nm") for x in ls).most_common())
print("  rlet_tp_cd/nm 분포:", Counter((x.get("rlet_tp_cd"), x.get("rlet_tp_nm")) for x in ls).most_common())
print("  division(구) 분포:", Counter(x.get("division") for x in ls).most_common(10))

print("\n===== 3) 프런트엔드 JS에서 /api/listings 호출 파라미터 =====")
home = S.get(BASE + "/", timeout=20, verify=False).text
scripts = [s if s.startswith("http") else BASE + s
           for s in re.findall(r'<script[^>]+src="([^"]+)"', home)]
for js in scripts:
    t = S.get(js, timeout=20, verify=False).text
    if "api/listings" not in t:
        continue
    for m in re.finditer(r"api/listings", t):
        seg = t[m.start()-40:m.end()+400]
        # 파라미터 키로 보이는 것들
        params = set(re.findall(r'["\']([a-z_]{3,25})["\']\s*:', seg))
        params |= set(re.findall(r'(?:searchParams\.set|append)\(["\']([a-z_]{3,25})["\']', seg))
        if params:
            print(f"  [{js.rsplit('/',1)[1]}] 후보 파라미터: {sorted(params)[:25]}")
    # 단계/유형 한글 라벨 매핑
    for label in ("다세대", "초기", "중기", "후기", "재개발", "빌라", "연립"):
        for mm in re.finditer(label, t):
            seg = t[mm.start()-60:mm.end()+40]
            code = re.findall(r'["\']([A-Za-z0-9_]{1,10})["\']', seg)
            print(f"  '{label}' 근처 코드: {code[:6]}")
            break

print("\n===== 4) is_redevelopment / days 파라미터 효과 =====")
for params in ({"limit": 1}, {"limit": 1, "is_redevelopment": "true"}, {"limit": 1, "days": 1}):
    rr = S.get(BASE + "/api/listings", params=params, timeout=20, verify=False)
    print(f"  {params} -> count={rr.json().get('data',{}).get('count')}")

print("\n===== 끝 =====")
