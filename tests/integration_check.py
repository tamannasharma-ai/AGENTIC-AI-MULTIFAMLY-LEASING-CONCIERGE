"""Manual PostgreSQL integration check. All test data and tables are rolled back."""
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

import agent3
from db_schema import SCHEMA_STATEMENTS
from leasing_utils import next_open_tour_slots


class TransactionConnection:
    """Keep tool commits inside the disposable outer transaction."""
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        pass

    def close(self):
        pass

    def rollback(self):
        raise RuntimeError("A tool failed; abort integration check")


def main():
    load_dotenv()
    connection = psycopg2.connect(os.environ["SUPABASE_DB_URL"], cursor_factory=RealDictCursor, connect_timeout=10)
    schema = "leasing_check_" + uuid.uuid4().hex
    try:
        with connection.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema)))
            for statement in SCHEMA_STATEMENTS:
                cur.execute(statement)
            for number in range(101, 113):
                cur.execute("""INSERT INTO units(unit_number,bedrooms,bathrooms,sqft,rent_usd,vacant_since,available_from)
                    VALUES (%s,1,1,750,%s,now()-interval '65 days',current_date)""", (str(number),1500+number))
            cur.execute("SELECT count(*) AS n FROM information_schema.columns WHERE table_schema=%s AND table_name='units' AND column_name='available_from'", (schema,))
            assert cur.fetchone()["n"] == 1
        proxy = TransactionConnection(connection)
        with patch.object(agent3, "get_db_connection", return_value=proxy), patch.object(agent3, "dispatch_tour_confirmation_email", return_value={}) as mail:
            page1 = json.loads(agent3.search_vacant_units.invoke({"specials_only": True}))
            page2 = json.loads(agent3.search_vacant_units.invoke({"specials_only": True, "page":2}))
            assert page1[0]["total_matches"] == 12
            assert not {u["unit_number"] for u in page1} & {u["unit_number"] for u in page2}
            assert len(json.loads(agent3.search_vacant_units.invoke({"unit_number":"112"}))) == 1
            hold = agent3.create_reservation_hold.invoke({"unit_number":"101","prospect_name":"Integration Demo","prospect_email":"integration@example.com"})
            data, _ = json.JSONDecoder().raw_decode(hold.removeprefix("VIP_HOLD_INITIALIZED::"))
            slot = next_open_tour_slots([],count=1)[0].isoformat()
            booking = dict(unit_number="101", prospect_name="Integration Demo", prospect_email="integration@example.com", date_time=slot)
            assert "cannot be scheduled" in agent3.book_tour_appointment.invoke(booking)
            booking["reservation_id"] = data["reservation_id"]
            assert "TOUR_CONFIRMED::" in agent3.book_tour_appointment.invoke(booking)
            assert "Time Conflict" in agent3.book_tour_appointment.invoke(booking)
            mail.assert_called_once()
            with connection.cursor() as cur:
                cur.execute("UPDATE reservations SET status='pending',expires_at=now()-interval '1 minute'")
            agent3.cleanup_expired_reservations(proxy)
            with connection.cursor() as cur:
                cur.execute("SELECT status FROM units WHERE unit_number='101'")
                assert cur.fetchone()["status"] == "vacant"
                cur.execute("SELECT status FROM reservations")
                assert cur.fetchone()["status"] == "expired"
        print("PASS: fresh schema, pagination, specials, unit lookup, hold ownership, booking, conflicts and legacy expiry. Email mocked; all SQL changes rolled back.")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
