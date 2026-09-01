import psycopg2
from fastapi import APIRouter

import config

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/verify")
def verify_onboarding():
    conn = psycopg2.connect(
        host=config.SUPABASE_DB_HOST,
        port=config.SUPABASE_DB_PORT,
        dbname=config.SUPABASE_DB_NAME,
        user=config.SUPABASE_DB_USER,
        password=config.SUPABASE_DB_PASSWORD,
        connect_timeout=3,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.user')")
            if cur.fetchone()[0] is None:
                return {"onboarding_required": True}

            cur.execute('SELECT EXISTS (SELECT 1 FROM "user")')
            has_user = cur.fetchone()[0]
            return {"onboarding_required": not has_user}
    finally:
        conn.close()
