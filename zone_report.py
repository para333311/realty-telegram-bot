"""수집한 공고를 서울 구별·구역별로 묶어 시계열로 정리한다.

seen_boards.json은 "무엇을 이미 알렸는가"만 기억하는 중복방지 파일이라
구청 게시판 순서대로 쌓여 있다. 한 구역의 이야기(후보지 공개 → 동의서
번호부여 → 정비계획 → 조합설립 → 사업시행 → 관리처분)가 여러 게시판에
흩어져 있어 그대로는 흐름이 안 보인다. 이 스크립트가 그걸 구역 단위로
모아 날짜순으로 세운다.

    python zone_report.py            # 요약 출력 + zones.json 저장
    python zone_report.py --md       # 마크다운 전문 출력

구역 키는 '동+번지'를 1순위로 삼는다. 같은 땅을 두고 나오는 문서가
'자양1동 772-1번지 일대 모아타운 1구역'처럼 사업명이 조금씩 달라도
번지가 같으면 한 묶음이 되게 하려는 것이다. 번지가 없는 문서는
구역명(방배13구역) → 단지명(반포미도2차아파트) 순으로 잡는다.
"""

import argparse
import collections
import json
import re

SEEN_FILE = "seen_boards.json"
OUT_FILE = "zones.json"

GU = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
    "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구",
    "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구",
    "강동구",
]

# 구역이 아니라 시(市) 단위 일정·소식인 게시판. 구역별 정리 대상에서 뺀다.
SKIP_BOARDS = ("위원회 일정", "보도자료")

# 정비사업과 무관한데 '정비'라는 낱말 때문에 수집된 것들
NOISE = re.compile(r"불법광고물|기간제근로자|아카데미|청소년|도로 ?정비 ?공사|가로등|위험수목|임기제공무원|채용 공고|채용공고")

RE_DATE_IN_TITLE = re.compile(
    r"^서울시(?:\s+(\S+구))?\s*(?:고시|공고|보도자료)?\s*•\s*"
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(.+)$"
)
RE_GU_PREFIX = re.compile(r"^\[(\S+?구)\]\s*(.+)$")

# ── 구역 키 추출 ──────────────────────────────────────────────────────
# 1순위: 동 + 번지  ("자양1동 772-1번지 일대", "행촌동 210-2 일대", "구로동 454번지 일원",
#                   "성내동 120-85,86 광신·장미")
# 번지 뒤에 ",86"처럼 필지가 더 붙어도 앞 번지만 키로 쓴다(같은 구역이므로).
RE_DONG_BUNJI = re.compile(
    r"([가-힣]+\d*동|[가-힣]{2,}\d*가)\s*(\d+(?:-\d+)?)(?:\s*,\s*\d+)*\s*(?:번지)?\s*(?:일대|일원|번지)"
)
# 2순위: 구역명  ("방배13구역", "신영제1구역", "세운재정비촉진지구 6-1-1구역",
#                "마포로1구역 제10지구", "모아타운 A1구역", "강북2재정비촉진구역")
RE_ZONE_NAMED = [
    re.compile(r"([가-힣]+(?:로|동|가)?\s?\d+구역\s*제\s?\d+(?:[·,]\d+)*\s?지구)"),
    re.compile(r"([가-힣]{2,}구역\s*제\s?\d+(?:[·,]\d+)*\s?지구)"),
    re.compile(r"([가-힣]{2,}(?:지구|지역)?\s?\d+(?:-\d+)*\s?(?:재정비촉진)?구역)"),
    re.compile(r"(모아타운\s*[A-Z]?\d+구역)"),
    re.compile(r"([가-힣]{2,}\s?제\s?\d+구역)"),
    re.compile(r"(신반포\d+지구|[가-힣]{2,}\d*지구)\s*(?:재건축|재개발)"),
]
# 3순위: 단지명  ("반포미도2차아파트", "상계주공7단지", "한강맨션아파트", "이조빌라")
# '개포우성1・2차아파트'처럼 차수가 쉼표·가운뎃점으로 이어지는 경우가 있어
# 이름 앞부분(한글 2자 이상)을 반드시 함께 잡는다. 안 그러면 '차아파트'만 남는다.
# '반포아파트지구'(지구단위계획 이름)처럼 뒤에 지구·지역이 붙으면 단지가 아니라
# 계획구역 이름이므로 건너뛴다. 그래야 같은 제목의 진짜 주어인
# '반포주공1단지'가 잡힌다.
RE_COMPLEX = re.compile(
    r"([가-힣]{2,}[가-힣A-Za-z0-9]*(?:\s?[\d,·・]+차)?\s?"
    r"(?:아파트|주공\d*단지|단지|맨션|빌라|연립|팰리스|타운하우스))(?!\s*(?:지구|지역))"
)

