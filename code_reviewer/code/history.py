"""Small SQLite-backed review history store."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from pathlib import Path
from typing import Any


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            filename TEXT NOT NULL,
            mode TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            proposal_hash TEXT,
            status TEXT NOT NULL,
            score INTEGER,
            approved INTEGER NOT NULL DEFAULT 0,
            findings_json TEXT NOT NULL,
            coverage_score REAL
        )"""
    )
    try:
        connection.execute("ALTER TABLE reviews ADD COLUMN coverage_score REAL")
    except sqlite3.OperationalError:
        pass
    connection.commit()
    return connection


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def save_review(path: str | Path, record: dict[str, Any]) -> int:
    connection = _connect(path)
    try:
        cursor = connection.execute(
            """INSERT INTO reviews
            (filename, mode, source_hash, proposal_hash, status, score, approved, findings_json, coverage_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("filename", "code.py"),
                record.get("mode", "review"),
                record.get("source_hash") or source_hash(record.get("source", "")),
                record.get("proposal_hash"),
                record.get("status", "unknown"),
                record.get("score"),
                int(bool(record.get("approved", False))),
                json.dumps(record.get("findings", [])),
                record.get("coverage_score"),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def list_reviews(path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    connection = _connect(path)
    try:
        rows = connection.execute(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def delete_review(path: str | Path, review_id: int) -> None:
    connection = _connect(path)
    try:
        connection.execute("DELETE FROM reviews WHERE id = ?", (int(review_id),))
        connection.commit()
    finally:
        connection.close()


def clear_history(path: str | Path) -> None:
    connection = _connect(path)
    try:
        connection.execute("DELETE FROM reviews")
        connection.commit()
    finally:
        connection.close()
