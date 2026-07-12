import sqlite3
from contextlib import closing

DB_PATH = "subscriptions.db"


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
            "SELECT chat_id, blog_id, blog_name, last_link FROM subscriptions"
        ).fetchall()
        return [
            {"chat_id": r[0], "blog_id": r[1], "blog_name": r[2], "last_link": r[3]}
            for r in rows
        ]


def update_last_link(chat_id, blog_id, last_link, db_path=DB_PATH):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE subscriptions SET last_link = ? WHERE chat_id = ? AND blog_id = ?",
            (last_link, chat_id, blog_id),
        )
        conn.commit()
