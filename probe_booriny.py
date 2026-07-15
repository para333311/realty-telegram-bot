"""(임시) booriny 재개발 필드 값/서버필터 확인. 조사 후 삭제."""

import json
import os

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
       json={"email": os.environ["BOORINY_ID"], "password": os.environ["BOORINY_PW"]},
       timeout=(15, 30), verify=False)


def fetch(label, **params):
    r = S.get(BASE + "/api/listings", params=params, timeout=(15, 40), verify=False)
    try:
        js = r.json()
    except Exception:
        print(f"[{label}] {params} -> {r.status_code} 비JSON")
        return []
    lst = js.get("data", {}).get("listings") or js.get("listings") or []
    print(f"[{label}] {params} -> {r.status_code}, listings {len(lst)}건")
    return lst


# 1) 넉넉히 받아서 재개발 비율 확인 (limit 상한 테스트)
for lim in (100, 500, 1000, 2000):
    lst = fetch(f"limit={lim}", limit=lim)
    redev = [x for x in lst if x.get("is_redevelopment")]
    print(f"    → is_redevelopment=True {len(redev)}건")

# 2) 서버측 재개발 필터 파라미터가 먹는지
for p in ({"is_redevelopment": "true"}, {"redevelopment": "true"},
          {"only_redevelopment": "true"}, {"is_redevelopment": 1}):
    lst = fetch("param", limit=1000, **p)
    redev = [x for x in lst if x.get("is_redevelopment")]
    print(f"    → 그중 is_redevelopment=True {len(redev)}건")

# 3) 재개발 매물 실제 값 덤프 (구역/단계/유형/건물유형)
lst = fetch("dump", limit=2000)
redev = [x for x in lst if x.get("is_redevelopment")]
print(f"\n=== 재개발 매물 {len(redev)}건 중 상위 12건 값 ===")
for x in redev[:12]:
    print("  ", json.dumps({
        "division": x.get("division"), "sector": x.get("sector"),
        "area": x.get("redevelopment_area"), "stage": x.get("redevelopment_stage"),
        "rtype": x.get("redevelopment_type"), "district": x.get("district_name"),
        "bld": x.get("rlet_tp_cd"), "nm": x.get("atcl_nm"),
        "prc": x.get("prc"), "trad": x.get("trad_tp_cd"),
    }, ensure_ascii=False))

# 4) stage/type/건물유형 분포
from collections import Counter
print("\nstage 분포:", Counter(str(x.get("redevelopment_stage")) for x in redev))
print("type  분포:", Counter(str(x.get("redevelopment_type")) for x in redev))
print("bld   분포:", Counter(str(x.get("rlet_tp_cd")) for x in redev))
print("division 분포:", Counter(str(x.get("division")) for x in redev))

print("\n끝")
