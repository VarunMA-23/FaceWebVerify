"""SQLite models (Job, DiscoveredPost, BlockchainRecord).

Uses plain sqlite3 with a thin repository layer — sufficient for the MVP.
The database file lives in the project root as ``pipeline.db`` (overridable
via the ``PIPELINE_DB`` environment variable).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import dotenv

dotenv.load_dotenv()

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline.db",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    input_image_path TEXT,
    created_at TIMESTAMP,
    status TEXT
);

CREATE TABLE IF NOT EXISTS discovered_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    post_url TEXT,
    image_url TEXT,
    platform TEXT,
    caption TEXT,
    title TEXT,
    face_similarity FLOAT,
    evidence_tier TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS blockchain_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    content_hash TEXT,
    transaction_hash TEXT,
    block_number INTEGER,
    registered_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thin sqlite3 wrapper exposing the schema and repository helpers."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("PIPELINE_DB") or DEFAULT_DB
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------- jobs
    def create_job(self, job_id: str, image_path: str, status: str = "processing") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs (job_id, input_image_path, created_at, status) "
                "VALUES (?, ?, ?, ?)",
                (job_id, image_path, _now(), status),
            )

    def update_job_status(self, job_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))

    def get_job(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------- posts
    def add_post(
        self,
        job_id: str,
        post_url: str,
        image_url: str,
        platform: str,
        caption: str,
        title: str,
        face_similarity: float,
        evidence_tier: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO discovered_posts "
                "(job_id, post_url, image_url, platform, caption, title, "
                "face_similarity, evidence_tier) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    post_url,
                    image_url,
                    platform,
                    caption,
                    title,
                    face_similarity,
                    evidence_tier,
                ),
            )

    def get_posts(self, job_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM discovered_posts WHERE job_id=? ORDER BY face_similarity DESC",
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------- blockchain
    def add_blockchain_record(
        self,
        job_id: str,
        content_hash: str,
        transaction_hash: str,
        block_number: int | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO blockchain_records "
                "(job_id, content_hash, transaction_hash, block_number, registered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, content_hash, transaction_hash, block_number, _now()),
            )

    def get_blockchain_record(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM blockchain_records WHERE job_id=? ORDER BY id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None
