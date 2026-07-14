"""(임시) 서울 열린데이터광장 OpenAPI 조사 3차. 조사 후 삭제 예정."""

import json
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def get(url, **kw):
    try:
        r = S.get(url, timeout=30, verify=False, **kw)
        r.encoding = "utf-8"
        print(f"### GET {r.url[:120]} -> {r.status_code}, {len(r.text)} bytes")
        return r
    except Exception as e:
        print(f"### GET {url[:120]} -> ERROR {e}")
        return None


def try_service(service, n=2, quiet=False):
    r = None
    try:
        r = S.get(f"http://openapi.seoul.go.kr:8088/sample/json/{service}/1/{n}/",
                  timeout=20, verify=False)
    except Exception as e:
        print(f"  {service} -> ERROR {e}")
        return False
    try:
        data = json.loads(r.text)
    except Exception:
        print(f"  {service} -> json 아님 {r.text[:120]}")
        return False
    for v in data.values():
        if isinstance(v, dict) and v.get("row"):
            row = v["row"][0]
            print(f"  ✅ {service} 필드: {sorted(row.keys())}")
            compact = {k: str(val)[:70] for k, val in row.items()
                       if "CONTENT" not in k.upper()}
            print(f"     첫 행: {json.dumps(compact, ensure_ascii=False)[:600]}")
            return True
    if not quiet:
        code = ""
        try:
            code = (data.get("RESULT") or {}).get("CODE", "")
        except Exception:
            pass
        print(f"  ❌ {service} {code}")
    return False


print("=========== 1) 데이터셋 페이지에서 서비스명 원문 덤프 ===========")
for oa in ("OA-12709", "OA-2192", "OA-12651"):
    r = get(f"https://data.seoul.go.kr/dataList/{oa}/A/1/datasetView.do")
    if not r:
        continue
    text = r.text
    # 후보 토큰: JS/HTML 안의 CamelCase List/Info 이름들
    tokens = set(re.findall(r"[A-Z][A-Za-z0-9]{4,50}(?:List|Info|Status|Service)", text))
    noise = {"SelectBox", "TabList", "DataList", "PageList", "MenuList", "FileList",
             "CodeList", "BbsList", "CommentList", "TagList", "ChartList"}
    tokens = sorted(t for t in tokens if t not in noise)
    print(f"  [{oa}] 후보 토큰: {tokens[:30]}")
    for m in re.finditer(r"8088", text):
        s = max(0, m.start() - 80)
        print(f"  [{oa}] 8088 주변: ...{text[s:m.end()+120]!r}...")

print("\n=========== 2) 메타 API (전체 서비스 목록) 후보 호출 ===========")
meta_found = False
for svc in ("SearchApiListService", "ApiInfoService", "OpenApiList", "InfApiList",
            "SearchApiService", "ListApiService"):
    if try_service(svc, 3, quiet=True):
        meta_found = True

print("\n=========== 3) 규칙 기반 서비스명 그리드 시도 ===========")
prefixes = ["Ydp", "Yeongdeungpo", "Yangcheon", "Yc", "Junggu", "JungGu",
            "Seocho", "Songpa", "Seodaemun", "Sdm"]
suffixes = ["NewsNoticeList", "NoticeList", "GosiList", "NewsGosiList", "GosiGonggoList"]
hits = []
for p in prefixes:
    for s in suffixes:
        if try_service(p + s, 1, quiet=True):
            hits.append(p + s)
print("  그리드 성공:", hits)

print("\n=========== 4) 영등포 보도자료(OA-12709)의 실제 서비스명 확인 ===========")
for svc in ("YdpNewsList", "YeongdeungpoNewsList", "YdpBodoList", "YdpPressList",
            "YeongdeungpoPressList"):
    try_service(svc, 1, quiet=True)

print("\n=========== 5) 결재문서 후보 ===========")
for svc in ("OpenGovSanctions", "SanctionsList", "GovSanctionList", "OpenGovDoc",
            "SeoulOpenGovList", "DocSanctionList", "OpenGovInfoList"):
    try_service(svc, 1, quiet=True)

print("\n=========== 끝 ===========")
