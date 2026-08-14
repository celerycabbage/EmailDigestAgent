"""Semantic memory with real embeddings, hybrid retrieval, and pgvector support."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from runtime_config import refresh_runtime_config
from time_utils import app_now


ROOT = Path(__file__).resolve().parent
LOCAL_DB = ROOT / "data" / "agent_memory.db"
VECTOR_SIZE = 96
LOCAL_MODEL = "local-hash-v1"
VALID_STRATEGIES = {"none", "vector", "hybrid"}


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", lowered)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.extend(chinese[index:index + 2] for index in range(max(len(chinese) - 1, 0)))
    return [word for word in words if word]


def embed(text: str) -> list[float]:
    """Dependency-free fallback embedding retained for offline operation."""
    vector = [0.0] * VECTOR_SIZE
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        vector[index] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    return sum(a * b for a, b in zip(left, right))


def _postgres_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"


class EmbeddingService:
    """OpenAI-compatible embeddings with an explicit local fallback."""

    def __init__(self) -> None:
        refresh_runtime_config(ROOT / ".env")
        self.model = os.getenv("EMBEDDING_MODEL_ID", "").strip()
        self.api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        self.base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
        self.fallback = os.getenv("EMBEDDING_FALLBACK_TO_LOCAL", "true").lower() not in {"0", "false", "no"}
        self.last_backend = "remote" if self.configured else "local"
        self.last_model = self.model if self.configured else LOCAL_MODEL
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.model and self.api_key and self.base_url)

    def create(self, text: str) -> tuple[list[float], str]:
        if self.configured:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30, max_retries=1)
                response = client.embeddings.create(model=self.model, input=[text[:8000]])
                self.last_backend = "remote"
                self.last_model = self.model
                self.last_error = ""
                return list(response.data[0].embedding), self.model
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {str(error)[:160]}"
                if not self.fallback:
                    raise RuntimeError(f"Embedding 服务调用失败：{self.last_error}") from error
        self.last_backend = "local"
        self.last_model = LOCAL_MODEL
        return embed(text), LOCAL_MODEL

    def status(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "backend": self.last_backend,
            "model": self.last_model,
            "fallback_enabled": self.fallback,
            "last_error": self.last_error,
        }


def _keyword_scores(query: str, documents: list[str]) -> list[float]:
    """Small BM25 implementation for local and PostgreSQL hybrid retrieval."""
    query_terms = _tokens(query)
    tokenized = [_tokens(document) for document in documents]
    if not query_terms or not tokenized:
        return [0.0] * len(documents)
    average_length = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    document_frequency = Counter(term for term in set(query_terms) for tokens in tokenized if term in tokens)
    scores: list[float] = []
    for tokens in tokenized:
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            if not frequency:
                continue
            inverse = math.log(1 + (len(tokenized) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(average_length, 1))
            score += inverse * frequency * 2.5 / denominator
        scores.append(score)
    return scores


def _rrf(vector_order: list[int], keyword_order: list[int]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for weight, order in ((0.65, vector_order), (0.35, keyword_order)):
        for rank, index in enumerate(order, start=1):
            scores[index] = scores.get(index, 0.0) + weight / (60 + rank)
    return scores


class SemanticMemory:
    """Stores sanitized summaries and retrieves relevant historical context."""

    def __init__(
        self, database_url: str | None = None, local_db: Path | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.database_url = os.getenv("DATABASE_URL", "").strip() if database_url is None else database_url
        self.local_db = local_db or LOCAL_DB
        self.embedding_service = embedding_service or EmbeddingService()
        if self.database_url:
            import psycopg

            self.connection = psycopg.connect(self.database_url)
            self.connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS agent_memories (
                id BIGSERIAL PRIMARY KEY, message_key TEXT UNIQUE, content TEXT NOT NULL,
                metadata JSONB NOT NULL, embedding VECTOR NOT NULL, embedding_model TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
            )
            legacy_exists = self.connection.execute("SELECT to_regclass('public.memories')").fetchone()[0]
            if legacy_exists:
                self.connection.execute(
                    """INSERT INTO agent_memories(message_key, content, metadata, embedding, embedding_model, created_at)
                    SELECT message_key, content, metadata, embedding, %s, created_at FROM memories
                    ON CONFLICT(message_key) DO NOTHING""",
                    (LOCAL_MODEL,),
                )
            self.connection.commit()
            return
        self.local_db.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.local_db)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message_key TEXT UNIQUE, content TEXT NOT NULL,
            metadata TEXT NOT NULL, embedding TEXT NOT NULL, embedding_model TEXT NOT NULL,
            created_at TEXT NOT NULL)"""
        )
        legacy_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        if legacy_exists:
            self.connection.execute(
                """INSERT OR IGNORE INTO agent_memories
                (message_key, content, metadata, embedding, embedding_model, created_at)
                SELECT message_key, content, metadata, embedding, ?, created_at FROM memories""",
                (LOCAL_MODEL,),
            )
        self.connection.commit()

    def remember(self, message_key: str, content: str, metadata: dict[str, str]) -> None:
        vector, model = self.embedding_service.create(content)
        if self.database_url:
            self.connection.execute(
                """INSERT INTO agent_memories(message_key, content, metadata, embedding, embedding_model)
                VALUES (%s, %s, %s, %s::vector, %s)
                ON CONFLICT(message_key) DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata,
                embedding=EXCLUDED.embedding, embedding_model=EXCLUDED.embedding_model, created_at=NOW()""",
                (message_key, content[:2000], json.dumps(metadata, ensure_ascii=False), _postgres_vector(vector), model),
            )
            self.connection.commit()
            return
        self.connection.execute(
            """INSERT OR REPLACE INTO agent_memories
            (message_key, content, metadata, embedding, embedding_model, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (message_key, content[:2000], json.dumps(metadata, ensure_ascii=False), json.dumps(vector), model, app_now().isoformat()),
        )
        self.connection.commit()

    def _rows(self, model: str, limit: int = 500) -> list[tuple[Any, ...]]:
        if self.database_url:
            return self.connection.execute(
                "SELECT message_key, content, metadata, embedding::text, embedding_model FROM agent_memories WHERE embedding_model=%s ORDER BY id DESC LIMIT %s",
                (model, limit),
            ).fetchall()
        return self.connection.execute(
            "SELECT message_key, content, metadata, embedding, embedding_model FROM agent_memories WHERE embedding_model=? ORDER BY id DESC LIMIT ?",
            (model, limit),
        ).fetchall()

    def search(self, query: str, limit: int = 3, strategy: str = "hybrid") -> list[dict[str, object]]:
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"无效的 RAG 检索策略：{strategy}")
        if strategy == "none":
            return []
        query_vector, model = self.embedding_service.create(query)
        rows = self._rows(model)
        if not rows:
            return []
        documents = [str(row[1]) for row in rows]
        vectors = [json.loads(row[3]) if isinstance(row[3], str) else list(row[3]) for row in rows]
        vector_scores = [cosine(query_vector, vector) for vector in vectors]
        vector_order = sorted(range(len(rows)), key=lambda index: vector_scores[index], reverse=True)
        if self.database_url:
            vector = _postgres_vector(query_vector)
            database_ranking = self.connection.execute(
                """SELECT message_key, 1 - (embedding <=> %s::vector) AS score
                FROM agent_memories WHERE embedding_model=%s
                ORDER BY embedding <=> %s::vector LIMIT 500""",
                (vector, model, vector),
            ).fetchall()
            index_by_key = {str(row[0]): index for index, row in enumerate(rows)}
            vector_order = [index_by_key[str(row[0])] for row in database_ranking if str(row[0]) in index_by_key]
            score_by_key = {str(row[0]): float(row[1]) for row in database_ranking}
            vector_scores = [score_by_key.get(str(row[0]), -1.0) for row in rows]
        keyword_scores = _keyword_scores(query, documents)
        keyword_order = sorted(range(len(rows)), key=lambda index: keyword_scores[index], reverse=True)
        if strategy == "vector":
            combined = {index: vector_scores[index] for index in vector_order}
        else:
            combined = _rrf(vector_order, keyword_order)
        ranked = sorted(combined, key=combined.get, reverse=True)
        results: list[dict[str, object]] = []
        for index in ranked[:limit]:
            metadata = rows[index][2] if isinstance(rows[index][2], dict) else json.loads(rows[index][2])
            results.append({
                "content": documents[index], "metadata": metadata,
                "score": round(float(combined[index]), 6), "vector_score": round(vector_scores[index], 4),
                "keyword_score": round(keyword_scores[index], 4), "strategy": strategy, "embedding_model": model,
            })
        return results

    def count(self) -> int:
        table = "agent_memories"
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def reindex(self, limit: int = 5000) -> dict[str, object]:
        """Re-embed existing sanitized memories after changing embedding models."""
        if self.database_url:
            rows = self.connection.execute(
                "SELECT message_key, content FROM agent_memories ORDER BY id DESC LIMIT %s", (limit,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT message_key, content FROM agent_memories ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        updated = 0
        for message_key, content in rows:
            vector, model = self.embedding_service.create(str(content))
            if self.database_url:
                self.connection.execute(
                    "UPDATE agent_memories SET embedding=%s::vector, embedding_model=%s WHERE message_key=%s",
                    (_postgres_vector(vector), model, message_key),
                )
            else:
                self.connection.execute(
                    "UPDATE agent_memories SET embedding=?, embedding_model=? WHERE message_key=?",
                    (json.dumps(vector), model, message_key),
                )
            updated += 1
        self.connection.commit()
        return {"updated": updated, **self.embedding_service.status()}

    def status(self) -> dict[str, object]:
        return {"storage": "pgvector" if self.database_url else "sqlite", **self.embedding_service.status(), "count": self.count()}

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SemanticMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
