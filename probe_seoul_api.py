"""(임시) 서울 열린데이터광장 OpenAPI 조사 4차. 조사 후 삭제 예정."""

import json

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"})


def try_service(service, n=1):
    try:
        r = S.get(f"http://openapi.seoul.go.kr:8088/sample/json/{service}/1/{n}/",
                  timeout=20, verify=False)
        data = json.loads(r.text)
    except Exception as e:
        print(f"  {service} -> ERROR {e}")
        return False
    for v in data.values():
        if isinstance(v, dict) and v.get("row"):
            row = v["row"][0]
            compact = {k: str(val)[:60] for k, val in row.items()
                       if "CONTENT" not in k.upper()}
            print(f"  ✅ {service}: {json.dumps(compact, ensure_ascii=False)[:400]}")
            return True
    return False


print("===== 1) 25개 구 NewsNoticeList 전수 조사 =====")
prefixes = ["Jongno", "Junggu", "Jung", "Yongsan", "Seongdong", "Gwangjin",
            "Dongdaemun", "Ddm", "Jungnang", "Seongbuk", "Gangbuk", "Dobong",
            "Nowon", "Eunpyeong", "Ep", "Seodaemun", "Sdm", "Mapo",
            "Yangcheon", "YangCheon", "Gangseo", "Guro", "Geumcheon", "Gumcheon",
            "Ydp", "Dongjak", "Gwanak", "Seocho", "Gangnam", "Songpa", "Gangdong"]
ok = [p for p in prefixes if try_service(p + "NewsNoticeList")]
print("  성공 prefix:", ok)

print("\n===== 2) 양천구 다른 이름 후보 =====")
for svc in ("YangcheonNoticeList", "YangcheonNewsList", "YangcheonGosiList",
            "YcNewsNoticeList", "YangcheonNewsGosiList"):
    try_service(svc)

print("\n===== 3) 결재문서 후보 =====")
for svc in ("OpenGovSanction", "SeoulOpenGovSanction", "OpenGovDocInfo",
            "GovDocList", "ApprDocList", "ElecApprovalList", "SanctionInfo",
            "OpenGovBasisList", "InfoDisclosureList"):
    try_service(svc)

print("\n===== 4) 서울시 보도자료 링크 형식 검증 =====")
try:
    r = S.get("http://openapi.seoul.go.kr:8088/sample/json/SeoulNewsList/1/1/",
              timeout=20, verify=False)
    post_id = json.loads(r.text)["SeoulNewsList"]["row"][0]["POST_ID"]
    print("  POST_ID:", post_id)
    for url in (f"https://mediahub.seoul.go.kr/archives/{post_id}",
                f"https://www.seoul.go.kr/news/news_report.do#view/{post_id}"):
        try:
            rr = S.get(url, timeout=15, verify=False, allow_redirects=True)
            head = rr.text[:400].replace("\n", " ")
            print(f"  {url} -> {rr.status_code}, {len(rr.text)}b, 앞부분: {head[:150]}")
        except Exception as e:
            print(f"  {url} -> ERROR {e}")
except Exception as e:
    print("  링크 검증 실패:", e)

print("\n===== 끝 =====")