# 단지명처럼 생겼지만 구역이 아닌 것
COMPLEX_STOP = re.compile(r"^(공동|공공|임대|민간|해당|관련|일반|기존|노후|저층)")

# ── 사업 단계 ─────────────────────────────────────────────────────────
# 정비사업은 정해진 순서로 간다. 한 구역의 공고를 이 순서에 얹으면
# "지금 어디까지 왔는가"가 제목을 다 읽지 않아도 보인다.
# 앞에 오는 규칙이 이긴다 — '조합설립인가를 위한 공람공고'는 공람이 아니라
# 조합설립 단계로 읽어야 하므로 조합설립을 공람보다 위에 둔다.
STAGES = [
    ("관리처분", 6, r"관리처분|보상계획|수용재결|보상협의|현금청산"),
    ("착공·준공", 7, r"준공인가|공사완료|해체공사|착공|안전점검 ?수행기관"),
    ("사업시행", 5, r"사업시행계획|사업시행인가|사업시행\(변경\)"),
    ("조합설립", 4, r"조합설립|추진위원회|주민대표회의"),
    ("동의서", 2, r"동의서|번호 ?부여|연번부여"),
    ("후보지·공모", 1, r"후보지|수시공모|주민제안|주민참여단|사전자문|대상지 ?선정"),
    ("계획수립", 3, r"정비계획|관리계획|정비구역|지구단위계획|재정비촉진계획|열람공고|공람|공청회|주민설명회|지형도면"),
    ("행위제한", 0, r"건축허가.{0,4}제한|개발행위허가 ?제한|토지거래허가"),
    # 아래 둘은 절차 진행이 아니라 곁가지 행정이라 순서(1~7) 밖에 둔다.
    ("용역·발주", 8, r"감리자|제안서 ?평가|전문관리 ?용역|입찰|낙찰|개찰|적격심사"),
    ("위원회 심의", 9, r"위원회 ?심의|심의 ?결과|건축위원회|공동위원회|자문단"),
]
STAGES = [(name, order, re.compile(rx)) for name, order, rx in STAGES]


def stage_of(title):
    """제목에서 사업 단계를 읽는다. (이름, 순서) 반환."""
    for name, order, rx in STAGES:
        if rx.search(title):
            return name, order
    return "기타", 10


