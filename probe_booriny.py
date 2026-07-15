"""(임시) booriny 로그인 후 매물 API 구조 조사. 비밀번호는 로그에 출력하지 않는다. 조사 후 삭제."""

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
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": BASE + "/",
})

EMAIL = os.environ.get("BOORINY_ID", "")
PW = os.environ.get("BOORINY_PW", "")
print("자격증명 존재:", bool(EMAIL), bool(PW))


def show(label, r):
    print(f"### {label} -> {r.status_code}, {len(r.text)}b")
    ct = r.headers.get("content-type", "")
    if "json" in ct:
        try:
            data = r.json()
            # 토큰류는 가리고 구조만
            s = json.dumps(data, ensure_ascii=False)
            s = re.sub(r'("(?:token|accessToken|refreshToken)":")[^"]+', r"\1***", s)
            print("  ", s[:1200])
            return data
        except Exception:
            pass
    print("  ", r.text[:400].replace("\n", " "))
    return None


print("\n===== 1) 로그인 =====")
r = S.post(BASE + "/api/auth/v2/login", json={"email": EMAIL, "password": PW}, timeout=30, verify=False)
login_data = show("POST /api/auth/v2/login", r)
# 토큰이 헤더/본문 어디서 오는지
print("  Set-Cookie 있음:", "set-cookie" in {k.lower() for k in r.headers})
token = None
if login_data:
    for k in ("token", "accessToken", "access_token"):
        token = login_data.get(k) or (login_data.get("data") or {}).get(k)
        if token:
            print(f"  토큰 위치: {k} (본문)")
            break
if token:
    S.headers["Authorization"] = f"Bearer {token}"

print("\n===== 2) 내 정보 / 관심지역 =====")
show("GET /api/user/me", S.get(BASE + "/api/user/me", timeout=20, verify=False))
show("GET /api/user/favorite-areas", S.get(BASE + "/api/user/favorite-areas", timeout=20, verify=False))

print("\n===== 3) 매물 목록 엔드포인트 탐색 =====")
candidates = [
    "/api/maemul", "/api/maemul/list", "/api/property", "/api/property/list",
    "/api/properties", "/api/listings", "/api/post", "/api/posts",
    "/api/redevelopment/maemul", "/api/board/maemul", "/api/v2/maemul",
    "/api/maemul/latest", "/api/latest-maemul",
]
for ep in candidates:
    try:
        rr = S.get(BASE + ep, params={"page": 1, "size": 3}, timeout=20, verify=False)
        if rr.status_code != 404:
            show(f"GET {ep}", rr)
    except Exception as e:
        print(f"### GET {ep} -> ERROR {e}")

print("\n===== 4) 홈 HTML의 __NEXT_DATA__에서 매물 API 힌트 =====")
r = S.get(BASE + "/", timeout=20, verify=False)
for m in re.findall(r"/api/[A-Za-z0-9_/\-]{3,50}", r.text):
    if any(k in m.lower() for k in ("maemul", "property", "listing", "post", "item", "board", "latest")):
        print("  홈 참조 API:", m)

print("\n===== 끝 =====")
