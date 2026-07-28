"""키워드 필터 회귀 테스트.

실제 서울시·구청 문서 제목(후니동산 주간 클리핑이 근거로 삼는 공문들)이
감시 키워드에 걸리는지, 그리고 도시정비와 무관한 제목이 걸리지 않는지 검증한다.

키워드를 손볼 때마다 여기 케이스를 돌려서 "새 유형을 잡으려다 기존 알림을
깨뜨리거나 오탐을 늘리는" 사고를 막는다.

실행:  python test_keywords.py
"""

import sys

import keywords as keyword_presets
from check_once import title_matches
from check_korea import KEYWORDS as OPENGOV_KEYWORDS
from check_sibo import KEYWORDS as SIBO_KEYWORDS

# ── 반드시 알림되어야 하는 실제 문서 제목 ──────────────────────────────
# (출처: 2026-07 서울시/자치구 공개 공문·고시공고 제목)
MUST_MATCH = [
    # 모아타운 — 주민제안·자문·관리계획 단계
    "군자동 159-1번지 일대 모아타운 주민제안 신청에 따른 협의 회신",
    "모아타운(예정) 지역 내 건축허가 등 제한 요청(구의1동 226 및 231번지 일대)",
    "모아타운(예정) 구역 내 건축허가 제한(변경) 안내문",
    "상도21구역 모아타운·모아주택 주민간담회 개최 계획",
    "`26년 제12차 전문가 자문회의 결과 알림(암사동 495번지 일원 모아타운)",
    "2026년 제12차 전문가 자문회의 결과 알림(강동구)",
    "모아타운 관리계획 총괄계획가(MP) 선정 및 운영 철저 알림",
    "모아타운 관리계획 주민제안 전자동의 지원사업 대상지 수시 공모 시행 재알림 및 적극 홍보 요청",
    "삼선동3가 42-7번지 일대 모아타운 주민제안 대상지 범위 변경 협의 회신",
    "삼선동3가 42-7번지 일대 모아타운 주민제안 전문가 대상지선정 자문회의 신청 검토보고",
    "목2동 231-27번지 일대 소규모주택정비 관리계획(모아타운 관리계획) 수립(안) 주민공람 공고",
    "응봉동 265 일대 모아타운 관리계획(안) 전문가 자문회의 상정 요청",
    "「숭실대입구역 남측 모아타운 기본구상 및 건축계획 수립 용역」최종결과 보고",
    "모아타운 주민제안 신청에 따른 보완 요청(천호동 191일대 모아타운)",
    # 신속통합기획 — 후보지·동의서·구역계 단계
    "고덕1지구 동의서 연번부여 반대 및 휴먼타운 2.0지정 촉구",
    "신월2동 470번지 신속통합기획 후보지 수시모집 관련 검토자료 회신",
    "남가좌동 3-62번지 일대 신속통합기획 주택재개발사업 입안요청 관련 안내 및 후보지 추천 제외 공고 알림",
    "자양1동 614번지 일대 신속통합기획 추진 관련 동의서 번호 부여 및 주민설명회 개최",
    "북가좌동 3-191 일대 신속통합기획 주택재개발사업 후보지 구역계 확대 관련 은평구 관할 필지 편입 협의 요청",
    "「전농동 152-65 일대 주택정비형 재개발사업」 조합설립추진위원회 (예비)추진위원장·(예비)감사 선거를 위한 선거인명부 확정 공고",
    "다수인 민원 접수 및 검토 보고(도화동 196-11번지 일대 신속통합기획)",
    # 사업 유형어 없이 절차만 적힌 문서 (가장 놓치기 쉬운 유형)
    "정비구역 등 권리산정기준일 지정 고시",
    "모아주택 사업시행계획 인가 신청 반려 알림",
    "소규모주택정비 관리계획 결정(변경) 고시",
    "휴먼타운 2.0(관리형 주택정비형) 대상지 선정 결과 알림",
    "소규모주택정비 전문가 사전자문 요청",
    # 단계별 인가 고시 (기존 알림 회귀 확인)
    "소규모재건축사업 사업시행계획인가 고시",
    "가로주택정비사업 조합설립인가 고시",
    "도심공공주택 복합사업 예정지구 지정 제안",
    "주택재개발정비사업 관리처분계획 인가 고시",
]

