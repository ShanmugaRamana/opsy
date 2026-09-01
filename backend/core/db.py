import psycopg2
from fastapi import HTTPException

import config


def get_connection():
    try:
        return psycopg2.connect(
            host=config.SUPABASE_DB_HOST,
            port=config.SUPABASE_DB_PORT,
            dbname=config.SUPABASE_DB_NAME,
            user=config.SUPABASE_DB_USER,
            password=config.SUPABASE_DB_PASSWORD,
            connect_timeout=3,
        )
    except psycopg2.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")
