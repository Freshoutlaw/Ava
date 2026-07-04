"""
Ava — memory_supabase.py
Tier 4 + Supabase: Persistent memory backed by Supabase Postgres.

Provides async functions to read/write facts, notes, preferences, tool accuracy,
and interaction logs to the ava_memory Supabase project.

All reads are synchronous; writes are async and cached locally first.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

try:
    import asyncpg
except ImportError:
    asyncpg = None

# ── Connection pool ───────────────────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()

async def _get_pool() -> Optional[asyncpg.Pool]:
    """Lazy-init the connection pool."""
    global _pool
    if _pool:
        return _pool
    
    url = os.environ.get("SUPABASE_AVA_MEMORY_URL", "").strip()
    if not url:
        print("[memory_supabase] No SUPABASE_AVA_MEMORY_URL configured")
        return None
    
    try:
        async with _pool_lock:
            if _pool:
                return _pool
            _pool = await asyncpg.create_pool(
                url,
                statement_cache_size=0,
                min_size=1,
                max_size=5,
                command_timeout=5,
            )
            print(f"[memory_supabase] Connection pool initialized")
        return _pool
    except Exception as e:
        print(f"[memory_supabase] Pool creation failed: {e}")
        _pool = None
        return None

async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

# ── Sync reads (blocking, cached) ─────────────────────────────────────────────

def get_facts() -> Dict[str, str]:
    """Read all facts from memory_facts table (sync, cached)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_get_facts())
        loop.close()
        return result
    except Exception as e:
        print(f"[memory_supabase] get_facts failed: {e}")
        return {}

def get_notes() -> List[Dict[str, Any]]:
    """Read all notes from memory_notes table (sync, cached)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_get_notes())
        loop.close()
        return result
    except Exception as e:
        print(f"[memory_supabase] get_notes failed: {e}")
        return []

def get_preferences() -> Dict[str, Any]:
    """Read all preferences from memory_preferences table (sync, cached)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_get_preferences())
        loop.close()
        return result
    except Exception as e:
        print(f"[memory_supabase] get_preferences failed: {e}")
        return {}

def get_tool_accuracy() -> Dict[str, Dict[str, float]]:
    """Read all tool accuracy stats (sync, cached)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_get_tool_accuracy())
        loop.close()
        return result
    except Exception as e:
        print(f"[memory_supabase] get_tool_accuracy failed: {e}")
        return {}

# ── Async reads ───────────────────────────────────────────────────────────────

async def _async_get_facts() -> Dict[str, str]:
    """Read all facts from DB."""
    pool = await _get_pool()
    if not pool:
        return {}
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM memory_facts ORDER BY updated_at DESC")
            return {row['key']: row['value'] for row in rows}
    except Exception as e:
        print(f"[memory_supabase] _async_get_facts failed: {e}")
        return {}

async def _async_get_notes() -> List[Dict[str, Any]]:
    """Read all notes from DB."""
    pool = await _get_pool()
    if not pool:
        return []
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, content, created_at, tags FROM memory_notes ORDER BY created_at DESC")
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"[memory_supabase] _async_get_notes failed: {e}")
        return []

async def _async_get_preferences() -> Dict[str, Any]:
    """Read all preferences from DB."""
    pool = await _get_pool()
    if not pool:
        return {}
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT preference_key, preference_value FROM memory_preferences ORDER BY updated_at DESC")
            return {row['preference_key']: row['preference_value'] for row in rows}
    except Exception as e:
        print(f"[memory_supabase] _async_get_preferences failed: {e}")
        return {}

async def _async_get_tool_accuracy() -> Dict[str, Dict[str, float]]:
    """Read all tool accuracy stats from DB."""
    pool = await _get_pool()
    if not pool:
        return {}
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tool_name, success_count, failure_count, accuracy FROM memory_tool_accuracy"
            )
            result = {}
            for row in rows:
                result[row['tool_name']] = {
                    'success_count': row['success_count'],
                    'failure_count': row['failure_count'],
                    'accuracy': row['accuracy'],
                }
            return result
    except Exception as e:
        print(f"[memory_supabase] _async_get_tool_accuracy failed: {e}")
        return {}

# ── Async writes ──────────────────────────────────────────────────────────────

async def save_fact(key: str, value: str) -> bool:
    """Save or update a fact in the DB."""
    pool = await _get_pool()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memory_facts (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = $2, updated_at = NOW()
                """,
                key, value
            )
        return True
    except Exception as e:
        print(f"[memory_supabase] save_fact({key}) failed: {e}")
        return False

async def save_note(content: str, tags: List[str] = None) -> bool:
    """Save a note to the DB."""
    pool = await _get_pool()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO memory_notes (content, tags) VALUES ($1, $2)",
                content, tags or []
            )
        return True
    except Exception as e:
        print(f"[memory_supabase] save_note failed: {e}")
        return False

async def save_preference(key: str, value: Any, confidence: float = 0.5) -> bool:
    """Save or update a preference."""
    pool = await _get_pool()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memory_preferences (preference_key, preference_value, confidence, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (preference_key) DO UPDATE
                SET preference_value = $2, confidence = $3, updated_at = NOW()
                """,
                key, json.dumps(value), confidence
            )
        return True
    except Exception as e:
        print(f"[memory_supabase] save_preference({key}) failed: {e}")
        return False

async def record_tool_call(
    tool_name: str,
    success: bool,
) -> bool:
    """Record a tool call result."""
    pool = await _get_pool()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            if success:
                await conn.execute(
                    """
                    INSERT INTO memory_tool_accuracy (tool_name, success_count, failure_count, accuracy)
                    VALUES ($1, 1, 0, 1.0)
                    ON CONFLICT (tool_name) DO UPDATE
                    SET success_count = success_count + 1,
                        accuracy = CAST(success_count + 1 AS FLOAT) / (success_count + failure_count + 1)
                    """,
                    tool_name
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO memory_tool_accuracy (tool_name, success_count, failure_count, accuracy)
                    VALUES ($1, 0, 1, 0.0)
                    ON CONFLICT (tool_name) DO UPDATE
                    SET failure_count = failure_count + 1,
                        accuracy = CAST(success_count AS FLOAT) / (success_count + failure_count + 1)
                    """,
                    tool_name
                )
        return True
    except Exception as e:
        print(f"[memory_supabase] record_tool_call({tool_name}) failed: {e}")
        return False

async def log_interaction(
    turn_number: int,
    role: str,
    content: str,
    tools_used: List[str] = None,
) -> bool:
    """Log an interaction turn."""
    pool = await _get_pool()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO memory_interactions (turn_number, role, content, tools_used) VALUES ($1, $2, $3, $4)",
                turn_number, role, content, tools_used or []
            )
        return True
    except Exception as e:
        print(f"[memory_supabase] log_interaction failed: {e}")
        return False

# ── Health check ──────────────────────────────────────────────────────────────

async def test_connection() -> bool:
    """Test the Supabase connection."""
    pool = await _get_pool()
    if not pool:
        print("[memory_supabase] No connection URL configured")
        return False
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT current_user AS user, now() AS ts")
            print(f"[memory_supabase] Connected as {row['user']}")
            return True
    except Exception as e:
        print(f"[memory_supabase] Connection test failed: {e}")
        return False
