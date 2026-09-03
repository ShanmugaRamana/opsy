import logging

import psycopg2.extras

from routers.models.queries import CREATE_MODELS_TABLE_SQL
from .catalog import BACKEND, get_entry

logger = logging.getLogger("local-models")

CREATE_LOCAL_MODELS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS local_models (
    id SERIAL PRIMARY KEY,
    backend TEXT NOT NULL DEFAULT 'ollama',
    model_key TEXT NOT NULL,
    model_ref TEXT NOT NULL,
    display_name TEXT NOT NULL,
    params_b NUMERIC(5,2),
    quantization TEXT,
    size_bytes BIGINT,
    context_length INTEGER NOT NULL,
    supports_tools BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL,
    error TEXT,
    downloaded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (backend, model_key)
)
"""

STATUS_DOWNLOADING = "downloading"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# Tool loops run 4 rounds against a full command schema plus accumulating tool output - this is set
# generously rather than trimmed, per the standing rule against shrinking what a model is told its
# tools do.
DEFAULT_CONTEXT_LENGTH = 16384


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_LOCAL_MODELS_TABLE_SQL)
        cur.execute(CREATE_MODELS_TABLE_SQL)


def start_download(conn, model_key):
    """Inserts (or resets) a `downloading` row for this model. Any prior failed attempt at the same
    key is overwritten, since a fresh download attempt supersedes it."""
    entry = get_entry(model_key)
    if entry is None:
        raise ValueError(f"unknown local model key: {model_key}")

    with conn.cursor() as cur:
        _ensure_tables(conn)
        cur.execute(
            """
            INSERT INTO local_models
                (backend, model_key, model_ref, display_name, params_b, quantization,
                 context_length, status, error, downloaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
            ON CONFLICT (backend, model_key) DO UPDATE
            SET status = EXCLUDED.status, error = NULL, downloaded_at = NULL
            """,
            (
                BACKEND, model_key, entry["tag"], entry["display_name"], entry["params_b"],
                entry["quantization"], DEFAULT_CONTEXT_LENGTH, STATUS_DOWNLOADING,
            ),
        )


def mark_failed(conn, model_key, error):
    with conn.cursor() as cur:
        _ensure_tables(conn)
        cur.execute(
            "UPDATE local_models SET status = %s, error = %s WHERE backend = %s AND model_key = %s",
            (STATUS_FAILED, str(error)[:500], BACKEND, model_key),
        )
    logger.error(f"local-models - {model_key} failed: {error}")


def mark_ready(conn, model_key, size_bytes):
    """The ONLY place a local model's row is published into `models`. Flipping `local_models.status`
    to 'ready' and inserting the `models` row happen in the same transaction (the caller commits both
    together), so a model the picker can select is always one that actually finished downloading -
    never a `downloading`, `failed`, or cancelled one."""
    entry = get_entry(model_key)
    if entry is None:
        raise ValueError(f"unknown local model key: {model_key}")

    with conn.cursor() as cur:
        _ensure_tables(conn)
        cur.execute(
            """
            UPDATE local_models
            SET status = %s, size_bytes = %s, downloaded_at = now(), error = NULL
            WHERE backend = %s AND model_key = %s
            """,
            (STATUS_READY, size_bytes, BACKEND, model_key),
        )
        cur.execute(
            """
            INSERT INTO models (provider, model_id, display_name) VALUES (%s, %s, %s)
            ON CONFLICT (provider, model_id) DO UPDATE SET display_name = EXCLUDED.display_name
            """,
            (BACKEND, entry["tag"], entry["display_name"]),
        )
    logger.info(f"local-models - published {BACKEND}/{entry['tag']} to models")


def delete_model(conn, model_key):
    entry = get_entry(model_key)
    with conn.cursor() as cur:
        _ensure_tables(conn)
        cur.execute("DELETE FROM local_models WHERE backend = %s AND model_key = %s", (BACKEND, model_key))
        if entry:
            cur.execute("DELETE FROM models WHERE provider = %s AND model_id = %s", (BACKEND, entry["tag"]))


def list_local_models(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.local_models')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT model_key, model_ref, display_name, params_b, quantization, size_bytes, "
            "status, error, downloaded_at FROM local_models WHERE backend = %s ORDER BY display_name",
            (BACKEND,),
        )
        return cur.fetchall()


def has_ready_local_model(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.local_models')")
        if cur.fetchone()[0] is None:
            return False

        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM local_models WHERE status = %s)",
            (STATUS_READY,),
        )
        return cur.fetchone()[0]


def clear_stale_downloads(conn):
    """Called on startup: a row still `downloading` from a previous process means that process died
    mid-pull, since a live download would be re-registered by whatever's running now, not found
    already in this state. Left as `downloading` it would look like a live progress bar that will
    never move."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.local_models')")
        if cur.fetchone()[0] is None:
            return

        cur.execute(
            "UPDATE local_models SET status = %s, error = %s WHERE status = %s RETURNING model_key",
            (STATUS_FAILED, "interrupted", STATUS_DOWNLOADING),
        )
        stale = cur.fetchall()

    for (model_key,) in stale:
        logger.warning(f"local-models - marking interrupted download {model_key} as failed")
