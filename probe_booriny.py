"""(임시) booriny.com 로그인 방식 조사. 비밀번호 미사용 — 로그인 엔드포인트/방식만 확인. 조사 후 삭제."""

import json
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://booriny.com"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def get(url, **kw):
    try:
        r = S.get(url, timeout=30, verify=False, **kw)
        r.encoding = "utf-8"
        print(f"### GET {url[:95]} -> {r.status_code}, {len(r.text)}b")
        return r
    except Exception as e:
        print(f"### GET {url[:95]} -> ERROR {e}")
        return None


print("===== 1) 홈에서 JS 번들 목록 =====")
r = get(BASE + "/")
scripts = []
if r:
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    scripts = [s if s.startswith("http") else BASE + s for s in scripts]
    print("  JS 번들:", scripts[:20])
    # 홈 HTML에 naver 로그인 흔적
    print("  nid.naver 언급:", "nid.naver" in r.text, "| kakao:", "kakao" in r.text.lower(),
          "| /api/auth:", "/api/auth" in r.text)

print("\n===== 2) JS 번들에서 login/auth 관련 조사 =====")
auth_eps = set()
naver_hit = kakao_hit = False
for js in scripts[:15]:
    rr = get(js)
    if not rr or rr.status_code != 200:
        continue
    t = rr.text
    if "nid.naver.com" in t or "naver.com/oauth" in t:
        naver_hit = True
    if "kauth.kakao" in t or "kakao.com/oauth" in t:
        kakao_hit = True
    # 로그인/인증 관련 API 경로
    for m in re.findall(r'["\'`](/api/[A-Za-z0-9_/\-]{2,50})["\'`]', t):
        low = m.lower()
        if any(k in low for k in ("login", "auth", "signin", "token", "session", "user", "member")):
            auth_eps.add(m)
    # 이메일/비번 필드 힌트
    for m in re.findall(r'["\'](email|password|userId|loginId|username|pwd)["\']', t):
        auth_eps.add("field:" + m)

print("\n  === 결과 ===")
print("  naver SSO 사용:", naver_hit)
print("  kakao SSO 사용:", kakao_hit)
print("  인증 관련 엔드포인트/필드:", sorted(auth_eps)[:30])

print("\n===== 3) 로그인 엔드포인트 형태 확인 (빈 요청으로 응답 구조만) =====")
for ep in sorted(e for e in auth_eps if e.startswith("/api")):
    for method in ("POST",):
        try:
            resp = S.post(BASE + ep, json={}, timeout=20, verify=False)
            print(f"  {method} {ep} -> {resp.status_code}: {resp.text[:150]!r}")
        except Exception as e:
            print(f"  {method} {ep} -> ERROR {e}")

print("\n===== 끝 =====")
