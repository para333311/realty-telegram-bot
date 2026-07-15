"""(임시) 도시공간포털 결정고시(ntfc) 유형/구 필터 파라미터 조사. 조사 후 삭제."""

import json
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://urban.seoul.go.kr"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
    "Content-Type": "application/json",
    "Referer": BASE + "/view/html/PMNU4030100001",
})


def post(ep, body):
    r = S.post(BASE + ep, data=json.dumps(body), timeout=30, verify=False)
    r.encoding = "utf-8"
    return r


print("===== 1) 결정고시 기본 응답 구조 + 유형/구 필드 =====")
r = post("/ntfc/getNtfcList.json", {"pageNo": 1, "pageSize": 5})
data = r.json()
content = data.get("content") or []
print("  총 건수 totalElements:", data.get("totalElements"), "| 반환:", len(content))
if content:
    item = content[0]
    nn = {k: v for k, v in item.items() if v not in (None, "", [], {}) and not isinstance(v, (dict, list))}
    print("  첫 항목 필드:", json.dumps(nn, ensure_ascii=False)[:1500])
    # 유형/구 관련 필드 값
    for x in content:
        for k in x:
            kl = k.lower()
            if any(t in kl for t in ("classif", "gubun", "type", "site", "area", "gu", "sgg", "region", "sido")):
                v = x.get(k)
                if v not in (None, ""):
                    print(f"    {k} = {v!r}")
        break

print("\n===== 2) 결정고시 페이지 JS에서 classifyM/구 옵션 코드 =====")
home = S.get(BASE + "/view/html/PMNU4030100001", timeout=20, verify=False).text
scripts = [s if s.startswith("http") else BASE + s
           for s in re.findall(r'<script[^>]+src="([^"]+)"', home)]
for js in scripts:
    if "PMNU4030100001" not in js:
        continue
    t = S.get(js, timeout=20, verify=False).text
    for label in ("결정고시", "지구단위계획", "정비사업구역계", "도시개발사업",
                  "도시계획시설", "용도지구", "용도구역"):
        i = t.find(label)
        if i >= 0:
            print(f"  '{label}' 근처: ...{t[max(0,i-70):i+30]!r}...")

print("\n===== 3) classifyM/siteCode 파라미터로 필터 시도 =====")
base_total = post("/ntfc/getNtfcList.json", {"pageNo": 1, "pageSize": 1}).json().get("totalElements")
print("  전체:", base_total)
for body in (
    {"pageNo": 1, "pageSize": 1, "classifyM": "정비사업구역계"},
    {"pageNo": 1, "pageSize": 1, "classifyG": "정비사업구역계"},
    {"pageNo": 1, "pageSize": 1, "siteCode": "11440"},   # 마포구 법정동코드 앞자리?
    {"pageNo": 1, "pageSize": 1, "readingArea": "11440"},
    {"pageNo": 1, "pageSize": 1, "sggNm": "마포구"},
):
    try:
        te = post("/ntfc/getNtfcList.json", body).json().get("totalElements")
        print(f"  {body} -> totalElements={te}")
    except Exception as e:
        print(f"  {body} -> ERR {e}")

print("\n===== 4) 전체 200건에서 유형(classify)·구 값 분포 =====")
from collections import Counter
r = post("/ntfc/getNtfcList.json", {"pageNo": 1, "pageSize": 200})
cont = r.json().get("content") or []
print("  반환:", len(cont))
# 모든 문자열 필드 중 유형/구로 보이는 값 후보
if cont:
    keys = [k for k in cont[0] if isinstance(cont[0].get(k), str)]
    for k in keys:
        vals = Counter(str(x.get(k)) for x in cont if x.get(k))
        common = vals.most_common(6)
        # 유형/구처럼 값 종류가 적당한 것만
        if 2 <= len(vals) <= 40 and any("구" in str(v) or "계획" in str(v) or "고시" in str(v) or "사업" in str(v) for v, _ in common):
            print(f"    [{k}] {common}")

print("\n끝")
