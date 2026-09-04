import psycopg2.extras

# Preferences live on the user row rather than in a table of their own: this app is single-user, and
# a preference is a property of the person who onboarded, not an entity in its own right.
ADD_ALWAYS_APPROVE_COLUMN_SQL = """
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS always_approve_commands BOOLEAN NOT NULL DEFAULT false
"""


def _user_table_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.user')")
        return cur.fetchone()[0] is not None


# The ALTER below is idempotent but still takes a brief exclusive lock, and the orchestrator reads
# preferences on every ad-hoc command. Once per process is enough to heal an upgraded database.
_columns_ensured = False


def ensure_preferences_columns(conn):
    """Adds any preference column an older database predates, and reports whether there is a user
    table to read at all.

    Onboarding's CREATE TABLE covers fresh installs, but a database that was onboarded before this
    preference existed would otherwise be missing the column with no migration step to add it - so
    an upgraded install heals itself on first use, the same shape as the CREATE TABLE IF NOT EXISTS
    calls elsewhere in the codebase.
    """
    global _columns_ensured

    if not _user_table_exists(conn):
        # Not cached: the table appears when onboarding runs, and the column has to be added then.
        return False

    if _columns_ensured:
        return True

    with conn.cursor() as cur:
        cur.execute(ADD_ALWAYS_APPROVE_COLUMN_SQL)
    _columns_ensured = True
    return True


def get_preferences(conn):
    """The onboarded user's preferences, or None if nobody has onboarded yet."""
    if not ensure_preferences_columns(conn):
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT id, always_approve_commands FROM "user" ORDER BY id LIMIT 1')
        return cur.fetchone()


def set_always_approve_commands(conn, enabled):
    """Returns the updated row, or None if nobody has onboarded yet."""
    if not ensure_preferences_columns(conn):
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE "user"
            SET always_approve_commands = %s
            WHERE id = (SELECT id FROM "user" ORDER BY id LIMIT 1)
            RETURNING id, always_approve_commands
            """,
            (bool(enabled),),
        )
        return cur.fetchone()
