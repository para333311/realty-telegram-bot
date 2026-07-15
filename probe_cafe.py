"""(임시) 네이버카페 jaegebal 접근/검색 방법 조사. 조사 후 삭제."""

import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def get(url, **kw):
    try:
        r = S.get(url, timeout=25, verify=False, allow_redirects=True, **kw)
        r.encoding = "utf-8"
        print(f"### GET {url[:100]} -> {r.status_code}, {len(r.text)}b, 최종={r.url[:70]}")
        return r
    except Exception as e:
        print(f"### GET {url[:100]} -> ERROR {e}")
        return None


print("===== 1) 카페 홈에서 clubid(카페 내부 id) 찾기 =====")
r = get("https://cafe.naver.com/jaegebal")
clubid = None
if r:
    for pat in (r"clubid[=:\"']+(\d+)", r"cafeId[=:\"']+(\d+)", r"g_sClubId\s*=\s*[\"'](\d+)"):
        m = re.search(pat, r.text)
        if m:
            clubid = m.group(1)
            print("  clubid:", clubid)
            break
    if not clubid:
        print("  clubid 못 찾음. 앞부분:", r.text[:200].replace("\n", " "))

print("\n===== 2) 모바일 카페 페이지 =====")
get("https://m.cafe.naver.com/ca-fe/web/cafes/jaegebal")
get("https://m.cafe.naver.com/jaegebal")

print("\n===== 3) 카페 RSS 시도 =====")
for u in ("https://cafe.naver.com/jaegebal.xml",
          "https://rss.cafe.naver.com/jaegebal.xml"):
    get(u)

print("\n===== 4) 카페 글 검색(로그인 없이 되나) =====")
if clubid:
    for u in (f"https://cafe.naver.com/ArticleSearchList.nhn?search.clubid={clubid}&search.query=%EC%84%A4%EB%AA%85%ED%9A%8C",
              f"https://apis.naver.com/cafe-web/cafe-articlesearch-api/v3/cafes/{clubid}/articles?query=%EC%84%A4%EB%AA%85%ED%9A%8C&sortBy=date"):
        get(u)

print("\n===== 5) 네이버 검색 API(cafearticle) — 키없이 응답 형태 =====")
r = get("https://openapi.naver.com/v1/search/cafearticle.json?query=%EC%9E%AC%EA%B0%9C%EB%B0%9C%20%EC%84%A4%EB%AA%85%ED%9A%8C&display=5")
if r:
    print("  응답 앞부분:", r.text[:250])

print("\n끝")
