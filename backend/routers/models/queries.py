import psycopg2.extras

from routers.models.providers import LOCAL_PROVIDERS

from .catalog import PROVIDER_CATALOG, PROVIDER_DISPLAY_NAMES

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
    isn't in our catalog (e.g. an unsupported/removed provider).

    Refuses local providers outright rather than silently no-op'ing: this does a blanket
    `DELETE FROM models WHERE provider = %s`, and a local provider's rows are only ever meant to be
    added one at a time, by `local/queries.py:mark_ready()`, as each download finishes. Running this
    against 'ollama' would wipe every model a user has downloaded.
    """
    if provider in LOCAL_PROVIDERS:
        raise ValueError(
            f"sync_provider_catalog() must not be called for local provider {provider!r} - "
            "local models table rows are managed by local/queries.py:mark_ready()"
        )

    catalog_entries = PROVIDER_CATALOG.get(provider, [])

    with conn.cursor() as cur:
        cur.execute(CREATE_MODELS_TABLE_SQL)
        cur.execute("DELETE FROM models WHERE provider = %s", (provider,))
        for model_id, display_name in catalog_entries:
            cur.execute(
                "INSERT INTO models (provider, model_id, display_name) VALUES (%s, %s, %s)",
                (provider, model_id, display_name),
            )


def clear_provider_catalog(conn, provider):
    """Removes all of a cloud provider's rows from the models table. Used when its BYOK key is
    deleted, since a provider with no key configured shouldn't still offer models to pick from.
    Same local-provider guard as sync_provider_catalog, for the same reason."""
    if provider in LOCAL_PROVIDERS:
        raise ValueError(
            f"clear_provider_catalog() must not be called for local provider {provider!r} - "
            "local models table rows are managed by local/queries.py:mark_ready()"
        )

    with conn.cursor() as cur:
        cur.execute(CREATE_MODELS_TABLE_SQL)
        cur.execute("DELETE FROM models WHERE provider = %s", (provider,))


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
        rows = cur.fetchall()

    for row in rows:
        row["provider_display_name"] = PROVIDER_DISPLAY_NAMES.get(row["provider"], row["provider"])

    return rows
