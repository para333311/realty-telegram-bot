"""탐침 4단계 - /api/blogs/{blogId}/buddies 의 정확한 파라미터를 JS 번들에서 캔다.

3단계 결과:
  · m.blog BuddyList 페이지는 이웃을 서버렌더 HTML로 50명까지만 담고 있다
  · 번들에 /api/blogs/${e}/buddies 계열 경로가 실재하고, 파라미터 없이 부르면
    500 + JSON 에러가 돌아온다 → 엔드포인트는 맞고 파라미터가 틀린 것
"""

import os
import re
import sys

import requests

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
MY_ID = os.environ.get("MY_BLOG_ID", "para333311")
S = requests.Session()
S.headers.update(
    {
        "User-Agent": UA,
        "Referer": f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
)


def ctx(js, needle, span=260, limit=8):
    out = []
    for m in list(re.finditer(re.escape(needle), js))[:limit]:
        s = max(0, m.start() - span)
        out.append(js[s : m.start() + span])
    return out


def main():
    html = S.get(f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}", timeout=20).text

    # 총 이웃 수 힌트
    print("== '명' 앞뒤 문맥 ==")
    for m in list(re.finditer(r"명", html))[:10]:
        print("   ..." + re.sub(r"\s+", " ", html[max(0, m.start() - 120) : m.start() + 30]))

    srcs = [s for s in re.findall(r'<script[^>]+src="([^"]+)"', html) if "main" in s or ".js" in s]
    print(f"\n== JS {len(srcs)}개에서 buddies 호출부 ==")
    for src in srcs:
        url = src if src.startswith("http") else ("https:" + src if src.startswith("//") else "https://m.blog.naver.com" + src)
        try:
            js = S.get(url, timeout=25).text
        except Exception:
            continue
        for needle in ("/buddies", "BuddyList.naver", "buddyList"):
            for c in ctx(js, needle, 240, 4):
                print(f"   [{needle}] ...{c}...\n")

    print("== /api/blogs/{id}/buddies 파라미터 조합 ==")
    base = f"https://m.blog.naver.com/api/blogs/{MY_ID}/buddies"
    param_sets = [
        {},
        {"page": 1, "size": 50},
        {"currentPage": 1, "countPerPage": 50},
        {"offset": 0, "limit": 50},
        {"buddyGroupId": 0, "page": 1},
        {"page": 1, "size": 50, "sortType": "UPDATE"},
        {"nextFrom": 1, "count": 50},
    ]
    for p in param_sets:
        try:
            r = S.get(base, params=p, timeout=20)
        except Exception as e:
            print(f"   {p} -> 실패 {e}")
            continue
        body = re.sub(r"\s+", " ", r.text[:300])
        print(f"   {p} -> http={r.status_code} len={len(r.text)} body={body}")

    print("\n== blog.naver.com(데스크톱) 쪽 동일 API ==")
    for host in ("https://blog.naver.com", "https://section.blog.naver.com"):
        r = S.get(f"{host}/api/blogs/{MY_ID}/buddies", params={"page": 1, "size": 50}, timeout=20)
        body = re.sub(r"\s+", " ", r.text[:200])
        print(f"   {host} -> http={r.status_code} len={len(r.text)} {body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
