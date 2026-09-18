"""Repair the original 400-sq-ft demo rows, preserving operational records."""
import json
import os

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv

from leasing_utils import photos_for_bedrooms


def fictional_details(number, beds):
    floor, position = divmod(int(number), 100)
    variant = (position * 3 + floor * 2) % 9
    base_size = {0: 460, 1: 660, 2: 960, 3: 1360}[beds]
    step = {0: 15, 1: 25, 2: 35, 3: 40}[beds]
    sqft = base_size + variant * step
    baths = 1 if beds <= 1 else (1.5 if beds == 2 and sqft < 1100 else 2)
    if beds == 3 and sqft >= 1560:
        baths = 2.5
    base_rent = {0: 1150, 1: 1450, 2: 1950, 3: 2700}[beds]
    rent = base_rent + round((sqft - base_size) * 1.5 / 25) * 25 + (floor - 1) * 35
    amenities = ["central-ac", "dishwasher", "in-unit-laundry"]
    if position % 2 == 0:
        amenities.append("walk-in-closet")
    if floor == 1 and position % 3 == 0:
        amenities.append("patio")
        rent += 50
    elif floor > 1 and position % 3 == 0:
        amenities.append("balcony")
        rent += 75
    if position in (1, 12):
        amenities.append("corner-unit")
        rent += 50
    return sqft, baths, rent, amenities


def main():
    load_dotenv()
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10,
                            cursor_factory=RealDictCursor)
    numbers = [str(floor * 100 + position) for floor in range(1, 6) for position in range(1, 13)]
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30s'")
                cur.execute("SELECT * FROM units WHERE unit_number = ANY(%s) ORDER BY unit_number FOR UPDATE", (numbers,))
                rows = cur.fetchall()
                affected = [r for r in rows if r["sqft"] == 400]
                cur.execute("""CREATE TABLE IF NOT EXISTS demo_inventory_backup (
                    unit_id uuid PRIMARY KEY, original_row jsonb NOT NULL,
                    backed_up_at timestamptz NOT NULL DEFAULT now())""")
                for row in affected:
                    size, baths, rent, amenities = fictional_details(row["unit_number"], row["bedrooms"])
                    assert size > 400 and rent > 0 and baths >= 1
                    cur.execute("""INSERT INTO demo_inventory_backup(unit_id, original_row)
                        VALUES (%s, %s) ON CONFLICT (unit_id) DO NOTHING""",
                        (row["id"], Json(dict(row), dumps=lambda obj: json.dumps(obj, default=str))))
                    cur.execute("""UPDATE units SET sqft=%s, bathrooms=%s, rent_usd=%s,
                        amenities=%s, photos=%s WHERE id=%s""",
                        (size, baths, rent, Json(amenities), Json(photos_for_bedrooms(row["bedrooms"])), row["id"]))
                cur.execute("SELECT * FROM units WHERE unit_number = ANY(%s) ORDER BY unit_number", (numbers,))
                updated = cur.fetchall()
                preserved = ("id", "unit_number", "building", "floor", "bedrooms", "status", "vacant_since", "available_from")
                assert len(updated) == len(rows)
                for before, after in zip(rows, updated):
                    assert all(before[k] == after[k] for k in preserved)
                    assert after["sqft"] > 400
                cur.execute("""SELECT bedrooms, count(*) AS units, min(sqft) AS min_sqft,
                    max(sqft) AS max_sqft, min(rent_usd) AS min_rent, max(rent_usd) AS max_rent
                    FROM units WHERE unit_number=ANY(%s) GROUP BY bedrooms ORDER BY bedrooms""", (numbers,))
                summary = cur.fetchall()
        print(json.dumps({"updated": len(affected), "summary": summary,
                          "backup_table": "demo_inventory_backup"}, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
