"""(임시) 서울 열린데이터광장에서 필요한 OpenAPI 서비스명을 찾는 조사 스크립트.

GitHub Actions에서 실행되어 로그로 결과를 출력한다. 조사가 끝나면 삭제 예정.
찾는 데이터셋:
- 서울정보소통광장 결재문서 목록
- 영등포구 고시공고
- 양천구 고시공고
- 서울시 보도자료(새소식)
"""

import json
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
})


def get(url, **kw):
    try:
        r = S.get(url, timeout=30, verify=False, **kw)
        r.encoding = "utf-8"
        print(f"### GET {url} -> {r.status_code}, {len(r.text)} bytes")
        return r
    except Exception as e:
        print(f"### GET {url} -> ERROR {e}")
        return None


def show_dataset_page(oa_id):
    """데이터셋 페이지에서 서비스명/샘플URL 추출."""
    r = get(f"https://data.seoul.go.kr/dataList/{oa_id}/S/1/datasetView.do")
    if not r or r.status_code != 200:
        return
    text = r.text
    for m in set(re.findall(r"openapi\.seoul\.go\.kr:8088/[^\s\"'<>]+", text)):
        print(f"  [{oa_id}] sample url: {m}")
    for m in set(re.findall(r'infNm["\']?\s*[:=]\s*["\']([^"\']+)', text)):
        print(f"  [{oa_id}] infNm: {m}")
    # 서비스명(영문) 패턴들
    for pat in (r"서비스명[^가-힣A-Za-z]{0,20}([A-Za-z][A-Za-z0-9_]{3,60})",
                r'"serviceNm"\s*:\s*"([^"]+)"',
                r"/(?:xml|json)/([A-Za-z][A-Za-z0-9_]+)/1/5"):
        for m in set(re.findall(pat, text)):
            print(f"  [{oa_id}] service?: {m}")
    title = re.search(r"<title>([^<]*)</title>", text)
    if title:
        print(f"  [{oa_id}] title: {title.group(1).strip()}")


def search_datasets(keyword):
    print(f"\n===== 검색: {keyword} =====")
    # 열린데이터광장 검색 (파라미터명이 확실치 않아 두 가지 시도)
    for param in ("srchText", "searchText"):
        r = get("https://data.seoul.go.kr/dataList/datasetList.do",
                params={"isOpenApiMenu": "Y", "srvType": "A", param: keyword})
        if not r or r.status_code != 200:
            continue
        ids = re.findall(r"OA-\d+", r.text)
        if ids:
            print(f"  발견된 데이터셋 ID: {sorted(set(ids))[:20]}")
            return sorted(set(ids))
    # 통합검색 API 시도
    r = get("https://data.seoul.go.kr/api/datasetList", params={"searchText": keyword})
    if r and r.status_code == 200:
        print("  api/datasetList 응답 앞부분:", r.text[:500])
    return []


def try_sample_service(service):
    r = get(f"http://openapi.seoul.go.kr:8088/sample/json/{service}/1/5/")
    if not r or r.status_code != 200:
        return
    try:
        data = json.loads(r.text)
    except Exception:
        print("  (json 아님)", r.text[:300])
        return
    print(f"  {service} keys: {list(data.keys())}")
    for k, v in data.items():
        if isinstance(v, dict):
            if "row" in v and v["row"]:
                print(f"  {service} 첫 행: {json.dumps(v['row'][0], ensure_ascii=False)[:600]}")
            elif "RESULT" in v:
                print(f"  {service} RESULT: {v['RESULT']}")
        elif k == "RESULT":
            print(f"  {service} RESULT: {v}")


print("================ 1) 접속 가능 여부 ================")
get("https://data.seoul.go.kr/")
get("http://openapi.seoul.go.kr:8088/sample/json/SearchSTNBySubwayLineInfo/1/2/")  # 잘 알려진 샘플

print("\n================ 2) 데이터셋 검색 ================")
found = {}
for kw in ("결재문서", "영등포구 고시공고", "양천구 고시공고", "서울특별시 보도자료", "새소식"):
    found[kw] = search_datasets(kw)

print("\n================ 3) 알려진/발견된 데이터셋 페이지 ================")
known = {"OA-12709", "OA-12651"}  # 영등포구 보도자료, 서초구 공지사항
for ids in found.values():
    known.update(ids[:5])
for oa in sorted(known):
    show_dataset_page(oa)

print("\n================ 4) 서비스명 후보 샘플 호출 ================")
for svc in ("SeoulNewsList", "OpenGovSanctionList", "SanctionList",
            "SebcNoticeList", "YdpNoticeList"):
    try_sample_service(svc)

print("\n================ 조사 끝 ================")
