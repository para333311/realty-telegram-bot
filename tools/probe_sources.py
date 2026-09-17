"""탐침 4단계 - 네프콘 글 카드에서 제목을 뽑는 선택자 확인.

3단계 결과:
  · 채널 페이지는 서버렌더 HTML이고 글 링크가 그대로 있다:
      <a href="/{creator}/{channel}/contents/{contentId}" class="channel_content_link">
  · contentId는 260917133337835uw 꼴 = YYMMDDHHMMSSmmm + 두 글자 (작성일시가 들어있다)
  · 같은 페이지에 recommend_item_link(추천글)·channel_pick_review_footer_link(픽 댓글)
    같은 잡음 링크가 섞여 있으므로 channel_content_link 만 골라야 한다
  · /{creator}/{channel}/contents 라는 별도 목록 페이지도 200이다
"""

import re
import sys

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
S = requests.Session()
S.headers.update({"User-Agent": UA})

CHANNELS = [("jejeguide", "jejemvp"), ("jejeguide", "jeje")]


def dump(creator, channel, path):
    url = f"https://contents.premium.naver.com/{creator}/{channel}{path}"
    r = S.get(url, timeout=20)
    print(f"\n--- {url} -> http={r.status_code} len={len(r.text)}")
    soup = BeautifulSoup(r.text, "html.parser")

    # 채널 이름
    title_tag = soup.find("title")
    print(f"    <title>: {title_tag.get_text(strip=True) if title_tag else None}")

    links = soup.select("a.channel_content_link")
    print(f"    a.channel_content_link {len(links)}개")
    if links:
        card = links[0].find_parent(class_="channel_content_card") or links[0]
        print(f"    첫 카드 HTML(1200자):\n{str(card)[:1200]}\n")
        for i, a in enumerate(links[:6]):
            href = a.get("href")
            texts = [t.strip() for t in a.stripped_strings]
            print(f"    [{i}] {href}\n        조각: {texts[:6]}")

    # 클래스 이름에 title/subject 들어간 것들
    classes = set()
    for el in soup.select('[class*="title"], [class*="subject"], [class*="name"]'):
        for c in el.get("class") or []:
            if re.search(r"title|subject|name", c):
                classes.add(c)
    print(f"    title/subject 계열 클래스: {sorted(classes)[:20]}")


def main():
    for creator, channel in CHANNELS:
        print("=" * 70)
        print(f"채널 {creator}/{channel}")
        for path in ("", "/contents"):
            try:
                dump(creator, channel, path)
            except Exception as e:
                print(f"    실패 {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
