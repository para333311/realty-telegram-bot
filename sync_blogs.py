"""네이버 '내 이웃 목록'을 blogs.txt에 그대로 반영한다.

네이버에서 이웃을 추가/삭제하면 blogs.txt를 손으로 고칠 필요 없이 이 스크립트가
따라간다. 이웃이 아닌데 알림을 받고 싶은 블로그는 blogs.txt의 '직접 추가' 구역에
적어두면 동기화가 건드리지 않는다.

쓰는 API (2026-09-17 확인, 로그인 불필요):
  GET https://m.blog.naver.com/api/blogs/{blogId}/public-buddies?pageNo=N
  -> {"isSuccess": true, "result": {"totalPublicBuddyCount": 180,
      "totalPageCount": 4, "currentPage": 1, "buddyList": [{"blogId": ...}]}}
  한 페이지 50명. m.blog 이웃목록 화면이 스크롤할 때 쓰는 것과 같은 경로다.

필요한 환경변수:
- MY_BLOG_ID: 이웃 목록을 읽어올 내 블로그 아이디
- TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: 증감 보고 (없으면 로그만 남긴다)
- SYNC_FORCE=1: 대량 삭제 안전장치를 무시하고 강행
"""

import logging
import os
import sys

import requests

import naver_blog
from check_once import BLOGS_FILE, send_message

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

API = "https://m.blog.naver.com/api/blogs/{blog_id}/public-buddies"
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
MAX_PAGES = 60  # 페이지당 50명 = 3,000명. 이웃 상한(5,000)에 못 미치지만 무한루프 방지용

MANUAL_MARKER = "# === 직접 추가 (동기화가 건드리지 않습니다) ==="
AUTO_MARKER = "# === 네이버 이웃 자동 동기화 (여기는 통째로 다시 씁니다) ==="

HEADER = f"""# 새 글 알림을 받을 네이버 블로그 목록.
#
# 아래 두 구역으로 나뉜다:
#   · '직접 추가'  - 손으로 적는 곳. 이웃이 아니어도 알림을 받고 싶은 블로그.
#                    블로그 주소를 통째로 붙여넣어도 되고 아이디만 적어도 된다.
#   · '자동 동기화' - sync_blogs.py가 네이버 이웃 목록을 그대로 옮겨 적는 곳.
#                    여기를 손으로 고쳐봐야 다음 동기화 때 덮어쓰인다.
#                    네이버에서 이웃을 추가/삭제하면 알아서 따라온다.
#
# ('#'으로 시작하는 줄은 무시된다)

{MANUAL_MARKER}
"""

# 한 번에 이만큼 넘게 지워야 하면 네이버 응답이 이상한 것으로 보고 멈춘다.
# (이웃 목록이 부분적으로만 내려오는 장애를 blogs.txt 대량 삭제로 굳히지 않으려는 방어)
REMOVE_ABORT_MIN = 10
REMOVE_ABORT_RATIO = 0.1


