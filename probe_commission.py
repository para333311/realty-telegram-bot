"""(임시) commission 일정 HTML 구조 덤프 + 위원회명. 조사 후 삭제."""

import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://commission.eseoul.go.kr"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
                  "Referer": BASE + "/mainInitPlatForm.do"})

r = S.get(BASE + "/cmitInfo/cmitSchdulList.do", params={"cmitId": "CM03"}, timeout=25, verify=False)
r.encoding = "utf-8"
soup = BeautifulSoup(r.text, "html.parser")

print("===== 1) 표/목록 컨테이너 후보 =====")
for sel in ("table", "ul", "ol", ".list", "#cmitOpmtTbl", "tbody", "tr", "li", ".schedule", ".result"):
    els = soup.select(sel)
    if els:
        print(f"  {sel}: {len(els)}개")

print("\n===== 2) '제N차' / 날짜 포함 요소 =====")
for el in soup.find_all(True):
    txt = el.get_text(" ", strip=True)
    if re.search(r"제\s*\d+\s*차", txt) and len(txt) < 200 and el.name in ("tr", "li", "div", "td", "a", "span", "p"):
        cls = el.get("class")
        print(f"  <{el.name} class={cls}> {txt[:120]!r}")
        if sum(1 for _ in soup.find_all(el.name, class_=cls)) < 60:
            pass

print("\n===== 3) 날짜(2026...) 주변 원문 스니펫 =====")
for m in list(re.finditer(r"20\d{2}[.\-]\s?\d{1,2}[.\-]\s?\d{1,2}", r.text))[:3]:
    s = max(0, m.start()-200)
    seg = re.sub(r"\s+", " ", r.text[s:m.end()+120])
    print(f"  ...{seg!r}...")

print("\n===== 4) 표 헤더(th) =====")
for th in soup.select("th")[:15]:
    print("  th:", th.get_text(strip=True)[:30])

print("\n===== 5) AJAX로 목록 다시 부르나? (js내 .do 호출) =====")
for m in re.findall(r"(?:url\s*:\s*|ajax\()['\"]([^'\"]+\.do)['\"]", r.text)[:10]:
    print("  ajax:", m)
for m in re.findall(r"function\s+(fn\w+)", r.text)[:15]:
    print("  fn:", m)

print("\n===== 6) 위원회명 (page title 영역) =====")
for sel in (".sub_tit", ".location", ".lnb", "h2", "h3", ".cmit"):
    e = soup.select_one(sel)
    if e:
        print(f"  {sel}: {e.get_text(' ', strip=True)[:50]!r}")

print("\n끝")
