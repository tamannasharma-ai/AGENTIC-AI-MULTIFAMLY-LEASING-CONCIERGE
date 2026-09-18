import argparse
import os
from datetime import datetime

import pandas as pd
import psycopg2
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from db_schema import ensure_schema

load_dotenv()

RENTCAST_API_KEY = os.getenv("RENTCAST_API_KEY")
DB_URL = os.getenv("SUPABASE_DB_URL")
LOCAL_DUMP_DIR = "rentcast_daily_dumps"


def pull_weekly_rentcast_comps(zip_code: str = "70113", limit: int = 25):
    """
    Pull nearby RentCast listings into market_comps (does not replace community units).
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Running RentCast market-comps pull...")

    if not RENTCAST_API_KEY:
        print("❌ Error: RENTCAST_API_KEY is not defined in .env")
        return

    url = "https://api.rentcast.io/v1/listings/rental/long-term"
    headers = {
        "accept": "application/json",
        "X-Api-Key": RENTCAST_API_KEY,
    }
    params = {
        "zipCode": zip_code,
        "status": "Active",
        "propertyType": "Apartment",
        "limit": limit,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            print(f"❌ RentCast API error ({response.status_code}): {response.text}")
            return
        listings = response.json()
    except Exception as e:
        print(f"❌ RentCast request failed: {e}")
        return

    if not listings:
        print("⚠️ No active listings found for the specified criteria.")
        return

    print(f"📦 Retrieved {len(listings)} active rental listings.")

    os.makedirs(LOCAL_DUMP_DIR, exist_ok=True)
    dated_csv_path = os.path.join(
        LOCAL_DUMP_DIR, f"rentcast_dump_{zip_code}_{date_str}_{timestamp_str}.csv"
    )
    latest_csv_path = os.path.join(LOCAL_DUMP_DIR, "rentcast_dump_latest.csv")
    df = pd.DataFrame(listings)
    df.to_csv(dated_csv_path, index=False)
    df.to_csv(latest_csv_path, index=False)
    print(f"💾 Local CSV written:\n   • {dated_csv_path}\n   • {latest_csv_path}")

    records = []
    for item in listings:
        records.append(
            (
                str(item.get("id") or item.get("formattedAddress") or ""),
                zip_code,
                item.get("formattedAddress") or item.get("addressLine1") or "",
                int(item["bedrooms"]) if item.get("bedrooms") is not None else None,
                float(item.get("bathrooms") or 1.0),
                int(item.get("squareFootage") or 0) or None,
                float(item.get("price") or 0) or None,
            )
        )

    conn = psycopg2.connect(DB_URL)
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM market_comps WHERE zip_code = %s;", (zip_code,))
            insert_query = """
                INSERT INTO market_comps (
                    listing_id, zip_code, address, bedrooms, bathrooms, sqft, rent_usd
                ) VALUES %s;
            """
            execute_values(cur, insert_query, records)
            conn.commit()
            print(f"✅ market_comps refreshed with {len(records)} nearby listings.")
    except Exception as db_err:
        conn.rollback()
        print(f"❌ Database error syncing comps: {db_err}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RentCast market comps worker")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Stay running and pull weekly on Sunday 03:00 (local).",
    )
    args = parser.parse_args()

    pull_weekly_rentcast_comps()

    if not args.schedule:
        raise SystemExit(0)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        pull_weekly_rentcast_comps,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="weekly_rentcast_comps",
    )
    print("\n⏰ Weekly RentCast scheduler active (Sunday 03:00). Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Worker stopped.")
