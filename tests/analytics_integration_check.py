"""Opt-in PostgreSQL check. All tables and events live in a rolled-back schema."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import leasing_analytics as analytics


class TransactionConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass


def main():
    load_dotenv()
    connection = psycopg2.connect(os.environ["SUPABASE_DB_URL"], cursor_factory=RealDictCursor, connect_timeout=5)
    schema = "analytics_check_" + uuid4().hex
    try:
        with connection.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            for _ in range(2):
                for statement in analytics.SCHEMA_STATEMENTS:
                    cur.execute(statement)
        proxy = TransactionConnection(connection)
        with patch.object(analytics, "_connect", return_value=proxy), patch.dict(os.environ, {"ANALYTICS_ENABLED": "true", "ANALYTICS_MODE": "test"}):
            request = analytics.begin_request(str(uuid4()), "typed")
            response = AIMessage(content="Private test text is never stored.", response_metadata={"model_attempted": True, "fallback_attempted": True})
            assert analytics.finish_request(request, [response])
            assert analytics.finish_request(request, [response])
            assert analytics._write([request.event()])
            assert analytics.save_feedback(request, 1)
            assert analytics.save_feedback(request, 5)
            now = datetime.now(timezone.utc)
            events = analytics.load_events("test", now - timedelta(days=1), now + timedelta(days=1))
            assert len(events) == 2
            report = analytics.summarize(events)
            assert report["requests"] == report["ratings"] == 1
            assert report["mean_rating"] == 5
            assert events[events.kind == "request"].iloc[0].outcome == "answered"
            assert bool(events[events.kind == "request"].iloc[0].fallback_attempted)
            assert analytics.load_events("live", now - timedelta(days=1), now + timedelta(days=1)).empty
            assert analytics.save_feedback(request, None)
            assert len(analytics.load_events("test", now - timedelta(days=1), now + timedelta(days=1))) == 1
            assert analytics.load_demo_summary()["model_requests"] == 0
        print("Analytics PostgreSQL integration passed; all test changes rolled back.")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
