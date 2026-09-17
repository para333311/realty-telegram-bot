"""네이버 '내 이웃 목록'을 로그인 없이 읽을 수 있는 경로를 찾는 일회성 탐침.

blogs.txt 자동 동기화가 가능한지 판단하려고 만들었다. 후보 엔드포인트를 전부
찔러보고, 응답에 blogs.txt에 이미 있는 블로그 아이디가 몇 개나 들어있는지 센다.
많이 겹칠수록 그게 진짜 이웃 목록이다.

사용법: MY_BLOG_ID=para333311 python tools/probe_buddy_endpoints.py
"""

import os
import re
import sys

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

MY_ID = os.environ.get("MY_BLOG_ID", "para333311")

CANDIDATES = [
    ("rss 정상확인(대조군)", f"https://rss.blog.naver.com/{MY_ID}.xml"),
    ("BuddyList type=1", f"https://blog.naver.com/BuddyList.naver?blogId={MY_ID}&type=1"),
    ("BuddyList type=0", f"https://blog.naver.com/BuddyList.naver?blogId={MY_ID}&type=0"),
    ("BuddyList 기본", f"https://blog.naver.com/BuddyList.naver?blogId={MY_ID}"),
    ("m.BuddyList", f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}"),
    ("BuddyListAsync", f"https://blog.naver.com/BuddyListAsync.naver?blogId={MY_ID}&currentPage=1"),
    (
        "section ConnectBuddy",
        f"https://section.blog.naver.com/ajax/ConnectBuddy.naver?blogId={MY_ID}",
    ),
    (
        "section ViewMoreFollowers",
        f"https://section.blog.naver.com/connect/ViewMoreFollowers.naver?blogId={MY_ID}",
    ),
    ("api buddies", f"https://blog.naver.com/api/blogs/{MY_ID}/buddies?page=1"),
    (
        "WidgetListAsync buddy",
        f"https://blog.naver.com/WidgetListAsync.naver?blogId={MY_ID}&widgetId=buddy",
    ),
]


def known_ids():
    ids = set()
    with open("blogs.txt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line)
    return ids


def main():
    known = known_ids()
    print(f"blogs.txt 등록 아이디 {len(known)}개, 내 블로그={MY_ID}\n")

    for label, url in CANDIDATES:
        print("=" * 70)
        print(f"[{label}]\n{url}")
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": f"https://blog.naver.com/{MY_ID}"},
                timeout=20,
            )
        except Exception as e:
            print(f"  요청 실패: {type(e).__name__}: {e}")
            continue

        body = r.text
        found = sorted(i for i in known if re.search(rf"\b{re.escape(i)}\b", body))
        print(f"  http={r.status_code} len={len(body)} type={r.headers.get('content-type')}")
        print(f"  blogs.txt와 겹치는 아이디: {len(found)}개 {found[:12]}")
        snippet = re.sub(r"\s+", " ", body[:400])
        print(f"  앞부분: {snippet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
