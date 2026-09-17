"""탐침 2단계 - 네프콘 채널 글목록 API와 카페 글목록 응답 구조 확인.

1단계 결과:
  · naver.me/xFLApksH -> contents.premium.naver.com/jejeguide/jejemvp
  · naver.me/x78NrtkA -> contents.premium.naver.com/jejeguide/jeje
    (주소가 {크리에이터}/{채널} 두 마디였는데 첫 마디만 보고 404를 맞았다)
  · 카페 휴멘(clubId=31636706) 글목록은 로그인 없이 200으로 읽힌다:
    apis.naver.com/cafe-web/cafe2/ArticleListV2.json?search.clubid=...
"""

import json
import re
import sys

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
S = requests.Session()
S.headers.update({"User-Agent": UA})

CHANNELS = [("jejeguide", "jejemvp"), ("jejeguide", "jeje")]
CLUB_ID = 31636706
CAFE_URL = "https://cafe.naver.com/jejeria"


def get(label, url, **kw):
    try:
        r = S.get(url, timeout=20, **kw)
    except Exception as e:
        print(f"    [{label}] 실패 {type(e).__name__}: {e}")
        return None
    print(f"    [{label}] http={r.status_code} len={len(r.text)} ct={(r.headers.get('content-type') or '')[:35]}")
    return r


def main():
    for creator, channel in CHANNELS:
        page_url = f"https://contents.premium.naver.com/{creator}/{channel}"
        print("=" * 70)
        print(f"채널 {creator}/{channel}")
        r = get("채널 페이지", page_url)
        if not r or r.status_code != 200:
            continue
        html = r.text

        for pat in (r'"channelId"\s*:\s*"?([\w-]+)"?', r'"channelNo"\s*:\s*(\d+)',
                    r'"channelName"\s*:\s*"([^"]{1,40})"', r'"volumeNo"\s*:\s*(\d+)',
                    r'"contentsNo"\s*:\s*(\d+)'):
            hits = list(dict.fromkeys(re.findall(pat, html)))[:6]
            if hits:
                print(f"    {pat} -> {hits}")

        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        print(f"    __NEXT_DATA__: {'있음' if m else '없음'}")
        if m:
            try:
                props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                print(f"    pageProps 키: {list(props.keys())[:15]}")
                print(f"    pageProps 일부: {json.dumps(props, ensure_ascii=False)[:600]}")
            except Exception as e:
                print(f"    __NEXT_DATA__ 파싱 실패: {e}")

        found = set()
        for src in re.findall(r'<script[^>]+src="([^"]+)"', html)[:14]:
            u = src if src.startswith("http") else ("https:" + src if src.startswith("//")
                                                    else f"https://contents.premium.naver.com{src}")
            try:
                js = S.get(u, timeout=25).text
            except Exception:
                continue
            for p in re.findall(r'["\'`]((?:https://[\w.]*premium[\w.]*)?/(?:api|v\d)[\w./{}$-]{3,80})["\'`]', js):
                found.add(p)
        hits = sorted(p for p in found if re.search(r"content|article|volume|list|channel", p, re.I))
        print(f"    JS 내 API 후보 {len(hits)}개:")
        for p in hits[:30]:
            print(f"      {p}")

        for label, u in [
            ("api.premium contents", f"https://api.premium.naver.com/contents/channels/{channel}/contents?page=0&size=5"),
            ("api.premium v1", f"https://api.premium.naver.com/v1/channels/{channel}/contents?page=0&size=5"),
            ("contents.premium api", f"https://contents.premium.naver.com/api/channels/{channel}/contents?page=0&size=5"),
            ("rss", f"https://contents.premium.naver.com/rss/{creator}/{channel}"),
        ]:
            rr = get(label, u, headers={"Accept": "application/json, */*", "Referer": page_url})
            if rr is not None and rr.status_code == 200:
                print(f"      body: {rr.text[:300]}")

    print("\n" + "=" * 70)
    print("카페 휴멘 글목록 구조")
    u = (f"https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json?search.clubid={CLUB_ID}"
         "&search.queryType=lastArticle&search.page=1&search.perPage=5")
    r = get("ArticleListV2", u, headers={"Referer": CAFE_URL})
    if r and r.status_code == 200:
        result = r.json()["message"]["result"]
        print(f"    cafeName={result.get('cafeName')} hasNext={result.get('hasNext')}")
        arts = result.get("articleList", [])
        print(f"    글 {len(arts)}건, 첫 글 필드: {sorted(arts[0].keys()) if arts else '없음'}")
        for a in arts[:5]:
            print(f"      #{a.get('articleId')} [{a.get('menuName')}] {a.get('subject')} "
                  f"/ {a.get('writeDateTimestamp')} / {a.get('writerNickname')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
