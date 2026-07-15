"""(임시) 네이버카페 jaegebal 검색 API 상세 조사. 조사 후 삭제."""

import json

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CLUBID = "12730407"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/604.1",
    "Referer": "https://m.cafe.naver.com/ca-fe/web/cafes/jaegebal/menus/0",
})


def get(url, label, **kw):
    try:
        r = S.get(url, timeout=25, verify=False, **kw)
        r.encoding = "utf-8"
        print(f"\n### [{label}] {r.status_code}, {len(r.text)}b, 최종={r.url[:90]}")
        print("  BODY:", r.text[:900].replace("\n", " "))
        return r
    except Exception as e:
        print(f"\n### [{label}] ERROR {e}")
        return None


kw = "설명회"
kw_enc = requests.utils.quote(kw)

# A) 인-카페 검색 API 여러 버전
for ver in ("v3", "v2.1", "v2"):
    get(f"https://apis.naver.com/cafe-web/cafe-articlesearch-api/{ver}/cafes/{CLUBID}/articles"
        f"?query={kw_enc}&sortBy=date&page=1&perPage=10",
        f"articlesearch-{ver}")

# B) 모바일 카페 게시글 목록 API (검색 아닌 최신글)
get(f"https://apis.naver.com/cafe-web/cafe-mobile/CafeArticleSearchListV3"
    f"?cafeId={CLUBID}&query={kw_enc}&searchBy=1&sortBy=date&page=1&perPage=10",
    "CafeArticleSearchListV3")

# C) gw.artInfo / cafe-home-api 최신글 목록 (메뉴 전체글)
get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{CLUBID}/articles"
    f"?query=&menuId=0&page=1&pageSize=10&sortBy=TIME",
    "articleapi-list")

# D) 통합검색용 모바일 엔드포인트
get(f"https://m.cafe.naver.com/ca-fe/web/cafes/jaegebal/menus/0/articles"
    f"?query={kw_enc}&searchType=1&sortBy=date&page=1",
    "m-cafe-articles")

print("\n끝")
