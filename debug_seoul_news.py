"""임시 진단 3단계: 새로 등록한 '서울시 보도자료' 게시판이 실제 파서로 잘 읽히는지 확인.

알림은 보내지 않고 seen 파일도 건드리지 않는다.
"""

from check_boards import load_boards, scrape_board

for board in load_boards():
    if board["name"] != "서울시 보도자료":
        continue
    posts = scrape_board(board["url"], board["keywords"], board["row_keywords"], board["name"])
    print(f"\n필터 통과 {len(posts)}건")
    for p in posts:
        print(f"  - ({p['date']}) {p['title'][:70]}")
        print(f"    {p['link']}")
