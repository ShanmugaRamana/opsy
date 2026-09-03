import psycopg2.extras

CREATE_BYOK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS byok (
    id SERIAL PRIMARY KEY,
    provider TEXT NOT NULL UNIQUE,
    api_key_encrypted TEXT NOT NULL,
    key_last4 TEXT NOT NULL,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def has_any_key(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.byok')")
        if cur.fetchone()[0] is None:
            return False

        cur.execute("SELECT EXISTS (SELECT 1 FROM byok)")
        return cur.fetchone()[0]


def upsert_key(conn, provider, encrypted_key, last4):
    with conn.cursor() as cur:
        cur.execute(CREATE_BYOK_TABLE_SQL)
        cur.execute(
            """
            INSERT INTO byok (provider, api_key_encrypted, key_last4, verified_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (provider) DO UPDATE
            SET api_key_encrypted = EXCLUDED.api_key_encrypted,
                key_last4 = EXCLUDED.key_last4,
                verified_at = now()
            """,
            (provider, encrypted_key, last4),
        )


def get_key(conn, provider):
    """Returns the encrypted key row for a provider, or None if not configured."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT to_regclass('public.byok')")
        if cur.fetchone()[0] is None:
            return None

        cur.execute("SELECT api_key_encrypted FROM byok WHERE provider = %s", (provider,))
        return cur.fetchone()


def list_keys(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.byok')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT provider, key_last4, verified_at FROM byok ORDER BY provider")
        return cur.fetchall()
