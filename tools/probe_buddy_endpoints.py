"""m.blog.naver.com BuddyList 페이지에서 이웃 목록을 뽑아내는 방법을 찾는 탐침 2단계.

1단계에서 https://m.blog.naver.com/BuddyList.naver?blogId={id} 가 로그인 없이
200으로 열리고 blogs.txt의 아이디가 다수 들어있음을 확인했다. 이제 그 안에서
전체 이웃 목록을 구조적으로 꺼낼 수 있는지(__NEXT_DATA__ / 내부 JSON API /
페이지네이션)를 본다.
"""

import json
import os
import re
import sys

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MY_ID = os.environ.get("MY_BLOG_ID", "para333311")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Referer": f"https://m.blog.naver.com/{MY_ID}"})


def walk(node, path="$", depth=0, out=None):
    """JSON 트리에서 블로그 아이디 리스트처럼 보이는 곳을 찾는다."""
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(node, dict):
        keys = set(node.keys())
        if keys & {"blogId", "blogid"} and keys & {"blogName", "nickName", "nickname", "blogTitle"}:
            out.append((path, node))
        for k, v in node.items():
            walk(v, f"{path}.{k}", depth + 1, out)
    elif isinstance(node, list):
        for i, v in enumerate(node[:3]):
            walk(v, f"{path}[{i}]", depth + 1, out)
    return out


def main():
    url = f"https://m.blog.naver.com/BuddyList.naver?blogId={MY_ID}"
    r = SESSION.get(url, timeout=20)
    html = r.text
    print(f"GET {url} -> http={r.status_code} len={len(html)}\n")

    # 1) 페이지 안에서 호출하는 내부 API 경로 흔적
    api_hits = sorted(set(re.findall(r"[\"'](/[\w./-]*[Bb]uddy[\w./-]*)[\"']", html)))
    print(f"[내부 API 후보] {api_hits[:20]}\n")

    # 2) __NEXT_DATA__ 파싱
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        print("[__NEXT_DATA__] 없음")
    else:
        data = json.loads(m.group(1))
        print(f"[__NEXT_DATA__] 최상위 키: {list(data.keys())}")
        props = data.get("props", {}).get("pageProps", {})
        print(f"[pageProps] 키: {list(props.keys())}")
        found = walk(data)
        print(f"[블로그 항목처럼 보이는 노드] {len(found)}개")
        for path, node in found[:3]:
            print(f"  {path} -> {json.dumps(node, ensure_ascii=False)[:300]}")
        # 이웃 리스트 후보의 실제 길이 찾기
        for path, node in found[:1]:
            parent_path = path.rsplit("[", 1)[0]
            print(f"  (리스트 경로 추정: {parent_path})")

    # 3) 페이지네이션 파라미터가 먹는지
    for extra in ("&currentPage=2", "&page=2", "&nextPage=2"):
        r2 = SESSION.get(url + extra, timeout=20)
        ids2 = set(re.findall(r'"blogId"\s*:\s*"([\w-]+)"', r2.text))
        ids1 = set(re.findall(r'"blogId"\s*:\s*"([\w-]+)"', html))
        print(
            f"[{extra}] http={r2.status_code} len={len(r2.text)} "
            f"blogId수={len(ids2)} 1페이지와동일={ids2 == ids1}"
        )

    ids1 = sorted(set(re.findall(r'"blogId"\s*:\s*"([\w-]+)"', html)))
    print(f"\n[1페이지에서 추출한 blogId] {len(ids1)}개")
    print(json.dumps(ids1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
