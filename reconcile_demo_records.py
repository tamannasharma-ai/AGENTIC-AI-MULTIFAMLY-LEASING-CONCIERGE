"""Back up and reconcile inconsistent records in the fictional demo database."""
import json
import os
from datetime import timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from leasing_utils import validate_tour_time, has_tour_collision, next_open_tour_slots


def main():
    load_dotenv()
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10,
                            cursor_factory=RealDictCursor)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                cur.execute("SELECT pg_advisory_xact_lock(702101)")
                cur.execute("LOCK TABLE tours, reservations, units IN SHARE ROW EXCLUSIVE MODE")
                cur.execute("""CREATE TABLE IF NOT EXISTS demo_reconciliation_backup (
                    source_table text NOT NULL, row_id uuid NOT NULL, original_row jsonb NOT NULL,
                    backed_up_at timestamptz DEFAULT now(), PRIMARY KEY(source_table,row_id))""")
                for table in ("tours", "reservations", "units"):
                    from psycopg2 import sql
                    cur.execute(sql.SQL("""INSERT INTO demo_reconciliation_backup(source_table,row_id,original_row)
                        SELECT %s,id,to_jsonb(t) FROM {} t ON CONFLICT DO NOTHING""").format(sql.Identifier(table)), (table,))
                cur.execute("SELECT now() AS moment")
                now = cur.fetchone()["moment"]
                cur.execute("UPDATE reservations SET status='expired' WHERE status IN ('pending','held') AND expires_at <= now()")
                expired = cur.rowcount
                cur.execute("""UPDATE units u SET status='vacant' WHERE u.status IN ('held','reserved')
                    AND EXISTS (SELECT 1 FROM reservations r WHERE r.unit_id=u.id AND r.status='expired')
                    AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.unit_id=u.id AND
                        (r.status='confirmed' OR (r.status IN ('held','pending') AND
                            (r.expires_at IS NULL OR r.expires_at>now()))))""")
                cur.execute("SELECT id,scheduled_at FROM tours ORDER BY scheduled_at,id")
                tours = cur.fetchall()
                accepted, repair = [], []
                for tour in tours:
                    start = tour["scheduled_at"]
                    try:
                        validate_tour_time(start, now=start-timedelta(hours=2))
                        if has_tour_collision(start, accepted):
                            raise ValueError("Overlap")
                    except ValueError:
                        repair.append(tour)
                    else:
                        accepted.append(start)
                for tour in repair:
                    slots = next_open_tour_slots(accepted, count=1, now=now)
                    if not slots:
                        raise RuntimeError("No replacement slots available; rolling back")
                    cur.execute("UPDATE tours SET scheduled_at=%s WHERE id=%s", (slots[0],tour["id"]))
                    accepted.append(slots[0])
                cur.execute("SELECT count(*) AS n FROM tours a JOIN tours b ON a.id<b.id AND abs(extract(epoch FROM (a.scheduled_at-b.scheduled_at)))<2700")
                if cur.fetchone()["n"]:
                    raise RuntimeError("Conflicts remain; rolling back")
        print(json.dumps({"expired_reservations": expired, "rescheduled_demo_tours": len(repair),
                          "backup": "demo_reconciliation_backup", "notifications_sent": 0}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
