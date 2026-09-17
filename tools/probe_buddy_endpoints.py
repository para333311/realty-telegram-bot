"""탐침 3단계 - m.blog BuddyList의 전체 목록 API와 총 이웃 수를 찾는다.

2단계 결과: m.blog.naver.com/BuddyList.naver?blogId={id} 는 200이지만 HTML에
blogId가 51개만 들어있고 __NEXT_DATA__도, 페이지네이션 파라미터도 없다.
클라이언트가 나머지를 별도 API로 받아온다는 뜻이므로, JS 번들과 HTML에서
그 경로와 총 이웃 수를 찾는다.
"""

import json
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
S.headers.update({"User-Agent": UA, "Referer": f"https://m.blog.naver.com/{MY_ID}"})


def show(label, url, **kw):
    try:
        r = S.get(url, timeout=20, **kw)
    except Exception as e:
        print(f"  [{label}] 실패 {type(e).__name__}: {e}")
        return None
    ids = sorted(set(re.findall(r'"blogId"\s*:\s*"([\w-]+)"', r.text)))
    ids += sorted(set(re.findall(r'blogId=([\w-]+)', r.text)))
    print(
        f"  [{label}] http={r.status_code} len={len(r.text)} "
        f"ct={r.headers.get('content-type','')[:40]} 고유blogId={len(set(ids))}"
    )
    if r.status_code == 200 and len(r.text) < 3000:
        print(f"      body: {re.sub(r'%s' % r'\s+', ' ', r.text[:500])}")
    return r


def main():
    page = S.get(f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}", timeout=20)
    html = page.text
    print(f"BuddyList HTML http={page.status_code} len={len(html)}\n")

    print("== HTML 안의 buddy 관련 문맥 ==")
    for m in list(re.finditer(r"[Bb]uddy", html))[:14]:
        s = max(0, m.start() - 90)
        print("   ..." + re.sub(r"\s+", " ", html[s : m.start() + 110]))

    print("\n== 총 이웃 수처럼 보이는 값 ==")
    for pat in (r'"?totalCount"?\s*[:=]\s*(\d+)', r'"?buddyCount"?\s*[:=]\s*(\d+)',
                r'"?totalBuddyCount"?\s*[:=]\s*(\d+)', r'이웃\s*([\d,]+)\s*명',
                r'"?count"?\s*[:=]\s*(\d+)'):
        hits = re.findall(pat, html)[:8]
        if hits:
            print(f"   {pat} -> {hits}")

    print("\n== JS 번들에서 buddy API 경로 찾기 ==")
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    print(f"   script {len(srcs)}개")
    seen_paths = set()
    for src in srcs:
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://m.blog.naver.com" + src
        try:
            js = S.get(src, timeout=20).text
        except Exception:
            continue
        for p in re.findall(r'["\'`](/[\w./{}$-]*[Bb]uddy[\w./{}$-]*)["\'`]', js):
            if p not in seen_paths:
                seen_paths.add(p)
                print(f"   {p}   (from {src.rsplit('/',1)[-1]})")
    if not seen_paths:
        print("   못 찾음")

    print("\n== API 후보 직접 호출 ==")
    cands = [
        ("api/blogs/buddies", f"https://m.blog.naver.com/api/blogs/{MY_ID}/buddies?countPerPage=200&currentPage=1"),
        ("rego BuddyList", f"https://m.blog.naver.com/rego/BuddyList.naver?blogId={MY_ID}"),
        ("m BuddyListAsync", f"https://m.blog.naver.com/BuddyListAsync.naver?blogId={MY_ID}&currentPage=2"),
        ("api buddy list", f"https://m.blog.naver.com/api/buddy/list?blogId={MY_ID}&currentPage=1"),
        ("BuddyList json", f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}&currentPage=2&type=json"),
    ]
    for label, url in cands:
        show(label, url, headers={"Accept": "application/json, text/plain, */*"})

    ids = sorted(set(re.findall(r'"blogId"\s*:\s*"([\w-]+)"', html)))
    print(f"\n[HTML에서 뽑은 blogId] {len(ids)}개")
    print(json.dumps(ids, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
