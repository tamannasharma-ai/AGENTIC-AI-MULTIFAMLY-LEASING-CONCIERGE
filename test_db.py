import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("SUPABASE_DB_URL")

try:
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT unit_number, bedrooms, rent_usd, status FROM units WHERE status = 'vacant';")
        units = cur.fetchall()
        print(" Connected successfully! Vacant units found:")
        for u in units:
            print(f" • Unit {u['unit_number']} | {u['bedrooms']} Bed | ${u['rent_usd']}/mo")
    conn.close()
except Exception as e:
    print(f" Connection failed: {e}")