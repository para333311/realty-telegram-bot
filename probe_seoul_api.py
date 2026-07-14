"""(임시) 서울 열린데이터광장 OpenAPI 조사 2차. 조사 후 삭제 예정."""

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
        print(f"### GET {r.url} -> {r.status_code}, {len(r.text)} bytes")
        return r
    except Exception as e:
        print(f"### GET {url} -> ERROR {e}")
        return None


def show_api_tab(oa_id):
    """데이터셋의 OpenAPI 탭(A타입)에서 서비스명/샘플 URL 추출."""
    r = get(f"https://data.seoul.go.kr/dataList/{oa_id}/A/1/datasetView.do")
    if not r or r.status_code != 200:
        return
    text = r.text
    m = re.search(r"<title>([^<]*)</title>", text)
    infnm = re.findall(r'infNm["\']?\s*[:=]\s*["\']([^"\']+)', text)
    print(f"  [{oa_id}] infNm: {infnm[:1]}")
    for pat in (r"openapi\.seoul\.go\.kr:8088/[^\s\"'<>]+",
                r'serviceNm["\']?\s*[:=]\s*["\']([A-Za-z0-9_]+)',
                r'infId["\']?\s*[:=]\s*["\']([A-Za-z0-9_-]+)',
                r"/(?:xml|json|xls)/([A-Za-z][A-Za-z0-9_]{3,60})/1/",
                r'"srvNm"\s*:\s*"([^"]+)"'):
        found = set(re.findall(pat, text))
        if found:
            print(f"  [{oa_id}] {pat[:25]}...: {sorted(found)[:8]}")


def try_service(service, n=3):
    r = get(f"http://openapi.seoul.go.kr:8088/sample/json/{service}/1/{n}/")
    if not r or r.status_code != 200:
        return False
    try:
        data = json.loads(r.text)
    except Exception:
        print("  (json 아님)", r.text[:200])
        return False
    for v in data.values():
        if isinstance(v, dict) and v.get("row"):
            row = v["row"][0]
            print(f"  ✅ {service} 필드: {sorted(row.keys())}")
            compact = {k: str(val)[:60] for k, val in row.items() if k != "POST_CONTENT"}
            print(f"     첫 행: {json.dumps(compact, ensure_ascii=False)[:700]}")
            return True
    print(f"  ❌ {service}: {str(data)[:120]}")
    return False


print("=========== 1) SeoulNewsList 전체 필드 (부서명 있나?) ===========")
try_service("SeoulNewsList")

print("\n=========== 2) 데이터셋 검색 폼 파라미터 파악 ===========")
r = get("https://data.seoul.go.kr/dataList/datasetList.do")
if r:
    inputs = re.findall(r"<(?:input|select)[^>]*name=[\"']([^\"']+)", r.text)
    print("  폼 필드:", sorted(set(inputs)))
    forms = re.findall(r"<form[^>]*action=[\"']([^\"']+)[\"'][^>]*>", r.text)
    print("  폼 액션:", sorted(set(forms))[:10])
    # 검색 관련 자바스크립트 함수 흔적
    for m in sorted(set(re.findall(r"function\s+(fn\w*[Ss]earch\w*)", r.text)))[:10]:
        print("  검색 함수:", m)

print("\n=========== 3) 검색 시도 (여러 파라미터) ===========")
for params in ({"searchDataDesc": "결재문서"}, {"schData": "결재문서"},
               {"sSearchValue": "결재문서"}, {"searchNm": "결재문서"}):
    r = get("https://data.seoul.go.kr/dataList/datasetList.do", params=params)
    if r:
        titles = re.findall(r'infNm["\']?\s*[:=]\s*["\']([^"\']+)', r.text)
        ids = re.findall(r"OA-\d+", r.text)
        pair = sorted(set(zip(ids, titles)))[:6] if len(ids) == len(titles) else sorted(set(ids))[:6]
        print(f"  {list(params)[0]} -> {pair}")

print("\n=========== 4) 통합검색 API ===========")
for url in ("https://data.seoul.go.kr/totSearch/totSearchList.do?searchKeyword=결재문서",
            "https://data.seoul.go.kr/totSearch/search.do?query=결재문서"):
    r = get(url)
    if r and r.status_code == 200:
        ids = sorted(set(re.findall(r"OA-\d+", r.text)))[:15]
        print("  발견 ID:", ids)

print("\n=========== 5) OpenAPI 탭(A타입) 페이지에서 서비스명 ===========")
for oa in ("OA-12709", "OA-12651", "OA-2191"):
    show_api_tab(oa)

print("\n=========== 6) 결재문서/고시공고 서비스명 후보 대량 시도 ===========")
candidates = [
    # 결재문서(정보소통광장)
    "OpenGovDocList", "SeoulSanctionList", "InfoSotongSanction", "OpenGovList",
    "ApprovalDocList", "SanctionDocList", "OpenDataSanction",
    # 영등포/양천 고시/공지/보도
    "YdpNews", "YangcheonNoticeList", "SebcNotice",
]
for c in candidates:
    try_service(c, 1)

print("\n=========== 끝 ===========")
