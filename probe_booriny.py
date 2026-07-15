"""(임시) booriny 재개발구역 매물 엔드포인트/필드 조사. 조사 후 삭제. (자격증명 출력 안 함)"""

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


def login():
    r = S.post(BASE + "/api/auth/v2/login",
               json={"email": os.environ["BOORINY_ID"], "password": os.environ["BOORINY_PW"]},
               timeout=(15, 30), verify=False)
    print("login:", r.status_code, "success=", r.json().get("success"))


def get(path, label, **params):
    try:
        r = S.get(BASE + path, params=params, timeout=(15, 30), verify=False)
        ct = r.headers.get("content-type", "")
        print(f"\n### [{label}] {path} {params} -> {r.status_code}, {len(r.text)}b, {ct[:30]}")
        if "json" in ct and r.status_code == 200:
            return r.json()
        else:
            print("   (비JSON/실패) 앞부분:", r.text[:150].replace("\n", " "))
    except Exception as e:
        print(f"\n### [{label}] {path} -> ERROR {str(e)[:100]}")
    return None


login()

# 1) 현재 쓰는 엔드포인트 — 첫 항목의 '모든' 필드를 본다 (구역/재개발 관련 필드 존재?)
data = get("/api/listings", "listings", limit=5)
if data:
    listings = data.get("data", {}).get("listings") or data.get("listings") or []
    print("   listings 개수:", len(listings))
    if listings:
        print("   [첫 항목 전체 필드]:")
        print("   ", json.dumps(listings[0], ensure_ascii=False)[:1200])
        print("   [키 목록]:", list(listings[0].keys()))

# 2) 재개발구역 매물일 법한 다른 후보 엔드포인트 탐색
for path, label in [
    ("/api/listings/redevelopment", "listings-redev"),
    ("/api/redevelopment/listings", "redev-listings"),
    ("/api/v2/listings", "v2-listings"),
    ("/api/articles", "articles"),
    ("/api/zones", "zones"),
    ("/api/regions", "regions"),
    ("/api/districts", "districts"),
    ("/api/estate/listings", "estate-listings"),
    ("/api/map/listings", "map-listings"),
]:
    get(path, label, limit=5)

# 3) listings에 구역/유형 필터 파라미터가 먹는지 테스트
get("/api/listings", "listings-filtered", limit=5, gu="서초구", type="재개발", division="서초구")

print("\n끝")
