"""Idempotent schema helpers for the demo Postgres / Supabase database."""

from __future__ import annotations

from leasing_analytics import SCHEMA_STATEMENTS as ANALYTICS_SCHEMA

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS units (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), unit_number text NOT NULL UNIQUE,
        building text, floor integer, bedrooms integer, bathrooms double precision,
        sqft integer, rent_usd numeric, status text NOT NULL DEFAULT 'vacant'
    );""",
    """CREATE TABLE IF NOT EXISTS tours (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), unit_id uuid REFERENCES units(id),
        prospect_name text NOT NULL, prospect_email text NOT NULL, tour_type text,
        scheduled_at timestamptz NOT NULL
    );""",
    """CREATE TABLE IF NOT EXISTS reservations (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), unit_id uuid REFERENCES units(id),
        prospect_name text NOT NULL, prospect_email text NOT NULL,
        status text NOT NULL DEFAULT 'held', expires_at timestamptz NOT NULL
    );""",
    """CREATE TABLE IF NOT EXISTS leads (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), full_name text NOT NULL,
        email text NOT NULL UNIQUE, phone text, preferred_beds integer, max_budget_usd numeric
    );""",
    """
    ALTER TABLE units ADD COLUMN IF NOT EXISTS available_from date DEFAULT CURRENT_DATE;
    ALTER TABLE units ADD COLUMN IF NOT EXISTS photos jsonb DEFAULT '[]'::jsonb;
    """,
    """
    ALTER TABLE units ADD COLUMN IF NOT EXISTS vacant_since timestamptz;
    """,
    """
    ALTER TABLE units ADD COLUMN IF NOT EXISTS amenities jsonb DEFAULT '[]'::jsonb;
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS units_unit_number_key ON units (unit_number);
    """,
    """
    CREATE TABLE IF NOT EXISTS market_comps (
        id bigserial PRIMARY KEY,
        listing_id text,
        zip_code text,
        address text,
        bedrooms int,
        bathrooms double precision,
        sqft int,
        rent_usd numeric,
        pulled_at timestamptz DEFAULT now()
    );
    """,
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in SCHEMA_STATEMENTS + ANALYTICS_SCHEMA:
            cur.execute(stmt)
    conn.commit()


if __name__ == "__main__":
    import os
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    with psycopg2.connect(os.environ["SUPABASE_DB_URL"]) as connection:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cursor.execute("""CREATE TABLE IF NOT EXISTS property_knowledge (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(), category text,
                content text NOT NULL, embedding vector(384)
            );""")
    connection.close()
    print("Schema ready.")
