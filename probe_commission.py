"""(임시) commission 위원회별 일정표 구조 + 코드 매핑 확인. 조사 후 삭제."""

import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://commission.eseoul.go.kr"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
                  "Referer": BASE + "/mainInitPlatForm.do"})


def dump(cmit_id):
    r = S.get(BASE + "/cmitInfo/cmitSchdulList.do", params={"cmitId": cmit_id}, timeout=25, verify=False)
    r.encoding = "utf-8"
    if "loginForm" in r.url or r.status_code != 200:
        print(f"  cmitId={cmit_id} -> 실패({r.status_code}, login={('loginForm' in r.url)})")
        return
    soup = BeautifulSoup(r.text, "html.parser")
    # 위원회명 추출
    name = ""
    for sel in ("h1", "h2", "h3", ".title", ".cmit_name", "title"):
        e = soup.select_one(sel)
        if e and e.get_text(strip=True):
            name = e.get_text(strip=True)[:40]
            break
    # 표 행
    rows = soup.select("table tbody tr")
    print(f"  cmitId={cmit_id} | {len(r.text)}b | 명칭후보:{name!r} | table tbody tr {len(rows)}행")
    for tr in rows[:3]:
        cells = [td.get_text(' ', strip=True)[:35] for td in tr.select("td, th")]
        a = tr.select_one("a")
        href = (a.get("href") or a.get("onclick") or "")[:60] if a else ""
        print(f"    {cells} | link={href!r}")


print("===== cmitId 형식 확인 (01 vs CM01) =====")
for cid in ("01", "CM01"):
    dump(cid)

print("\n===== 10개 위원회 코드별 일정표 =====")
for cid in ("CM01", "CM02", "CM03", "CM05", "CM07", "CM08", "CM09", "CM10", "CM11", "CM12"):
    dump(cid)

print("\n===== 메인에서 위원회명↔코드 매핑 =====")
home = S.get(BASE + "/mainInitPlatForm.do", timeout=30, verify=False)
home.encoding = "utf-8"
soup = BeautifulSoup(home.text, "html.parser")
# 카드 구조: 위원회명 + fnMainCmitSchdul('CMxx')
for m in re.finditer(r"fnMainCmitSchdul\('(CM\d+)'\)", home.text):
    code = m.group(1)
    # 주변 텍스트에서 위원회명 찾기
    seg = home.text[max(0, m.start()-400):m.start()]
    names = re.findall(r"[가-힣·]{4,20}위원회|[가-힣·]{4,20}자문단", seg)
    print(f"  {code} <- {names[-1] if names else '?'}")

print("\n끝")
