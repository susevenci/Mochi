"""记忆服务（S6）：会话、消息、长期记忆、画像、摘要与提醒的统一入口。"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from app.memory.extractor import MemoryCandidate, extract_rules, extract_with_llm, keywords_for
from app.memory.summarizer import summarize
from app.memory.tokens import count_tokens
from app.store.db import Database
from app.utils.ids import ulid

log = logging.getLogger(__name__)

DEFAULT_TITLE = "默认会话"
DEFAULT_SESSION_HISTORY = 20
SUMMARY_TRIGGER_MESSAGES = 30
SUMMARY_KEEP_MESSAGES = 20


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int = 0
    summary: str = ""


class MemoryService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._current_session: str | None = None
        self._background: set[asyncio.Task[None]] = set()

    @property
    def db(self) -> Database:
        return self._db

    @property
    def current_session(self) -> str:
        if self._current_session is None:
            raise RuntimeError("MemoryService not started")
        return self._current_session

    async def start(self) -> None:
        await self._db.start()
        row = await self._db.fetchone(
            "SELECT id FROM sessions WHERE archived=0 ORDER BY updated_at DESC LIMIT 1"
        )
        if row:
            self._current_session = str(row[0])
        else:
            self._current_session = await self.create_session(DEFAULT_TITLE)
        log.info("memory ready session=%s", self._current_session)

    async def stop(self) -> None:
        for task in list(self._background):
            task.cancel()
        await self._db.stop()

    # ── 会话 ──────────────────────────────────────────────────────────
    async def create_session(self, title: str | None = None) -> str:
        now = time.time()
        session_id = ulid()
        await self._db.execute(
            "INSERT INTO sessions(id,title,created_at,updated_at) VALUES (?,?,?,?)",
            (session_id, title or f"会话 {time.strftime('%m-%d %H:%M')}", now, now),
        )
        self._current_session = session_id
        return session_id

    async def list_sessions(self) -> list[SessionInfo]:
        rows = await self._db.fetchall(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, s.summary,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS cnt
            FROM sessions s WHERE s.archived=0 ORDER BY s.updated_at DESC LIMIT 50
            """
        )
        return [
            SessionInfo(
                id=str(row[0]),
                title=str(row[1]),
                created_at=float(row[2]),
                updated_at=float(row[3]),
                summary=str(row[4] or ""),
                message_count=int(row[5] or 0),
            )
            for row in rows
        ]

    async def switch_session(self, session_id: str) -> bool:
        row = await self._db.fetchone("SELECT id FROM sessions WHERE id=?", (session_id,))
        if not row:
            return False
        self._current_session = session_id
        await self._touch_session(session_id)
        return True

    async def rename_session(self, title: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title[:60], time.time(), self.current_session),
        )

    async def delete_session(self, session_id: str | None = None) -> bool:
        target = session_id or self.current_session
        await self._db.execute("DELETE FROM messages WHERE session_id=?", (target,))
        await self._db.execute("DELETE FROM sessions WHERE id=?", (target,))
        if target == self._current_session:
            rows = await self._db.fetchall(
                "SELECT id FROM sessions WHERE archived=0 ORDER BY updated_at DESC LIMIT 1"
            )
            self._current_session = (
                str(rows[0][0]) if rows else await self.create_session(DEFAULT_TITLE)
            )
        return True

    async def _touch_session(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), session_id)
        )

    # ── 消息与上下文 ──────────────────────────────────────────────────
    async def append_turn(self, user: str, assistant: str, turn_id: str = "") -> None:
        now = time.time()
        session = self.current_session
        await self._db.execute(
            "INSERT INTO messages(session_id,role,content,turn_id,token_count,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (session, "user", user, turn_id, count_tokens(user), now),
        )
        await self._db.execute(
            "INSERT INTO messages(session_id,role,content,turn_id,token_count,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (session, "assistant", assistant, turn_id, count_tokens(assistant), now + 0.001),
        )
        await self._touch_session(session)

    async def recent_turns(self, limit: int = DEFAULT_SESSION_HISTORY) -> list[tuple[str, str]]:
        rows = await self._db.fetchall(
            "SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (self.current_session, limit * 2),
        )
        ordered = list(reversed(rows))
        turns: list[tuple[str, str]] = []
        pending_user: str | None = None
        for role, content in ordered:
            if role == "user":
                pending_user = str(content)
            elif role == "assistant" and pending_user is not None:
                turns.append((pending_user, str(content)))
                pending_user = None
        return turns[-limit:]

    async def message_count(self, session_id: str | None = None) -> int:
        row = await self._db.fetchone(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (session_id or self.current_session,),
        )
        return int(row[0]) if row else 0

    async def summary(self) -> str:
        row = await self._db.fetchone(
            "SELECT summary FROM sessions WHERE id=?", (self.current_session,)
        )
        return str(row[0] or "") if row else ""

    async def maybe_summarize(self, provider: Any) -> str:
        """超过 30 条消息时，把"最近 20 条之外"的旧消息滚动合并进摘要。"""
        if provider is None:
            return await self.summary()
        count = await self.message_count()
        if count <= SUMMARY_TRIGGER_MESSAGES:
            return await self.summary()
        row = await self._db.fetchone(
            "SELECT summary, summarized_upto FROM sessions WHERE id=?",
            (self.current_session,),
        )
        previous, summarized_upto = (str(row[0] or ""), int(row[1] or 0)) if row else ("", 0)
        recent_ids = await self._db.fetchall(
            "SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (self.current_session, SUMMARY_KEEP_MESSAGES),
        )
        if not recent_ids:
            return previous
        cutoff = min(int(item[0]) for item in recent_ids)
        rows = await self._db.fetchall(
            "SELECT role,content FROM messages WHERE session_id=? AND id>? AND id<=? "
            "ORDER BY id ASC",
            (self.current_session, summarized_upto, cutoff),
        )
        if not rows:
            return previous
        transcript = "\n".join(f"{role}: {content}" for role, content in rows)
        summary_text = await summarize(provider, previous, transcript)
        await self._db.execute(
            "UPDATE sessions SET summary=?, summarized_upto=?, updated_at=? WHERE id=?",
            (summary_text, cutoff, time.time(), self.current_session),
        )
        return summary_text

    async def after_turn(
        self,
        user: str,
        assistant: str,
        *,
        provider: Any = None,
        turn_id: str = "",
    ) -> None:
        await self.append_turn(user, assistant, turn_id)
        candidates = extract_rules(user)
        for candidate in candidates:
            await self.store_memory(candidate)
        if provider is not None and not candidates and len(user.strip()) >= 12:
            task = asyncio.create_task(self._extract_llm(provider, user))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        await self.maybe_summarize(provider)

    async def _extract_llm(self, provider: Any, text: str) -> None:
        try:
            candidates = await extract_with_llm(provider, text)
            for candidate in candidates:
                await self.store_memory(candidate)
        except Exception as exc:  # noqa: BLE001
            log.info("LLM 记忆抽取跳过: %s", exc)

    # ── 长期记忆 ──────────────────────────────────────────────────────
    async def store_memory(self, candidate: MemoryCandidate, session_id: str | None = None) -> None:
        now = time.time()
        target = session_id or self.current_session
        await self._db.execute(
            """
            INSERT INTO memories(
                session_id,type,content,keywords,importance,source,created_at,updated_at
            )
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id,content) DO UPDATE SET
                importance=MAX(memories.importance, excluded.importance),
                keywords=excluded.keywords,
                updated_at=excluded.updated_at
            """,
            (
                target,
                candidate.type,
                candidate.content,
                candidate.keywords or keywords_for(candidate.content),
                candidate.importance,
                "rule",
                now,
                now,
            ),
        )
        if candidate.type == "profile":
            await self._update_profile_from_memory(candidate.content)

    async def _update_profile_from_memory(self, content: str) -> None:
        import re

        match = re.search(r"名字是([\u4e00-\u9fa5A-Za-z0-9_]{1,12})", content)
        if match:
            await self.set_profile("name", match.group(1))

    async def recall(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        keywords = keywords_for(query)
        rows: list[Any] = []
        if self._db.fts_enabled and keywords:
            match = " OR ".join(f'"{token}"' for token in keywords.split()[:12])
            try:
                rows = await self._db.fetchall(
                    """
                    SELECT m.id, m.content, m.type, m.importance, m.updated_at,
                           bm25(memories_fts) AS rank
                    FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid
                    WHERE memories_fts MATCH ? LIMIT 30
                    """,
                    (match,),
                )
            except Exception as exc:  # noqa: BLE001 - FTS 语法问题回落到 LIKE
                log.debug("FTS query failed: %s", exc)
        if not rows:
            like = f"%{query[:40]}%"
            rows = await self._db.fetchall(
                "SELECT id,content,type,importance,updated_at,0.0 FROM memories "
                "WHERE content LIKE ? OR keywords LIKE ? ORDER BY updated_at DESC LIMIT 30",
                (like, like),
            )
        now = time.time()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            rank = float(row[5] or 0.0)
            importance = float(row[3] or 0.5)
            age_days = max(0.0, (now - float(row[4] or now)) / 86400)
            score = -rank * 0.1 + importance * 0.5 + 0.3 * math.exp(-age_days / 30)
            scored.append(
                (
                    score,
                    {
                        "id": int(row[0]),
                        "content": str(row[1]),
                        "type": str(row[2]),
                        "importance": importance,
                        "updated_at": float(row[4]),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    async def context_block(self, query: str, *, max_chars: int = 900) -> str:
        profile = await self.get_profile()
        summary = await self.summary()
        memories = await self.recall(query, 4)
        lines: list[str] = []
        if profile:
            rendered = "、".join(f"{key}={value}" for key, value in profile.items())
            lines.append(f"用户画像：{rendered}")
        if summary:
            lines.append(f"对话摘要：{summary}")
        if memories:
            lines.append("相关长期记忆：")
            lines.extend(f"- {item['content']}" for item in memories)
        if not lines:
            return ""
        return ("【长期记忆】\n" + "\n".join(lines))[:max_chars]

    async def list_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT id,type,content,importance,updated_at FROM memories "
            "WHERE session_id=? ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (self.current_session, limit),
        )
        return [
            {
                "id": int(row[0]),
                "type": str(row[1]),
                "content": str(row[2]),
                "importance": float(row[3]),
                "updated_at": float(row[4]),
            }
            for row in rows
        ]

    async def delete_memory(self, memory_id: int) -> None:
        await self._db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    async def delete_matching(self, query: str) -> int:
        matches = await self.recall(query, limit=20)
        for item in matches:
            await self.delete_memory(int(item["id"]))
        return len(matches)

    async def forget(self, *, all_sessions: bool = False) -> None:
        if all_sessions:
            await self._db.execute("DELETE FROM memories")
            await self._db.execute("DELETE FROM profiles")
        else:
            await self._db.execute(
                "DELETE FROM memories WHERE session_id=?", (self.current_session,)
            )

    # ── 画像 ──────────────────────────────────────────────────────────
    async def get_profile(self) -> dict[str, str]:
        rows = await self._db.fetchall("SELECT key,value FROM profiles ORDER BY key")
        return {str(key): str(value) for key, value in rows}

    async def set_profile(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO profiles(key,value,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key[:40], value[:200], time.time()),
        )

    # ── 提醒 ──────────────────────────────────────────────────────────
    async def add_reminder(self, text: str, due_at: float) -> int:
        reminder_id = await self._db.execute(
            "INSERT INTO reminders(text,due_at,created_at) VALUES (?,?,?)",
            (text[:200], due_at, time.time()),
        )
        return int(reminder_id or 0)

    async def list_reminders(self, include_done: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT id,text,due_at,status,fired_at FROM reminders"
        if not include_done:
            sql += " WHERE status='pending'"
        sql += " ORDER BY due_at ASC LIMIT 50"
        rows = await self._db.fetchall(sql)
        return [
            {
                "id": int(row[0]),
                "text": str(row[1]),
                "due_at": float(row[2]),
                "status": str(row[3]),
                "fired_at": row[4],
            }
            for row in rows
        ]

    async def due_reminders(self, now: float | None = None) -> list[dict[str, Any]]:
        moment = time.time() if now is None else now
        rows = await self._db.fetchall(
            "SELECT id,text,due_at FROM reminders WHERE status='pending' AND due_at<=? "
            "ORDER BY due_at ASC LIMIT 10",
            (moment,),
        )
        return [{"id": int(row[0]), "text": str(row[1]), "due_at": float(row[2])} for row in rows]

    async def mark_reminder_fired(self, reminder_id: int) -> None:
        await self._db.execute(
            "UPDATE reminders SET status='fired', fired_at=? WHERE id=?",
            (time.time(), reminder_id),
        )

    # ── 指标 ──────────────────────────────────────────────────────────
    async def record_metric(self, name: str, value: float, meta: str = "{}") -> None:
        await self._db.execute(
            "INSERT INTO metrics(ts,name,value,meta) VALUES (?,?,?,?)",
            (time.time(), name, value, meta),
        )
