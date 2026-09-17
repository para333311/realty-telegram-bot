"""탐침 5단계 - /api/blogs/{blogId}/public-buddies?pageNo=N 전수 확인.

4단계에서 m.blog 번들의 호출부를 찾았다:
  get(`/api/blogs/${blogId}/public-buddies?${stringify({pageNo})}`)
  meta 에 totalPublicBuddyCount / currentCursor 가 들어온다.
여기서 페이지를 끝까지 돌려 전체 이웃 수와 blogs.txt 차이를 확인한다.
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
S.headers.update(
    {
        "User-Agent": UA,
        "Referer": f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}",
        "Accept": "application/json, text/plain, */*",
    }
)
API = f"https://m.blog.naver.com/api/blogs/{MY_ID}/public-buddies"


def main():
    r = S.get(API, params={"pageNo": 1}, timeout=20)
    print(f"pageNo=1 -> http={r.status_code} len={len(r.text)}")
    print(f"body 앞부분: {r.text[:600]}\n")
    if r.status_code != 200:
        return 1

    data = r.json()
    result = data.get("result", data.get("data", {}).get("result", {}))
    print(f"최상위 키: {list(data.keys())}")
    print(f"result 키: {list(result.keys()) if isinstance(result, dict) else type(result)}")
    for k in ("totalPublicBuddyCount", "totalCount", "currentPage", "currentCursor"):
        if isinstance(result, dict) and k in result:
            print(f"  {k} = {result[k]}")

    all_ids, page = [], 1
    while page <= 30:
        rr = S.get(API, params={"pageNo": page}, timeout=20)
        if rr.status_code != 200:
            print(f"pageNo={page} http={rr.status_code} 중단")
            break
        res = rr.json().get("result", {})
        items = res.get("buddyList") or res.get("items") or []
        ids = [it.get("blogId") for it in items if it.get("blogId")]
        print(f"  pageNo={page}: {len(ids)}명")
        if not ids:
            break
        before = len(all_ids)
        all_ids += [i for i in ids if i not in all_ids]
        if len(all_ids) == before:
            print("  (새 아이디 없음 → 페이지네이션 끝)")
            break
        page += 1

    known = [
        l.strip()
        for l in open("blogs.txt", encoding="utf-8")
        if l.strip() and not l.startswith("#")
    ]
    print(f"\n== 결과 ==")
    print(f"네이버 공개 이웃: {len(all_ids)}명 / blogs.txt: {len(known)}개")
    print(f"이웃인데 blogs.txt에 없음({len(set(all_ids)-set(known))}): {sorted(set(all_ids)-set(known))}")
    print(f"blogs.txt에만 있음({len(set(known)-set(all_ids))}): {sorted(set(known)-set(all_ids))}")
    print("\n전체 이웃 목록:")
    print(json.dumps(all_ids, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
