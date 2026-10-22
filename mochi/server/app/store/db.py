"""SQLite 基础设施（T6-01）：WAL + 单写者队列 + 版本化 schema。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
BASE_SCHEMA = Path(__file__).resolve().parent / "schema.sql"
FTS_SCHEMA = Path(__file__).resolve().parent / "fts.sql"

WriteFuture = asyncio.Future[int | None]


class Database:
    """所有写操作进单队列，读操作走 WAL 并发连接。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_queue: asyncio.Queue[tuple[str, tuple[Any, ...], WriteFuture] | None] = (
            asyncio.Queue()
        )
        self._writer: asyncio.Task[None] | None = None
        self.fts_enabled = False

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not started")
        return self._conn

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.path))
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(BASE_SCHEMA.read_text(encoding="utf-8"))
        await self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        try:
            await self._conn.executescript(FTS_SCHEMA.read_text(encoding="utf-8"))
            self.fts_enabled = True
        except Exception as exc:  # noqa: BLE001 - 老 SQLite 可能无 FTS5
            self.fts_enabled = False
            log.warning("FTS5 不可用，长期记忆回落到 LIKE: %s", exc)
        await self._conn.commit()
        self._writer = asyncio.create_task(self._writer_loop(), name="sqlite-writer")
        log.info("sqlite ready path=%s fts=%s", self.path, self.fts_enabled)

    async def _writer_loop(self) -> None:
        while True:
            item = await self._write_queue.get()
            if item is None:
                return
            sql, params, future = item
            try:
                cursor = await self.connection.execute(sql, params)
                await self.connection.commit()
                future.set_result(cursor.lastrowid)
            except Exception as exc:  # noqa: BLE001 - 交给调用方
                future.set_exception(exc)
            finally:
                self._write_queue.task_done()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int | None:
        future: WriteFuture = asyncio.get_running_loop().create_future()
        await self._write_queue.put((sql, params, future))
        return await future

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        async with self.connection.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        async with self.connection.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def stop(self) -> None:
        if self._writer is not None:
            await self._write_queue.put(None)
            await self._writer
            self._writer = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
