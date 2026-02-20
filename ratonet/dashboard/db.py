"""Banco de dados SQLite async para persistência de streamers e expedições."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

from ratonet.common.logger import get_logger

log = get_logger("db")

DB_PATH = "ratonet.db"


async def init_db(db_path: str = DB_PATH) -> None:
    """Cria tabelas se não existirem."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS streamers (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                email       TEXT UNIQUE,
                avatar_url  TEXT DEFAULT '',
                color       TEXT DEFAULT '#ff6600',
                is_crown    INTEGER DEFAULT 0,
                socials     TEXT DEFAULT '[]',
                api_key     TEXT UNIQUE NOT NULL,
                config      TEXT DEFAULT '{}',
                approved    INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expeditions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                active      INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL
            );
        """)
        await db.commit()
    log.info("Banco de dados inicializado: %s", db_path)


def _generate_api_key() -> str:
    """Gera uma API key segura."""
    return f"rn_{secrets.token_urlsafe(32)}"


def _row_to_dict(row: aiosqlite.Row, columns: List[str]) -> Dict[str, Any]:
    """Converte row do SQLite para dict."""
    d = dict(zip(columns, row))
    # Converte campos JSON
    if "socials" in d and isinstance(d["socials"], str):
        try:
            d["socials"] = json.loads(d["socials"])
        except (json.JSONDecodeError, TypeError):
            d["socials"] = []
    if "config" in d and isinstance(d["config"], str):
        try:
            d["config"] = json.loads(d["config"])
        except (json.JSONDecodeError, TypeError):
            d["config"] = {}
    # Converte booleans
    if "is_crown" in d:
        d["is_crown"] = bool(d["is_crown"])
    if "approved" in d:
        d["approved"] = bool(d["approved"])
    return d


STREAMER_COLUMNS = [
    "id", "name", "email", "avatar_url", "color",
    "is_crown", "socials", "api_key", "config", "approved", "created_at",
]


# --- Streamers CRUD ---

async def create_streamer(
    name: str,
    email: str,
    avatar_url: str = "",
    color: str = "#ff6600",
    socials: Optional[List[str]] = None,
    auto_approve: bool = False,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    """Registra novo streamer. Retorna dados incluindo api_key."""
    streamer_id = str(uuid.uuid4())
    api_key = _generate_api_key()
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO streamers (id, name, email, avatar_url, color, socials, api_key, approved, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                streamer_id, name, email, avatar_url, color,
                json.dumps(socials or []), api_key,
                1 if auto_approve else 0, now,
            ),
        )
        await db.commit()

    log.info("Streamer criado: %s (%s) — approved=%s", name, streamer_id, auto_approve)
    return {
        "id": streamer_id,
        "name": name,
        "email": email,
        "avatar_url": avatar_url,
        "color": color,
        "socials": socials or [],
        "api_key": api_key,
        "approved": auto_approve,
        "created_at": now,
    }


async def get_streamer_by_id(
    streamer_id: str, db_path: str = DB_PATH
) -> Optional[Dict[str, Any]]:
    """Busca streamer por ID."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT * FROM streamers WHERE id = ?", (streamer_id,)
        )
        row = await cursor.fetchone()
        if row:
            return _row_to_dict(row, STREAMER_COLUMNS)
    return None


async def get_streamer_by_api_key(
    api_key: str, db_path: str = DB_PATH
) -> Optional[Dict[str, Any]]:
    """Busca streamer por API key."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT * FROM streamers WHERE api_key = ?", (api_key,)
        )
        row = await cursor.fetchone()
        if row:
            return _row_to_dict(row, STREAMER_COLUMNS)
    return None


async def get_streamer_by_email(
    email: str, db_path: str = DB_PATH
) -> Optional[Dict[str, Any]]:
    """Busca streamer por email."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT * FROM streamers WHERE email = ?", (email,)
        )
        row = await cursor.fetchone()
        if row:
            return _row_to_dict(row, STREAMER_COLUMNS)
    return None


async def list_streamers(
    approved_only: bool = False, db_path: str = DB_PATH
) -> List[Dict[str, Any]]:
    """Lista streamers. Se approved_only=True, retorna apenas aprovados."""
    async with aiosqlite.connect(db_path) as db:
        if approved_only:
            cursor = await db.execute(
                "SELECT * FROM streamers WHERE approved = 1 ORDER BY created_at"
            )
        else:
            cursor = await db.execute("SELECT * FROM streamers ORDER BY created_at")
        rows = await cursor.fetchall()
        return [_row_to_dict(row, STREAMER_COLUMNS) for row in rows]


async def update_streamer(
    streamer_id: str,
    db_path: str = DB_PATH,
    **kwargs: Any,
) -> bool:
    """Atualiza campos do streamer."""
    allowed = {"name", "avatar_url", "color", "socials", "is_crown", "config", "approved", "email"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    if not updates:
        return False

    # Serializa campos JSON
    if "socials" in updates and isinstance(updates["socials"], list):
        updates["socials"] = json.dumps(updates["socials"])
    if "config" in updates and isinstance(updates["config"], dict):
        updates["config"] = json.dumps(updates["config"])
    if "is_crown" in updates:
        updates["is_crown"] = 1 if updates["is_crown"] else 0
    if "approved" in updates:
        updates["approved"] = 1 if updates["approved"] else 0

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [streamer_id]

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE streamers SET {set_clause} WHERE id = ?", values
        )
        await db.commit()

    return True


async def delete_streamer(
    streamer_id: str, db_path: str = DB_PATH
) -> bool:
    """Remove streamer."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM streamers WHERE id = ?", (streamer_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def approve_streamer(
    streamer_id: str, db_path: str = DB_PATH
) -> bool:
    """Aprova streamer."""
    return await update_streamer(streamer_id, db_path=db_path, approved=True)
