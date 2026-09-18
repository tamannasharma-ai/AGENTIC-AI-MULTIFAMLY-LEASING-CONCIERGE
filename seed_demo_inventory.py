"""Add consistent fictional inventory without overwriting existing records."""
import json
import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
from dotenv import load_dotenv

from leasing_utils import photos_for_bedrooms
from diversify_demo_inventory import fictional_details
from db_schema import ensure_schema

# Unit, bedrooms, bathrooms, square feet, monthly rent, days vacant.
DEMO_UNITS = [
    ("601", 0, 1, 510, 1250, 12),
    ("602", 0, 1, 550, 1325, 48),
    ("603", 1, 1, 710, 1575, 22),
    ("604", 1, 1, 760, 1650, 52),
    ("605", 1, 1, 820, 1775, 65),
    ("606", 2, 2, 1050, 2150, 10),
    ("607", 2, 2, 1120, 2275, 47),
    ("608", 2, 2, 1200, 2425, 72),
    ("609", 2, 2, 1280, 2550, 30),
    ("610", 3, 2, 1420, 2850, 18),
    ("611", 3, 2, 1510, 3050, 55),
    ("612", 3, 2.5, 1650, 3275, 80),
]

# Preserve the curated floor mix when recreating this demo on a fresh database.
FLOOR_BEDS = [
    [2, 0, 1, 0, 1, 2, 0, 1, 1, 1, 0, 1],
    [1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1],
    [1, 1, 2, 1, 2, 2, 1, 2, 2, 1, 2, 1],
    [1, 1, 3, 0, 1, 1, 2, 0, 1, 1, 1, 1],
    [3, 1, 1, 1, 2, 0, 0, 0, 1, 2, 1, 1],
]
for floor, bed_counts in enumerate(FLOOR_BEDS, 1):
    for position, beds in enumerate(bed_counts, 1):
        number = str(floor * 100 + position)
        sqft, baths, rent, _ = fictional_details(number, beds)
        DEMO_UNITS.append((number, beds, baths, sqft, rent, [8, 18, 32, 48, 62, 80][position % 6]))


def seed():
    load_dotenv()
    now = datetime.now(timezone.utc)
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10)
    try:
        ensure_schema(conn)
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30s'")
                # Preserve the original allowed states while adding the app's hold state.
                for table, expected, name, allowed in [
                    ("units", {"vacant", "reserved", "leased"}, "units_status_check",
                     ["vacant", "reserved", "leased", "held"]),
                    ("reservations", {"pending", "confirmed", "expired"}, "reservations_status_check",
                     ["pending", "confirmed", "expired", "held"]),
                ]:
                    cur.execute("""SELECT conname, pg_get_constraintdef(oid)
                        FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'c'""", (table,))
                    import re
                    for constraint, definition in cur.fetchall():
                        if "status" in definition and set(re.findall(r"'([^']+)'", definition)) == expected:
                            cur.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(sql.Identifier(table), sql.Identifier(constraint)))
                            cur.execute(sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} CHECK (status = ANY ({}))").format(
                                sql.Identifier(table), sql.Identifier(name), sql.Literal(allowed)))

                inserted = []
                for number, beds, baths, sqft, rent, days in DEMO_UNITS:
                    amenities = ["central-ac", "in-unit-laundry", "dishwasher"]
                    if beds >= 2:
                        amenities.append("balcony")
                    floor = int(number) // 100
                    if floor < 6:
                        _, _, _, amenities = fictional_details(number, beds)
                    cur.execute("""INSERT INTO units
                        (unit_number, building, floor, bedrooms, bathrooms, sqft,
                         rent_usd, status, amenities, photos, vacant_since, available_from)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'vacant', %s, %s, %s, %s)
                        ON CONFLICT (unit_number) DO NOTHING RETURNING unit_number""",
                        (number, "Demo Wing (fictional)" if floor == 6 else "Main Building", floor, beds, baths, sqft, rent,
                         Json(amenities), Json(photos_for_bedrooms(beds)),
                         now - timedelta(days=days), (now - timedelta(days=days)).date()))
                    row = cur.fetchone()
                    if row:
                        inserted.append(row[0])
                cur.execute("""SELECT unit_number, bedrooms, bathrooms, sqft, rent_usd,
                    status, jsonb_array_length(photos) FROM units
                    WHERE unit_number = ANY(%s) ORDER BY unit_number""",
                    ([u[0] for u in DEMO_UNITS],))
                verified = cur.fetchall()
                if len(verified) != len(DEMO_UNITS):
                    raise RuntimeError("Incomplete demo inventory; transaction rolled back")
                print(json.dumps({"inserted": inserted, "verified_units": verified}, default=str))
        print("Committed. Existing inventory and prospect records preserved.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
