"""(임시) booriny.com 접근성/구조 조사. 로그인·비밀번호는 다루지 않는다. 조사 후 삭제."""

import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def get(url, **kw):
    try:
        r = S.get(url, timeout=30, verify=False, allow_redirects=True, **kw)
        r.encoding = "utf-8"
        print(f"### GET {url[:90]} -> {r.status_code}, {len(r.text)}b, 최종URL={r.url[:90]}")
        return r
    except Exception as e:
        print(f"### GET {url[:90]} -> ERROR {e}")
        return None


print("===== 1) 기본 접근성 (해외 차단 여부) =====")
r = get("https://booriny.com/")
if r and r.status_code == 200:
    # 로그인 필요 여부 힌트
    low = r.text.lower()
    print("  '로그인' 언급:", "로그인" in r.text, "| naver login:", "nid.naver" in low or "naver" in low)
    # API/데이터 엔드포인트 흔적
    eps = set(re.findall(r"[\"'](/[A-Za-z0-9_/.\-]{3,60}\.(?:do|json|php|api))[\"']", r.text))
    eps |= set(re.findall(r"(/api/[A-Za-z0-9_/.\-]{2,60})", r.text))
    print("  엔드포인트 후보:", sorted(eps)[:25])
    # 매물/필터 관련 키워드
    for kw in ("다세대", "매물", "최저가", "sido", "gugun", "sigungu", "price", "list"):
        if kw in r.text:
            m = r.text.find(kw)
            print(f"  '{kw}' 주변: ...{r.text[max(0,m-40):m+60]!r}...")

print("\n===== 2) 흔한 매물 목록 경로 시도 =====")
for path in ("/list", "/maemul", "/property/list", "/api/maemul/list",
             "/api/property", "/board/list", "/item/list", "/search"):
    rr = get("https://booriny.com" + path)

print("\n===== 3) robots.txt / sitemap (구조 파악) =====")
get("https://booriny.com/robots.txt")

print("\n===== 끝 =====")
