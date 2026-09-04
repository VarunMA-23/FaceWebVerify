"""SQLite models (Job, DiscoveredPost, BlockchainRecord).

Uses plain sqlite3 with a thin repository layer — sufficient for the MVP.
The database file lives in the project root as ``pipeline.db`` (overridable
via the ``PIPELINE_DB`` environment variable).
"""

from __future__ import annotations

import json
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
    evidence_id TEXT,
    record_type TEXT NOT NULL DEFAULT 'content_registration',
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
"""

_MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN metadata_json TEXT DEFAULT ''",
    "ALTER TABLE discovered_posts ADD COLUMN source_type TEXT DEFAULT ''",
    "ALTER TABLE discovered_posts ADD COLUMN domain TEXT DEFAULT ''",
    "ALTER TABLE discovered_posts ADD COLUMN evidence_score INTEGER DEFAULT 0",
    "ALTER TABLE discovered_posts ADD COLUMN provider_count INTEGER DEFAULT 0",
    "ALTER TABLE discovered_posts ADD COLUMN providers_json TEXT DEFAULT ''",
    "ALTER TABLE discovered_posts ADD COLUMN explanation_json TEXT DEFAULT ''",
    "ALTER TABLE discovered_posts ADD COLUMN metadata_json TEXT DEFAULT ''",
    "ALTER TABLE blockchain_records ADD COLUMN evidence_id TEXT",
    "ALTER TABLE blockchain_records ADD COLUMN record_type TEXT NOT NULL DEFAULT 'content_registration'",
]


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
            for stmt in _MIGRATIONS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column already exists

    def update_job_metadata(self, job_id: str, metadata: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET metadata_json=? WHERE job_id=?",
                (json.dumps(metadata), job_id),
            )

    def get_job_metadata(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        if not job:
            return {}
        raw = job.get("metadata_json") or ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

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
        *,
        source_type: str = "",
        domain: str = "",
        evidence_score: int = 0,
        provider_count: int = 0,
        providers: list | None = None,
        explanation: list | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO discovered_posts "
                "(job_id, post_url, image_url, platform, caption, title, "
                "face_similarity, evidence_tier, source_type, domain, evidence_score, "
                "provider_count, providers_json, explanation_json, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    post_url,
                    image_url,
                    platform,
                    caption,
                    title,
                    face_similarity,
                    evidence_tier,
                    source_type,
                    domain,
                    evidence_score,
                    provider_count,
                    json.dumps(providers or []),
                    json.dumps(explanation or []),
                    json.dumps(metadata or {}),
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
        evidence_id: str | None = None,
        record_type: str = "content_registration",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO blockchain_records "
                "(job_id, content_hash, transaction_hash, block_number, registered_at, "
                "evidence_id, record_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    content_hash,
                    transaction_hash,
                    block_number,
                    _now(),
                    evidence_id,
                    record_type,
                ),
            )

    def get_blockchain_record(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM blockchain_records "
                "WHERE job_id=? AND record_type='content_registration' "
                "ORDER BY id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_evidence_attestation_record(
        self,
        job_id: str,
        evidence_id: str | None = None,
    ) -> dict | None:
        query = (
            "SELECT * FROM blockchain_records "
            "WHERE job_id=? AND record_type='evidence_attestation'"
        )
        params: list[str] = [job_id]
        if evidence_id is not None:
            query += " AND evidence_id=?"
            params.append(evidence_id)
        query += " ORDER BY id DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_evidence_revocation_record(
        self,
        job_id: str,
        evidence_id: str | None = None,
    ) -> dict | None:
        query = (
            "SELECT * FROM blockchain_records "
            "WHERE job_id=? AND record_type='evidence_revocation'"
        )
        params: list[str] = [job_id]
        if evidence_id is not None:
            query += " AND evidence_id=?"
            params.append(evidence_id)
        query += " ORDER BY id DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
