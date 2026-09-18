import os
import json
from datetime import datetime, timezone

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

from db_schema import ensure_schema
from leasing_utils import photos_for_bedrooms, staggered_vacant_since

load_dotenv()

CSV_FILE = "apartments_for_rent_classified_10K.csv"
DB_URL = os.getenv("SUPABASE_DB_URL")


def clean_and_ingest():
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: Could not find '{CSV_FILE}' in the current folder.")
        return

    print(f"📂 Reading {CSV_FILE}...")

    try:
        df = pd.read_csv(CSV_FILE, sep=";", encoding="latin-1", low_memory=False)
    except Exception:
        df = pd.read_csv(CSV_FILE, sep=",", encoding="utf-8", low_memory=False)

    print(f"📊 Total raw rows loaded: {len(df)}")

    df = df.dropna(subset=["price", "square_feet", "bedrooms", "bathrooms"])
    df = df[
        (df["price"] >= 800)
        & (df["price"] <= 6000)
        & (df["square_feet"] >= 400)
        & (df["square_feet"] <= 3500)
        & (df["bedrooms"] >= 0)
        & (df["bedrooms"] <= 4)
        & (df["bathrooms"] >= 1)
    ]

    sample_df = df.head(60).copy()
    now = datetime.now(timezone.utc)
    records = []
    unit_counter = 101

    for idx, (_, row) in enumerate(sample_df.iterrows()):
        raw_amenities = str(row.get("amenities", ""))
        if raw_amenities != "nan" and raw_amenities.strip():
            amenity_list = [a.strip().lower() for a in raw_amenities.split(",") if a.strip()]
        else:
            amenity_list = ["hardwood-floors", "central-ac"]

        unit_number = str(unit_counter)
        floor = int(unit_number[0])
        bedrooms = int(row["bedrooms"])
        bathrooms = float(row["bathrooms"])
        sqft = int(row["square_feet"])
        rent_usd = float(row["price"])

        records.append(
            (
                unit_number,
                "Main Building",
                floor,
                bedrooms,
                bathrooms,
                sqft,
                rent_usd,
                "vacant",
                json.dumps(amenity_list),
                json.dumps(photos_for_bedrooms(bedrooms)),
                staggered_vacant_since(idx, now=now),
            )
        )

        unit_counter += 1
        if unit_counter % 100 > 12:
            unit_counter = ((unit_counter // 100) + 1) * 100 + 1

    print(f"🚀 Upserting {len(records)} apartment units into Supabase...")

    conn = psycopg2.connect(DB_URL)
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            insert_query = """
                INSERT INTO units (
                    unit_number, building, floor, bedrooms, bathrooms,
                    sqft, rent_usd, status, amenities, photos, vacant_since
                ) VALUES %s
                ON CONFLICT (unit_number) DO NOTHING;
            """
            execute_values(cur, insert_query, records)
            conn.commit()
    finally:
        conn.close()

    print("✅ Ingestion complete. Existing tours and VIP holds were preserved.")


if __name__ == "__main__":
    clean_and_ingest()
