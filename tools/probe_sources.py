"""네프콘 채널 2개와 카페 1개의 새 글 목록을 로그인 없이 읽을 수 있는지 찾는 탐침.

개발 컨테이너는 naver.com 이그레스가 막혀 있어 Actions에서 실측한다.
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

SHORT_LINKS = ["https://naver.me/xFLApksH", "https://naver.me/x78NrtkA"]
CAFE_URL = "https://cafe.naver.com/jejeria"


def head(label, url, **kw):
    try:
        r = S.get(url, timeout=20, **kw)
    except Exception as e:
        print(f"  [{label}] 실패 {type(e).__name__}: {e}")
        return None
    ct = (r.headers.get("content-type") or "")[:40]
    print(f"  [{label}] http={r.status_code} len={len(r.text)} ct={ct}")
    return r


def main():
    print("=" * 70)
    print("1) 단축링크 풀기")
    finals = []
    for link in SHORT_LINKS:
        try:
            r = S.get(link, timeout=20, allow_redirects=True)
            print(f"  {link}\n    -> {r.url}  (http={r.status_code})")
            finals.append(r.url)
        except Exception as e:
            print(f"  {link} 실패: {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print("2) 네프콘 채널 페이지에서 API 경로 찾기")
    for url in finals:
        m = re.search(r"contents\.premium\.naver\.com/([\w-]+)", url)
        if not m:
            print(f"  {url} -> 네프콘 주소가 아님, 건너뜀")
            continue
        channel = m.group(1)
        print(f"\n  -- 채널 '{channel}' --")
        r = head("채널 페이지", f"https://contents.premium.naver.com/{channel}")
        if not r:
            continue
        html = r.text

        # 페이지에 박힌 채널 식별자
        for pat in (r'"channelId"\s*:\s*"?([\w-]+)"?', r'"channelName"\s*:\s*"([^"]+)"',
                    r'"contentsNo"\s*:\s*(\d+)', r'"channelKey"\s*:\s*"([^"]+)"'):
            hits = list(dict.fromkeys(re.findall(pat, html)))[:5]
            if hits:
                print(f"     {pat} -> {hits}")

        api_paths = sorted(set(re.findall(r'["\'](/?(?:api|v1)[\w./{}$-]*)["\']', html)))[:25]
        print(f"     HTML 내 api 후보: {api_paths[:15]}")

        srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
        print(f"     script {len(srcs)}개")
        found = set()
        for src in srcs[:12]:
            u = src if src.startswith("http") else ("https:" + src if src.startswith("//")
                                                    else "https://contents.premium.naver.com" + src)
            try:
                js = S.get(u, timeout=25).text
            except Exception:
                continue
            for p in re.findall(r'["\'`](/(?:api|v\d)[\w./{}$-]*(?:contents|articles|volumes)[\w./{}$-]*)["\'`]', js):
                if p not in found:
                    found.add(p)
        for p in sorted(found)[:25]:
            print(f"     JS: {p}")

        # 흔한 목록 API 후보 직접 호출
        for label, u in [
            ("api.premium contents", f"https://api.premium.naver.com/contents/channels/{channel}/contents?page=0&size=10"),
            ("api.premium volumes", f"https://api.premium.naver.com/channel/channels/{channel}/contents?page=0&size=10"),
            ("contents.premium api", f"https://contents.premium.naver.com/api/channels/{channel}/contents?page=0&size=10"),
            ("rss", f"https://contents.premium.naver.com/rss/{channel}"),
        ]:
            rr = head(label, u, headers={"Accept": "application/json, */*",
                                         "Referer": f"https://contents.premium.naver.com/{channel}"})
            if rr is not None and rr.status_code == 200 and len(rr.text) < 1500:
                print(f"       body: {re.sub(r'[srn]+', ' ', rr.text[:400])}")

    print("\n" + "=" * 70)
    print("3) 카페 jejeria")
    r = head("카페 페이지", CAFE_URL)
    club_ids = []
    if r:
        club_ids = list(dict.fromkeys(re.findall(r'clubid[=\"\':\s]+(\d{6,})', r.text, re.I)))
        club_ids += list(dict.fromkeys(re.findall(r'"cafeId"\s*:\s*"?(\d{6,})"?', r.text)))
        print(f"  clubId 후보: {club_ids[:5]}")
    for label, u in [
        ("CafeInfo", "https://apis.naver.com/cafe-web/cafe2/CafeInfo.json?cafeUrl=jejeria"),
        ("GateInfo", "https://apis.naver.com/cafe-web/cafe-cafeinfo-api/v1.0/cafes/jejeria/info"),
    ]:
        rr = head(label, u, headers={"Referer": CAFE_URL})
        if rr is not None and rr.status_code == 200:
            print(f"    body: {rr.text[:300]}")
            club_ids += re.findall(r'"cafeId"\s*:\s*"?(\d{6,})"?', rr.text)

    for cid in list(dict.fromkeys(club_ids))[:2]:
        print(f"\n  -- clubId={cid} 글목록 API --")
        for label, u in [
            ("ArticleList.json", f"https://apis.naver.com/cafe-web/cafe2/ArticleList.json?search.clubid={cid}&search.queryType=lastArticle&search.page=1&search.perPage=10"),
            ("ArticleListV2dot1", f"https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json?search.clubid={cid}&search.queryType=lastArticle&search.menuid=0&search.page=1&search.perPage=10"),
            ("f-e articles", f"https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json?search.clubid={cid}&search.queryType=lastArticle&search.page=1&search.perPage=10"),
        ]:
            rr = head(label, u, headers={"Referer": CAFE_URL})
            if rr is not None and rr.status_code == 200:
                print(f"    body 앞부분: {rr.text[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
