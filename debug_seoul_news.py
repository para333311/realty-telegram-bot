"""임시 진단 스크립트: 서울시 보도자료 OpenAPI(SeoulNewsList) 응답 구조 확인.

- 필드 이름과 샘플 값(부서/링크/날짜 후보)을 찍어 필터가 왜 거의 안 걸리는지 확인한다.
- API 키는 절대 출력하지 않는다.
"""

import json
import os

import requests

KEY = os.environ.get("SEOUL_API_KEY", "").strip() or "sample"
URL = f"http://openapi.seoul.go.kr:8088/{KEY}/json/SeoulNewsList/1/50/"

DEPTS = ["공공주택과", "공동주택과", "신속통합기획과", "도시계획과", "주거정비과", "전략주택공급과"]
KEYWORDS = ["재개발", "재건축", "신속통합", "모아타운", "도심복합", "정비계획",
            "정비구역", "정비사업", "후보지", "역세권", "통합심의", "심의위원회"]

r = requests.get(URL, timeout=(15, 40))
print("status:", r.status_code)
data = json.loads(r.text)

service = next((v for v in data.values() if isinstance(v, dict)), {})
print("list_total_count:", service.get("list_total_count"))
print("RESULT:", service.get("RESULT"))
rows = service.get("row") or []
print("rows:", len(rows))
if not rows:
    raise SystemExit(0)

print("\n=== 필드 이름(첫 행 기준, dict 순서) ===")
for k, v in rows[0].items():
    s = str(v).replace("\n", " ")
    print(f"  {k}: {s[:120]}")

print("\n=== 행별 요약 (index | 날짜후보 | http값 | 부서필드 | 제목) ===")
dept_keys = [k for k in rows[0] if any(x in k.upper() for x in ("DEPT", "DEPART", "ORG", "BUSEO"))]
print("부서로 보이는 필드:", dept_keys)
for i, row in enumerate(rows):
    values = {k: str(v).strip() for k, v in row.items() if v is not None}
    https = [f"{k}={v[:70]}" for k, v in values.items() if v.startswith("http")]
    depts = {k: values.get(k, "") for k in dept_keys}
    title = next((values[k] for k in ("TITLE", "POST_TITLE", "SJ", "NTT_SJ", "SUBJECT")
                  if values.get(k)), "")
    date_like = [f"{k}={v[:30]}" for k, v in values.items()
                 if any(c.isdigit() for c in v) and ("-" in v or "/" in v or "." in v)]
    print(f"[{i:02d}] 날짜후보={date_like[:3]}")
    print(f"     http값={https[:3]}")
    print(f"     부서={depts} 제목={title[:60]}")

print("\n=== 필터 시뮬레이션 ===")
title_hits = dept_hits = 0
for row in rows:
    values = {k: str(v).strip() for k, v in row.items() if v is not None}
    title = next((values[k] for k in ("TITLE", "POST_TITLE", "SJ", "NTT_SJ", "SUBJECT")
                  if values.get(k)), "")
    row_text = " ".join(v for k, v in values.items()
                        if not any(x in k.upper() for x in ("CONTENT", "EXCERPT", "DESC")))
    if any(k in title for k in KEYWORDS):
        title_hits += 1
    hit_depts = [d for d in DEPTS if d in row_text]
    if hit_depts:
        dept_hits += 1
        print("  부서매치:", hit_depts, title[:50])
print(f"제목 키워드 매치 {title_hits}건 / 부서 매치 {dept_hits}건 (전체 {len(rows)}행)")

print("\n=== 전체 부서값 분포 ===")
seen = {}
for row in rows:
    for k in dept_keys:
        v = str(row.get(k) or "").strip()
        if v:
            seen[f"{k}:{v}"] = seen.get(f"{k}:{v}", 0) + 1
for k, c in sorted(seen.items(), key=lambda x: -x[1]):
    print(f"  {c:3d}  {k}")