def clean_date(s):
    """'2026.09.04'·'2026/9/4' 등을 '2026-09-04'로 맞춘다.

    게시판마다 구분자가 달라서 그대로 두면 문자열 정렬이 뒤엉킨다
    ('-'(0x2D) < '.'(0x2E)라 점 형식이 전부 뒤로 밀린다).
    """
    s = (s or "").strip()
    m = re.match(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def normalize(raw, board):
    """저장 형식 3종을 (구, 날짜, 제목)으로 통일한다."""
    title, _, datepart = raw.rpartition("#")
    if not title:
        title, datepart = raw, ""
    gu, date = None, clean_date(datepart)

    m = RE_DATE_IN_TITLE.match(title)
    if m:  # 재개발닷컴: "서울시 강남구 고시 • 2026년 9월 11일 ..."
        gu = m.group(1)
        date = f"{int(m.group(2)):04d}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"
        title = m.group(4 + 1).strip()
    else:
        m2 = RE_GU_PREFIX.match(title)
        if m2:  # 서울시 도시계획: "[용산구] ..."
            gu, title = m2.group(1), m2.group(2).strip()
        else:  # 구청 게시판: 게시판 이름이 곧 구
            for g in GU:
                if board.startswith(g):
                    gu = g
                    break
    if gu is None:
        for g in GU:
            if g in title:
                gu = g
                break
    return gu, date, title


def canon(name):
    """키 비교용 정규화: 띄어쓰기와 나열 기호를 없앤다.

    같은 단지가 '개포우성1・2차아파트'와 '개포우성1,2차아파트'로 들어와
    두 구역으로 갈라지던 것을 막는다.
    """
    return re.sub(r"[\s,·・⦁ㆍ/]", "", name)


def zone_of(title):
    """제목에서 구역 키와 표시용 이름을 뽑는다. 못 찾으면 (None, None)."""
    m = RE_DONG_BUNJI.search(title)
    if m:
        dong, bunji = m.group(1), m.group(2)
        return canon(f"{dong}{bunji}"), f"{dong} {bunji}번지 일대"

    for rx in RE_ZONE_NAMED:
        m = rx.search(title)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            return canon(name), name

    m = RE_COMPLEX.search(title)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if not COMPLEX_STOP.match(name):
            return canon(name), name
    return None, None


def dedupe(docs):
    """같은 날 같은 공고를 한 줄로 합친다.

    구청 고시공고와 재개발닷컴이 같은 고시를 각각 싣기 때문에 그대로 두면
    한 구역 연표에 같은 줄이 두세 번 나온다. 어느 게시판에서 걸렸는지는
    sources에 모아 둔다.
    """
    merged = {}
    for d in docs:
        k = (d["date"], canon(d["title"]))
        if k in merged:
            if d["board"] not in merged[k]["sources"]:
                merged[k]["sources"].append(d["board"])
        else:
            stage, order = stage_of(d["title"])
            merged[k] = {"date": d["date"], "title": d["title"],
                         "stage": stage, "order": order,
                         "sources": [d["board"]]}
    return list(merged.values())


def build():
    data = json.load(open(SEEN_FILE, encoding="utf-8"))
    # 구 -> 구역키 -> {label, docs[]}
    tree = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"label": None, "docs": []}))
    skipped = collections.Counter()

    for board, entry in data.items():
        if any(s in board for s in SKIP_BOARDS):
            skipped["시 단위 일정·보도자료"] += len(entry.get("keys", []))
            continue
        for raw in entry.get("keys", []):
            gu, date, title = normalize(raw, board)
            if NOISE.search(title):
                skipped["정비사업 무관"] += 1
                continue
            if not gu:
                skipped["구 미상"] += 1
                continue
            key, label = zone_of(title)
            if not key:
                key, label = "_구역미상", "구역 미상(구 전체 공고 등)"
            slot = tree[gu][key]
            slot["label"] = slot["label"] or label
            slot["docs"].append({"date": date, "title": title, "board": board})

    out = {}
    for gu in sorted(tree):
        zones = []
        for key, slot in tree[gu].items():
            docs = dedupe(slot["docs"])
            docs.sort(key=lambda d: (d["date"] or "0000"), reverse=True)
            # 도달 단계 = 그 구역 문서가 닿은 가장 앞선 절차.
            # 행위제한(0)·기타(8)는 진행 순서가 아니라 성격이 다른 공고라 뺀다.
            prog = [d for d in docs if 1 <= d["order"] <= 7]
            top = max(prog, key=lambda d: d["order"], default=None)
            if top is None:
                # 절차 문서가 하나도 없는 구역(용역 발주만 올라온 단지 등)은
                # 가장 최근 공고의 성격을 그대로 쓴다. '기타'로 뭉뚱그리면
                # 카드만 봐서는 무슨 구역인지 알 수 없다.
                top = max(docs, key=lambda d: d["date"] or "")
            zones.append({
                "key": key,
                "label": slot["label"],
                "count": len(docs),
                "stage": top["stage"],
                "order": top["order"],
                "first": min((d["date"] for d in docs if d["date"]), default=""),
                "last": max((d["date"] for d in docs if d["date"]), default=""),
                "docs": docs,
            })
        # 문서 많은 구역부터, '구역미상'은 맨 뒤로
        zones.sort(key=lambda z: (z["key"] == "_구역미상", -z["count"]))
        out[gu] = zones
    return out, skipped


def print_summary(tree, skipped):
    total_docs = sum(z["count"] for zs in tree.values() for z in zs)
    real = [z for zs in tree.values() for z in zs if z["key"] != "_구역미상"]
    print(f"서울 {len(tree)}개 구 · 구역 {len(real)}개 · 문서 {total_docs}건")
    print(f"제외: " + ", ".join(f"{k} {v}건" for k, v in skipped.items()))
    print()
    for gu, zones in tree.items():
        named = [z for z in zones if z["key"] != "_구역미상"]
        unknown = sum(z["count"] for z in zones if z["key"] == "_구역미상")
        print(f"── {gu}  구역 {len(named)}개 / 문서 {sum(z['count'] for z in zones)}건"
              f"{f' (구역미상 {unknown})' if unknown else ''}")
        for z in named[:6]:
            span = f"{z['first'][2:]}~{z['last'][2:]}" if z["first"] else "날짜없음"
            print(f"     {z['count']:2d}건  {z['label'][:34]:34s} {span}")
        if len(named) > 6:
            print(f"     … 외 {len(named) - 6}개 구역")


def print_markdown(tree):
    for gu, zones in tree.items():
        print(f"\n# {gu}\n")
        for z in zones:
            print(f"## {z['label']}  ({z['count']}건)\n")
            for d in z["docs"]:
                print(f"- `{d['date'] or '        '}` {d['title']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="마크다운 전문 출력")
    args = ap.parse_args()

    tree, skipped = build()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=1)

    if args.md:
        print_markdown(tree)
    else:
        print_summary(tree, skipped)
        print(f"\n{OUT_FILE} 저장 완료")


if __name__ == "__main__":
    main()
