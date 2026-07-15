"""(임시) scrape_commission 실사이트 검증 + 10개 위원회명 확인. 조사 후 삭제."""

import check_boards as cb

CODES = ["CM01", "CM02", "CM03", "CM05", "CM07", "CM08", "CM09", "CM10", "CM11", "CM12"]
for code in CODES:
    url = f"https://commission.eseoul.go.kr/cmitInfo/cmitSchdulList.do?cmitId={code}"
    try:
        posts = cb.scrape_commission(url, [], [], code)
        top = posts[0]["title"] if posts else "(없음)"
        print(f"  {code}: {len(posts)}건 | 최신: {top[:60]} | 날짜 {posts[0]['date'] if posts else '-'}")
    except Exception as e:
        print(f"  {code}: ERROR {e}")
print("끝")
