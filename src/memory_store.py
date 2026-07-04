"""赫湦公開社群的本機記憶庫。

只記錄已成功發布的內容；未發布候選與 Render 自動回覆不寫入本庫。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Final


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
DB_PATH: Final = PROJECT_ROOT / "data" / "hexing_memory.sqlite3"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS published_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            threads_post_id TEXT NOT NULL UNIQUE,
            post_type TEXT NOT NULL,
            text TEXT NOT NULL,
            topic_tag TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            published_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approved_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            threads_reply_id TEXT NOT NULL UNIQUE,
            in_reply_to_id TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            comment_text TEXT NOT NULL DEFAULT '',
            post_text TEXT NOT NULL DEFAULT '',
            conversation_text TEXT NOT NULL DEFAULT '',
            reply_text TEXT NOT NULL,
            source TEXT NOT NULL,
            published_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_posts_published_at
            ON published_posts(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_replies_published_at
            ON approved_replies(published_at DESC);
        """
    )
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_published_post(
    threads_post_id: str,
    text: str,
    post_type: str,
    topic_tag: str = "",
    source: str = "manual_command",
) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO published_posts
               (threads_post_id, post_type, text, topic_tag, source, published_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (threads_post_id, post_type, text.strip(), topic_tag.strip(), source, _now()),
        )


def record_approved_reply(
    threads_reply_id: str,
    in_reply_to_id: str,
    reply_text: str,
    *,
    author: str = "",
    comment_text: str = "",
    post_text: str = "",
    conversation_text: str = "",
    source: str = "human_approved",
) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO approved_replies
               (threads_reply_id, in_reply_to_id, author, comment_text, post_text,
                conversation_text, reply_text, source, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                threads_reply_id, in_reply_to_id, author.strip(), comment_text.strip(),
                post_text.strip(), conversation_text.strip(), reply_text.strip(), source, _now(),
            ),
        )


def recent_approved_reply_examples(limit: int = 8) -> str:
    """只提供人工核准回覆作為語氣校準，不將網友留言視為人物事實。"""
    safe_limit = max(1, min(limit, 20))
    with _connect() as connection:
        rows = connection.execute(
            """SELECT comment_text, reply_text FROM approved_replies
               WHERE comment_text <> '' AND reply_text <> ''
               ORDER BY published_at DESC LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    if not rows:
        return "（尚無人工核准的歷史回覆）"
    return "\n".join(
        f"- 留言：{row['comment_text'][:180]}\n  赫湦回覆：{row['reply_text'][:120]}"
        for row in reversed(rows)
    )
