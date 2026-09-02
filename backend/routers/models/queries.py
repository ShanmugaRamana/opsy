import psycopg2.extras

from .catalog import PROVIDER_CATALOG

CREATE_MODELS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS models (
    id SERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, model_id)
)
"""


def sync_provider_catalog(conn, provider):
    """Replaces this provider's rows with its curated catalog. No-op if the provider
    isn't in our catalog (e.g. an unsupported/removed provider)."""
    catalog_entries = PROVIDER_CATALOG.get(provider, [])

    with conn.cursor() as cur:
        cur.execute(CREATE_MODELS_TABLE_SQL)
        cur.execute("DELETE FROM models WHERE provider = %s", (provider,))
        for model_id, display_name in catalog_entries:
            cur.execute(
                "INSERT INTO models (provider, model_id, display_name) VALUES (%s, %s, %s)",
                (provider, model_id, display_name),
            )


def list_models(conn, provider=None):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.models')")
        if cur.fetchone()[0] is None:
            return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if provider:
            cur.execute(
                "SELECT provider, model_id, display_name FROM models WHERE provider = %s ORDER BY display_name",
                (provider,),
            )
        else:
            cur.execute("SELECT provider, model_id, display_name FROM models ORDER BY provider, display_name")
        return cur.fetchall()
