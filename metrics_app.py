"""Staff analytics, served separately and restricted to a loopback listener."""

import os
from datetime import datetime, timedelta, timezone

import streamlit as st
from dotenv import load_dotenv

from chat_suggestions import SUGGESTED_QUESTIONS
from leasing_analytics import load_events, summarize

load_dotenv()
st.set_page_config(page_title="Leasing metrics", page_icon=":material/monitoring:", layout="wide")
st.title("Leasing metrics")

# Fail closed if someone starts this staff surface on a public network interface.
# A reverse proxy or tunnel must NOT expose this listener without real authentication.
if st.get_option("server.address") not in {"127.0.0.1", "::1"}:
    st.error("Staff metrics require a local-only server. See the README launch command.")
    st.stop()


@st.cache_data(ttl=30, max_entries=16, show_spinner=False)
def fetch_events(mode, start, end):
    return load_events(mode, start, end)


def percentage(numerator, denominator):
    return f"{100 * numerator / denominator:.1f}%" if denominator else "N/A"


today = datetime.now(timezone.utc).date()
default_mode = os.getenv("ANALYTICS_MODE", "demo")
with st.sidebar:
    st.subheader("Reporting period")
    mode = st.selectbox("Traffic", ["demo", "live", "test"], index=["demo", "live", "test"].index(default_mode) if default_mode in {"demo", "live", "test"} else 0)
    dates = st.date_input("Dates (UTC)", value=(today - timedelta(days=29), today), max_value=today)
    if st.button("Refresh", icon=":material/refresh:"):
        fetch_events.clear()
    st.caption("Random session IDs. No names, emails or chat transcripts.")
if len(dates) != 2:
    st.info("Select a start and end date.")
    st.stop()
start = datetime.combine(dates[0], datetime.min.time(), timezone.utc)
end = datetime.combine(dates[1] + timedelta(days=1), datetime.min.time(), timezone.utc)
st.caption(f"{mode.capitalize()} traffic | {dates[0]:%d %b %Y} to {dates[1]:%d %b %Y} | UTC")
try:
    with st.spinner("Loading metrics..."):
        events = fetch_events(mode, start, end)
except ValueError as exc:
    st.warning(str(exc))
    st.stop()
except Exception:
    st.error("Metrics are unavailable. Check the database connection and analytics schema.")
    st.stop()

if events.empty:
    st.info("No recorded activity in this period.")
    st.stop()

report = summarize(events)
with st.container(horizontal=True):
    st.metric("Requests", report["requests"], help="Chat turns, submitted inventory searches and consented contact requests.")
    st.metric("Sessions", report["sessions"], help="Browser sessions, not unique people. A reconnect can create another session.")
    st.metric("Tool-backed completion", percentage(report["completed_requests"], report["requests"]), help=f"{report['completed_requests']} of {report['requests']} requests completed all invoked tools. Correct empty searches count. Conversational replies and clarification are not verified completion.")
    st.metric("Requests with errors", percentage(report["errors"], report["requests"]), help=f"{report['errors']} of {report['requests']} requests. Validation rejections are separate from technical errors.")

st.subheader("Search to tour")
with st.container(horizontal=True):
    st.metric("Searching sessions", report["search_sessions"])
    st.metric("Search-to-tour sessions", percentage(report["converted_sessions"], report["search_sessions"]), help=f"{report['converted_sessions']} of {report['search_sessions']} searching sessions had a later recorded booking in the selected period. Repeat tours count once per session.")
    st.metric("Tracked tours booked", report["bookings"], help="Distinct confirmed tour IDs recorded by analytics; not the entire historical tour inventory.")
    st.metric("Unfinished requests", report["unfinished"], help="A start was recorded without a finish. This can mean in progress, interruption or telemetry loss, not proven abandonment.")

st.subheader("Completion by task and source")
if not report["by_task"].empty:
    st.dataframe(report["by_task"].rename(columns={
        "task": "Task", "source": "Source", "attempts": "Tool attempts",
        "completed": "Completed", "completion_percent": "Completed (%)",
    }).round(1), hide_index=True)
else:
    st.caption("No recorded tool calls.")
st.caption(f"{report['unverified']} requests have a reply or unknown outcome without verified tool completion. Operational completion is not audited answer accuracy.")

st.subheader("Processing time")
st.caption("Seconds per finished request. Includes failed requests; excludes analytics writes and browser rendering.")
st.dataframe(report["speed"].rename(columns={
    "source": "Source", "samples": "Samples", "p50_seconds": "Median (s)", "p95_seconds": "95th percentile (s)",
}).round(2), hide_index=True)

st.subheader("Suggested prompts")
suggestions = report["suggestions"].copy()
if not suggestions.empty:
    suggestions["suggestion_index"] = suggestions.suggestion_index.map(lambda i: SUGGESTED_QUESTIONS[int(i)][0])
    st.dataframe(suggestions.rename(columns={
        "suggestion_index": "Prompt", "clicks": "Clicks", "tool_complete": "Tool-complete requests",
        "completion_percent": "Completed (%)",
    }).round(1), hide_index=True)
else:
    st.caption("No suggested prompts selected in this period.")

st.subheader("Helpfulness and effort")
with st.container(horizontal=True):
    mean_rating = report["mean_rating"]
    st.metric("Helpfulness", "N/A" if mean_rating is None else f"{mean_rating:.1f} / 5", help=f"{report['ratings']} rated replies; voluntary feedback can be biased.")
    st.metric("Rated replies", report["ratings"])
    st.metric("Reply rating coverage", percentage(report["ratings"], report["chat_requests"]))
    turns = report["median_chat_turns"]
    st.metric("Median chat turns / session", "N/A" if turns is None else f"{turns:.1f}", help="Within this reporting period; not messages needed to complete a goal.")

st.subheader("Daily requests")
st.bar_chart(report["daily"], x="day", x_label="Date (UTC)", y_label="Requests")
if not report["errors_by_category"].empty:
    st.subheader("Recorded errors")
    st.dataframe(report["errors_by_category"].rename(columns={"category": "Category", "requests": "Requests"}), hide_index=True)

st.subheader("Not yet measured")
st.caption("Independent answer accuracy, tour attendance, applications, leases and production booking integrity require reviewed outcomes. They are not inferred from chat activity.")
st.download_button("Export events", events.to_csv(index=False), "leasing-metrics.csv", "text/csv", icon=":material/download:")
