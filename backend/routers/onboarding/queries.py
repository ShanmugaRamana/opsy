CREATE_USER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS "user" (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    linux_experience TEXT NOT NULL,
    role_use_case TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def user_table_has_rows(conn):
    """Returns None if the user table doesn't exist yet, else whether it has any rows."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.user')")
        if cur.fetchone()[0] is None:
            return None

        cur.execute('SELECT EXISTS (SELECT 1 FROM "user")')
        return cur.fetchone()[0]


def insert_user(conn, name, linux_experience, role_use_case):
    with conn.cursor() as cur:
        cur.execute(CREATE_USER_TABLE_SQL)
        cur.execute(
            'INSERT INTO "user" (name, linux_experience, role_use_case) VALUES (%s, %s, %s)',
            (name, linux_experience, role_use_case),
        )
