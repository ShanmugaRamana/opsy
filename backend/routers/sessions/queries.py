import psycopg2.extras

CREATE_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id SERIAL PRIMARY KEY,
    session_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_CHATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    chat TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# Short-term memory reads the newest few rows of one session on every single turn (see
# routers/orchestrator/memory/short_term/). Without this index that read is a full scan of `chats`,
# which grows without bound - the one query in this file whose cost is not bounded by the session.
CREATE_CHATS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS chats_session_id_chat_id_idx ON chats (session_id, chat_id DESC)
"""


def _ensure_tables(cur):
    cur.execute(CREATE_SESSIONS_TABLE_SQL)
    cur.execute(CREATE_CHATS_TABLE_SQL)
    cur.execute(CREATE_CHATS_INDEX_SQL)


def create_session(conn, name):
    """Inserts a new session and makes it the one active session, deactivating whatever was active
    before - `is_active` is an invariant (at most one true row), not a soft-delete flag. Returns the
    new session_id."""
    with conn.cursor() as cur:
        _ensure_tables(cur)
        cur.execute("UPDATE sessions SET is_active = false WHERE is_active = true")
        cur.execute(
            "INSERT INTO sessions (session_name, is_active) VALUES (%s, true) RETURNING session_id",
            (name,),
        )
        return cur.fetchone()[0]


def activate_session(conn, session_id):
    """Makes session_id the one active session, deactivating whatever was active before."""
    with conn.cursor() as cur:
        _ensure_tables(cur)
        cur.execute("UPDATE sessions SET is_active = false WHERE is_active = true")
        cur.execute("UPDATE sessions SET is_active = true WHERE session_id = %s", (session_id,))


def touch_session(conn, session_id):
    with conn.cursor() as cur:
        _ensure_tables(cur)
        cur.execute("UPDATE sessions SET updated_at = now() WHERE session_id = %s", (session_id,))


def rename_session(conn, session_id, name):
    with conn.cursor() as cur:
        _ensure_tables(cur)
        cur.execute("UPDATE sessions SET session_name = %s WHERE session_id = %s", (name, session_id))


def get_session(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.sessions')")
        if cur.fetchone()[0] is None:
            return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT session_id, session_name, is_active, created_at, updated_at "
            "FROM sessions WHERE session_id = %s",
            (session_id,),
        )
        return cur.fetchone()


def list_sessions(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.sessions')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT session_id, session_name, is_active, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC"
        )
        return cur.fetchall()


def insert_chat(conn, session_id, role, chat_text):
    with conn.cursor() as cur:
        _ensure_tables(cur)
        cur.execute(
            "INSERT INTO chats (session_id, role, chat) VALUES (%s, %s, %s)",
            (session_id, role, chat_text),
        )


def delete_trailing_user_chats(conn, session_id, chat_text):
    """Removes the unanswered user rows at the tail of a session that say exactly `chat_text`.

    A turn that fails still leaves its user row behind, so retrying that message would otherwise stack
    a second copy of the same question in the transcript. Two things keep this narrow: only rows after
    the last assistant reply are candidates, since a user row a reply followed is part of a completed
    turn; and only rows matching the message being retried are removed, so retrying one failed message
    does not quietly erase a different failed message sitting beside it. Returns the rows removed.

    Keyed on chat_id rather than created_at for the same reason list_recent_chats is - the two rows of
    one turn can share a timestamp, and only the serial is unambiguous."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.chats')")
        if cur.fetchone()[0] is None:
            return 0

        cur.execute(
            "DELETE FROM chats WHERE session_id = %s AND role = 'user' AND chat = %s AND chat_id > "
            "COALESCE((SELECT MAX(chat_id) FROM chats WHERE session_id = %s AND role = 'assistant'), 0)",
            (session_id, chat_text, session_id),
        )
        return cur.rowcount


def list_chats(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.chats')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT chat_id, session_id, role, chat, created_at FROM chats "
            "WHERE session_id = %s ORDER BY created_at ASC, chat_id ASC",
            (session_id,),
        )
        return cur.fetchall()


def list_recent_chats(conn, session_id, limit):
    """The newest `limit` rows of a session, newest first - the bounded read short-term memory is
    built on, as opposed to list_chats, which returns the whole session for replay into the UI.

    Ordered by chat_id rather than created_at: created_at is now() at insert, so the two rows of a
    single turn can share a timestamp and order ambiguously. chat_id is the serial insertion order
    and cannot."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.chats')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT chat_id, session_id, role, chat, created_at FROM chats "
            "WHERE session_id = %s ORDER BY chat_id DESC LIMIT %s",
            (session_id, limit),
        )
        return cur.fetchall()
