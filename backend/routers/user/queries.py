import psycopg2.extras


def list_users(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.user')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT id, name, profile_pic, linux_experience, role_use_case, created_at FROM "user" ORDER BY id')
        return cur.fetchall()
