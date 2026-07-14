import sqlite3
from contextlib import closing

DB_PATH = "subscriptions.db"


SEEN_LINKS_KEEP = 200  # 구독별로 보관할 확인한 글 링크 수


def init_db(db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                chat_id INTEGER NOT NULL,
                blog_id TEXT NOT NULL,
                blog_name TEXT,
                last_link TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, blog_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_posts (
                chat_id INTEGER NOT NULL,
                blog_id TEXT NOT NULL,
                link TEXT NOT NULL,
                PRIMARY KEY (chat_id, blog_id, link)
            )
            """
        )
        conn.commit()


def add_subscription(chat_id, blog_id, blog_name, db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions (chat_id, blog_id, blog_name) VALUES (?, ?, ?)",
            (chat_id, blog_id, blog_name),
        )
        conn.commit()


def remove_subscription(chat_id, blog_id, db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id = ? AND blog_id = ?",
            (chat_id, blog_id),
        )
        conn.execute(
            "DELETE FROM seen_posts WHERE chat_id = ? AND blog_id = ?",
            (chat_id, blog_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_subscriptions(chat_id, db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT blog_id, blog_name FROM subscriptions WHERE chat_id = ? ORDER BY created_at",
            (chat_id,),
        ).fetchall()
        return [{"blog_id": r[0], "blog_name": r[1]} for r in rows]


def all_subscriptions(db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT chat_id, blog_id, blog_name FROM subscriptions"
        ).fetchall()
        return [{"chat_id": r[0], "blog_id": r[1], "blog_name": r[2]} for r in rows]


def get_seen_links(chat_id, blog_id, db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT link FROM seen_posts WHERE chat_id = ? AND blog_id = ?",
            (chat_id, blog_id),
        ).fetchall()
        return {r[0] for r in rows}


def mark_seen(chat_id, blog_id, links, db_path=DB_PATH):
    """링크들을 확인한 글로 기록하고, 오래된 기록은 정리한다."""
    if not links:
        return
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_posts (chat_id, blog_id, link) VALUES (?, ?, ?)",
            [(chat_id, blog_id, link) for link in links],
        )
        conn.execute(
            """
            DELETE FROM seen_posts
            WHERE chat_id = ? AND blog_id = ? AND rowid NOT IN (
                SELECT rowid FROM seen_posts
                WHERE chat_id = ? AND blog_id = ?
                ORDER BY rowid DESC LIMIT ?
            )
            """,
            (chat_id, blog_id, chat_id, blog_id, SEEN_LINKS_KEEP),
        )
        conn.commit()