# opengov(집 노트북 결재문서 감시)는 키워드당 검색 1회 비용이 있어 소음이 큰
# '역세권·지구단위계획·토지거래허가'를 의도적으로 뺐다. 구청 게시판(@표준)이
# 같은 내용을 커버하므로 여기서만 예외로 둔다.
MUST_MATCH_EXCEPT_OPENGOV = [
    "역세권 장기전세주택 건립 관련 지구단위계획 결정",
    "도로 지목에 한한 토지거래허가구역 지정 공고",
]

# 서울도시공간포털 결정고시(@도시계획)에만 있는 '도시관리계획' 키워드 케이스.
# 재개발 문맥이면 통과, 기반시설(도로·철도) 고시면 제외되어야 한다.
URBAN_NOTICE_MATCH = [
    "도시관리계획(암사·명일아파트지구 지구단위계획구역 지정 및 지구단위계획) 결정 및 지형도면 고시",
    "도시관리계획(강동대로 주변 지구단위계획구역 및 계획) 결정(변경) 및 지형도면 고시",
    "도시관리계획(천호지구 지구단위계획) 변경(경미한 변경) 결정 및 지형도면 고시",
]
URBAN_NOTICE_NOT_MATCH = [
    "도시관리계획(도시계획시설:철도) 결정(경미한 변경) 및 지형도면 고시",
    "도시관리계획(도시계획시설:도로) 결정 및 지형도면 고시",
    "도시관리계획(도시계획시설 : 철도 및 광장) 결정(경미한 변경) 및 지형도면 고시",
]

# ── 알림되면 안 되는 제목(오탐) ────────────────────────────────────────
MUST_NOT_MATCH = [
    "불법광고물 정비 기간제근로자 채용 공고",
    "중랑천 물놀이장 휴장 안내(침수정비 및 오후우천)",
    "인재개발원 인재기획과 교육 알림",
    "공무원증 일련번호 및 개인정보 제공 동의서 제출",
    "관내 도로 가로등 정비 공사 계약",
    "어린이집 통학차량 운행 동의 서류 제출 안내",
    "○○어린이공원 조성 사업 주민설명회 개최 알림",
    "구립도서관 리모델링 주민공람 공고",
    "건축허가 신청 처리기한 안내 및 주차 제한구역 변경 알림",
    "체육센터 이용료 감면 대상자 선정 결과",
    "재활용 분리배출 주민설명회 개최",
]


def keyword_sets():
    sets = {}
    for name in keyword_presets.PRESETS:
        resolved, unknown = keyword_presets.resolve([name])
        assert not unknown, f"프리셋 해석 실패: {unknown}"
        sets[name] = resolved
    sets["opengov"] = OPENGOV_KEYWORDS
    return sets


def main():
    failures = []
    sets = keyword_sets()

    for name, kws in sets.items():
        expected = list(MUST_MATCH)
        if name != "opengov":
            expected += MUST_MATCH_EXCEPT_OPENGOV
        for title in expected:
            if not title_matches(title, kws):
                failures.append(f"[{name}] 누락: {title}")
        for title in MUST_NOT_MATCH:
            if title_matches(title, kws):
                failures.append(f"[{name}] 오탐: {title}")

    # '도시관리계획'은 @도시계획 프리셋에만 있으므로 그 세트로만 검사한다.
    urban = sets["@도시계획"]
    for title in URBAN_NOTICE_MATCH:
        if not title_matches(title, urban):
            failures.append(f"[@도시계획] 누락: {title}")
    for title in URBAN_NOTICE_NOT_MATCH:
        if title_matches(title, urban):
            failures.append(f"[@도시계획] 오탐(기반시설 고시): {title}")

    # 서울시보 목차는 단순 부분일치로 검사되므로(check_sibo) 대표 유형만 확인
    sibo_expected = [
        "모아타운 관리계획 결정 고시",
        "정비구역 지정 및 정비계획 결정 고시",
        "소규모주택정비 관리계획 결정 고시",
        "토지거래허가구역 지정 공고",
    ]
    for title in sibo_expected:
        if not any(k in title for k in SIBO_KEYWORDS):
            failures.append(f"[서울시보] 누락: {title}")

    for name, kws in sets.items():
        print(f"{name}: {len(kws)}개 키워드")
    if failures:
        print(f"\n실패 {len(failures)}건:")
        for f in failures:
            print("  ✗", f)
        return 1
    total = len(MUST_MATCH) + len(MUST_MATCH_EXCEPT_OPENGOV)
    print(
        f"\n✅ 통과: 실제 문서 {total}종 알림 확인, "
        f"오탐 후보 {len(MUST_NOT_MATCH)}종 차단 확인"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
