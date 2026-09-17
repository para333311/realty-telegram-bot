"""탐침 3단계 - 네프콘 채널 페이지 HTML에서 글 목록을 직접 뽑을 수 있는지.

2단계 결과:
  · api.premium.naver.com 은 DNS에 없다(그런 호스트가 아님)
  · 채널 페이지는 200에 96~110KB짜리 HTML이고 __NEXT_DATA__는 없다
    -> Next.js App Router의 self.__next_f 청크이거나 서버렌더 HTML일 것
  · 카페는 이미 해결: ArticleListV2.json 이 로그인 없이 글목록을 준다
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


def main():
    for creator, channel in CHANNELS:
        url = f"https://contents.premium.naver.com/{creator}/{channel}"
        print("=" * 70)
        print(f"채널 {creator}/{channel}  ({url})")
        r = S.get(url, timeout=20)
        html = r.text
        print(f"  http={r.status_code} len={len(html)}")

        links = list(dict.fromkeys(re.findall(rf'/{creator}/{channel}/contents/[\w-]+', html)))
        print(f"  글 링크 후보 {len(links)}개: {links[:10]}")

        chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
        print(f"  __next_f 청크 {len(chunks)}개")
        blob = ""
        if chunks:
            try:
                blob = "".join(json.loads(f'"{c}"') for c in chunks)
            except Exception as e:
                print(f"  청크 디코드 실패: {e}")
        print(f"  디코드된 blob 길이: {len(blob)}")

        haystack = blob or html
        for pat in (r'"contentsNo"\s*:\s*"?([\w-]+)"?',
                    r'"title"\s*:\s*"([^"]{4,60})"',
                    r'"channelName"\s*:\s*"([^"]{1,40})"',
                    r'"contentsTitle"\s*:\s*"([^"]{4,60})"'):
            hits = list(dict.fromkeys(re.findall(pat, haystack)))[:8]
            if hits:
                print(f"  {pat}\n     -> {hits}")

        # 글 제목이 서버렌더 HTML에 그대로 있는지
        for m in list(re.finditer(r"contents/", haystack))[:3]:
            s = max(0, m.start() - 300)
            print(f"  ...{re.sub(chr(92)+'s+', ' ', haystack[s:m.start() + 300])}...\n")

        # 구독 없이 목록만 주는 별도 경로 후보
        for label, u in [
            ("?page=2", f"{url}?page=2"),
            ("/contents", f"{url}/contents"),
            ("api/channels", f"https://contents.premium.naver.com/api/channels/{channel}/volumes?page=0&size=5"),
            ("nlog list", f"https://contents.premium.naver.com/{creator}/{channel}/recent"),
        ]:
            try:
                rr = S.get(u, timeout=20, headers={"Referer": url})
                print(f"  [{label}] http={rr.status_code} len={len(rr.text)}")
            except Exception as e:
                print(f"  [{label}] 실패 {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
