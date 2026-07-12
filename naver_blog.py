import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

RESERVED_PATHS = {
    "postlist.naver", "postlist.nhn",
    "postview.naver", "postview.nhn",
    "prologuelist.naver",
}


def extract_blog_id(text):
    """네이버블로그 주소 또는 블로그 아이디 문자열에서 blogId를 추출한다."""
    text = text.strip()
    if "blog.naver.com" not in text:
        if re.fullmatch(r"[a-zA-Z0-9_-]+", text):
            return text
        return None

    parsed = urlparse(text if "://" in text else f"https://{text}")
    qs = parse_qs(parsed.query)
    if qs.get("blogId"):
        return qs["blogId"][0]

    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts and path_parts[0].lower() not in RESERVED_PATHS:
        return path_parts[0]
    return None


def parse_rss_date(date_str):
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def fetch_posts(blog_id, timeout=15):
    """블로그의 최신 글 목록을 최신순으로 반환한다. (채널명, 글 목록) 튜플."""
    rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
    response = requests.get(
        rss_url,
        headers={"User-Agent": USER_AGENT, "Referer": rss_url},
        timeout=timeout,
    )
    response.encoding = "utf-8"
    response.raise_for_status()

    root = ET.fromstring(response.text)
    channel_title = (root.findtext(".//channel/title") or blog_id).strip()

    posts = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        posts.append({
            "title": title,
            "link": link,
            "pub_date": parse_rss_date((item.findtext("pubDate") or "").strip()),
        })

    return channel_title, posts
