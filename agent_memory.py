"""Lightweight semantic memory with an optional PostgreSQL/pgvector backend.

The local SQLite backend keeps the desktop application dependency-free.  Docker
deployments can set DATABASE_URL to use PostgreSQL; embeddings are deterministic
hash vectors so no second model/API key is required.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from time_utils import app_now


ROOT = Path(__file__).resolve().parent
LOCAL_DB = ROOT / "data" / "agent_memory.db"
VECTOR_SIZE = 96


def embed(text: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        vector[index] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _postgres_vector(values: list[float]) -> str:
    """Serialize a vector explicitly so psycopg never infers float8[]."""
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"


class SemanticMemory:
    """Stores sanitized summaries and retrieves the nearest historical context."""

    def __init__(self) -> None:
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        if self.database_url:
            import psycopg
            from pgvector.psycopg import register_vector

            self.connection = psycopg.connect(self.database_url)
            self.connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(self.connection)
            self.connection.execute(
                f"""CREATE TABLE IF NOT EXISTS memories (
                id BIGSERIAL PRIMARY KEY, message_key TEXT UNIQUE, content TEXT NOT NULL,
                metadata JSONB NOT NULL, embedding VECTOR({VECTOR_SIZE}) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
            )
            self.connection.commit()
            return
        LOCAL_DB.parent.mkdir(exist_ok=True)
        self.connection = sqlite3.connect(LOCAL_DB)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_key TEXT UNIQUE,
            content TEXT NOT NULL,
            metadata TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def remember(self, message_key: str, content: str, metadata: dict[str, str]) -> None:
        if self.database_url:
            self.connection.execute(
                """INSERT INTO memories(message_key, content, metadata, embedding) VALUES (%s, %s, %s, %s::vector)
                ON CONFLICT(message_key) DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata,
                embedding=EXCLUDED.embedding, created_at=NOW()""",
                (message_key, content[:2000], json.dumps(metadata, ensure_ascii=False), _postgres_vector(embed(content))),
            )
            self.connection.commit()
            return
        self.connection.execute(
            "INSERT OR REPLACE INTO memories(message_key, content, metadata, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
            (message_key, content[:2000], json.dumps(metadata, ensure_ascii=False), json.dumps(embed(content)), app_now().isoformat()),
        )
        self.connection.commit()

    def search(self, query: str, limit: int = 3) -> list[dict[str, object]]:
        query_vector = embed(query)
        if self.database_url:
            vector = _postgres_vector(query_vector)
            rows = self.connection.execute(
                "SELECT content, metadata, 1 - (embedding <=> %s::vector) AS score FROM memories ORDER BY embedding <=> %s::vector LIMIT %s",
                (vector, vector, limit),
            ).fetchall()
            return [{"content": row[0], "metadata": row[1], "score": round(float(row[2]), 4)} for row in rows]
        rows = self.connection.execute(
            "SELECT content, metadata, embedding FROM memories ORDER BY id DESC LIMIT 500"
        ).fetchall()
        ranked = sorted(
            (
                {
                    "content": content,
                    "metadata": json.loads(metadata),
                    "score": round(cosine(query_vector, json.loads(vector)), 4),
                }
                for content, metadata, vector in rows
            ),
            key=lambda item: item["score"],
            reverse=True,
        )
        return [item for item in ranked[:limit] if item["score"] > 0]

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SemanticMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