def fetch_buddies(blog_id):
    """이웃 목록 전체를 [(아이디, 표시이름)] 로 반환한다. 순서는 네이버가 준 그대로."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": f"https://m.blog.naver.com/BuddyList.naver?blogId={blog_id}",
            "Accept": "application/json, text/plain, */*",
        }
    )

    buddies = []
    seen = set()
    total_count = None
    page = 1
    while page <= MAX_PAGES:
        response = session.get(API.format(blog_id=blog_id), params={"pageNo": page}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("isSuccess"):
            raise RuntimeError(f"이웃 목록 조회 실패: {payload.get('error')}")

        result = payload.get("result") or {}
        if total_count is None:
            total_count = result.get("totalPublicBuddyCount")
        total_pages = result.get("totalPageCount") or 1

        for item in result.get("buddyList") or []:
            blog = item.get("blogId")
            if blog and blog not in seen:
                seen.add(blog)
                buddies.append((blog, item.get("blogName") or item.get("nickName") or blog))

        if page >= total_pages:
            break
        page += 1

    return buddies, total_count


def parse_blogs_file(path, buddy_ids):
    """blogs.txt를 (직접 추가 줄, 자동 구역 아이디)로 나눈다.

    구분선이 아직 없는 예전 형식이면, 지금 이웃이 아닌 아이디를 '직접 추가'로 본다.
    (지금까지 손으로 관리해온 것들을 동기화가 지워버리지 않게 하려는 것)
    """
    if not os.path.exists(path):
        return [], []

    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f]

    if AUTO_MARKER in lines:
        split_at = lines.index(AUTO_MARKER)
        manual_lines, auto_lines = lines[:split_at], lines[split_at + 1 :]
    else:
        manual_lines, auto_lines = lines, []

    manual_ids = []
    for line in manual_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        blog_id = naver_blog.extract_blog_id(line)
        if blog_id and blog_id not in manual_ids:
            manual_ids.append(blog_id)

    auto_ids = []
    for line in auto_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        blog_id = naver_blog.extract_blog_id(line)
        if blog_id and blog_id not in auto_ids:
            auto_ids.append(blog_id)

    if AUTO_MARKER not in lines:
        # 예전 형식: 이웃인 것들은 자동 구역으로 넘기고, 나머지만 직접 추가로 남긴다.
        auto_ids = [b for b in manual_ids if b in buddy_ids]
        manual_ids = [b for b in manual_ids if b not in buddy_ids]

    return manual_ids, auto_ids


def write_blogs_file(path, manual_ids, buddies):
    lines = [HEADER]
    lines += [f"{blog_id}\n" for blog_id in manual_ids]
    lines.append(f"\n{AUTO_MARKER}\n")
    lines += [f"{blog_id}\n" for blog_id, _ in buddies]
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def notify(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("텔레그램 설정이 없어 알림을 건너뜁니다:\n%s", text)
        return
    send_message(token, chat_id, text, disable_preview=True)


def main():
    blog_id = os.environ.get("MY_BLOG_ID")
    if not blog_id:
        logger.error("MY_BLOG_ID가 없습니다.")
        return 1

    try:
        buddies, total_count = fetch_buddies(blog_id)
    except Exception as e:
        logger.error("이웃 목록을 가져오지 못했습니다: %s", e)
        notify(f"⚠️ 네이버 이웃 목록 동기화 실패\n{type(e).__name__}: {e}\nblogs.txt는 그대로 둡니다.")
        return 1

    if not buddies:
        logger.error("이웃 목록이 비어 있습니다. blogs.txt를 건드리지 않습니다.")
        notify("⚠️ 네이버 이웃 목록이 비어서 왔습니다.\nblogs.txt는 그대로 둡니다.")
        return 1

    if total_count is not None and len(buddies) != total_count:
        logger.error("이웃 %d명 중 %d명만 받았습니다.", total_count, len(buddies))
        notify(
            f"⚠️ 네이버 이웃 {total_count}명 중 {len(buddies)}명만 받아왔습니다.\n"
            "일부만 반영하면 나머지가 지워지므로 blogs.txt는 그대로 둡니다."
        )
        return 1

    names = dict(buddies)
    buddy_ids = [blog for blog, _ in buddies]
    manual_ids, previous_auto = parse_blogs_file(BLOGS_FILE, set(buddy_ids))

    added = [b for b in buddy_ids if b not in previous_auto]
    removed = [b for b in previous_auto if b not in buddy_ids]

    limit = max(REMOVE_ABORT_MIN, int(len(previous_auto) * REMOVE_ABORT_RATIO))
    if removed and len(removed) > limit and not os.environ.get("SYNC_FORCE"):
        logger.error("한 번에 %d개를 지우려 해서 멈춥니다(상한 %d).", len(removed), limit)
        notify(
            f"⚠️ 이웃 동기화가 한 번에 {len(removed)}개를 지우려 해서 멈췄습니다 (상한 {limit}개).\n"
            f"네이버 이웃: {len(buddy_ids)}명 / blogs.txt 자동 구역: {len(previous_auto)}개\n"
            "정말 맞다면 Actions에서 '네이버 이웃 목록 동기화'를 강행 옵션으로 다시 돌려주세요."
        )
        return 1

    write_blogs_file(BLOGS_FILE, manual_ids, buddies)

    # 변동이 없어도 매일 한 줄은 보낸다. 내가 네이버에서 추가·삭제한 것이
    # 반영됐는지, 동기화가 살아는 있는지를 이 메시지 하나로 확인하려는 것이다.
    delta = " ".join(p for p in (f"+{len(added)}" if added else "",
                                 f"-{len(removed)}" if removed else "") if p)
    lines = [f"📋 네이버 이웃 {len(buddy_ids)}명 ({delta or '변동 없음'})"]
    lines.append(f"직접 추가 {len(manual_ids)}개 · 알림 대상 {len(buddy_ids) + len(manual_ids)}개")
    if added:
        lines.append("")
        lines += [f"➕ {names.get(b, b)} ({b})" for b in added[:20]]
        if len(added) > 20:
            lines.append(f"… 외 {len(added) - 20}개")
    if removed:
        lines.append("")
        lines += [f"➖ {b}" for b in removed[:20]]
        if len(removed) > 20:
            lines.append(f"… 외 {len(removed) - 20}개")
    notify("\n".join(lines))
    logger.info("동기화 완료: +%d / -%d", len(added), len(removed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
