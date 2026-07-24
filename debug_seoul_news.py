"""임시 진단 스크립트 2단계.

1) 알림 링크(mediahub.seoul.go.kr/archives/{POST_ID})가 실제로 열리는지 확인
2) 진짜 보도자료 목록(www.seoul.go.kr/news/news_report.do)이
   GitHub Actions에서 읽히는지, 기존 범용 파서로 파싱되는지 확인
"""

import json
import os
import re

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

KEY = os.environ.get("SEOUL_API_KEY", "").strip() or "sample"

print("=== 1) API 첫 행 POST_ID로 mediahub 링크 확인 ===")
r = requests.get(f"http://openapi.seoul.go.kr:8088/{KEY}/json/SeoulNewsList/1/5/", timeout=(15, 40))
service = next((v for v in json.loads(r.text).values() if isinstance(v, dict)), {})
rows = service.get("row") or []
for row in rows[:3]:
    pid = row.get("POST_ID")
    title = str(row.get("POST_TITLE") or "")[:40]
    for base in ("https://mediahub.seoul.go.kr/archives/",
                 "https://news.seoul.go.kr/archives/"):
        url = f"{base}{pid}"
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=(15, 30),
                                allow_redirects=True)
            soup = BeautifulSoup(resp.text, "html.parser")
            page_title = (soup.title.get_text(strip=True) if soup.title else "")[:60]
            print(f"  {url} -> {resp.status_code} 최종={resp.url[:90]} title={page_title!r}")
            print(f"     API제목={title!r} 본문에 제목 포함={title[:15] in resp.text}")
        except Exception as e:
            print(f"  {url} -> 실패: {e}")

print("\n=== 2) 서울시 보도자료 목록 페이지 확인 ===")
for url in ("https://www.seoul.go.kr/news/news_report.do",
            "https://mediahub.seoul.go.kr/news/newsList.do"):
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Referer": url},
                            timeout=(20, 40), verify=False)
        resp.encoding = "utf-8"
        print(f"\n[{url}] -> {resp.status_code}, {len(resp.text)}자")
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select(
            "table tbody tr, .board-list tr, .bbs-list tr, .list_type li, "
            ".news-list li, .search-result-list li, .list-wrap li, .bdList > ul > li"
        )
        print(f"  기존 범용 셀렉터 행 수: {len(rows)}")
        for row in rows[:5]:
            el = (row.select_one(".subject a, .tit a, .title a")
                  or row.select_one(".subject, .tit, .title, .s a, a"))
            text = el.get_text(strip=True)[:60] if el else "(제목 못찾음)"
            href = el.get("href", "")[:70] if el is not None and el.name == "a" else ""
            date = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", row.get_text(" ", strip=True))
            print(f"   - {text!r} href={href!r} 날짜={date[:2]}")
        if not rows:
            for sel in ("li", "dl", ".article", ".card"):
                print(f"  참고: {sel} 개수 {len(soup.select(sel))}")
            print("  본문 앞부분:", resp.text[:300].replace("\n", " "))
    except Exception as e:
        print(f"[{url}] 실패: {e}")
