"""Leasing portal with complete session-scoped agent history."""
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

load_dotenv()
try:
    for key in ("SUPABASE_DB_URL", "GROQ_API_KEY", "RESEND_API_KEY", "GROQ_MODEL", "GROQ_FALLBACK_MODEL", "ANALYTICS_ENABLED", "ANALYTICS_MODE"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = str(st.secrets[key])
except FileNotFoundError:
    pass

from agent3 import leasing_app, search_vacant_units, upsert_lead
from leasing_utils import PROPERTY_NAME, PROPERTY_ADDRESS, OFFICE_HOURS, osm_embed_url
from leasing_analytics import begin_request, finish_request, save_feedback, enabled as analytics_enabled
from chat_suggestions import SUGGESTED_QUESTIONS


st.set_page_config(page_title=f"{PROPERTY_NAME} | Leasing", page_icon=":material/apartment:", layout="wide")
st.title(PROPERTY_NAME)
st.caption(PROPERTY_ADDRESS)
st.caption("Fictional community demo. Sample inventory, policies, contact number and illustrative photos.")


def as_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def render_units(units):
    for unit in units:
        with st.container(border=True):
            st.subheader(f"Unit {unit['unit_number']}")
            st.write(f"${float(unit['rent_usd']):,.0f}/month | {unit['bedrooms']} bed | {unit['bathrooms']} bath | {unit['sqft']} sq ft")
            if unit.get("special_offer"):
                st.success(unit["special_offer"])
            photos = as_list(unit.get("photos"))
            if photos:
                st.image(photos[0], width="stretch", caption="Illustrative photo")
            amenities = as_list(unit.get("amenities"))
            if amenities:
                st.caption(" | ".join(str(a) for a in amenities[:6]))


@st.fragment(run_every="1s")
def render_hold(payload):
    remaining = max(0, int((datetime.fromisoformat(payload["expires_at"]) - datetime.now(timezone.utc)).total_seconds()))
    if remaining:
        st.info(f"Unit {payload['unit_number']} held for {payload['prospect_name']}: {remaining // 60:02d}:{remaining % 60:02d} remaining")
    else:
        st.caption(f"Hold for Unit {payload['unit_number']} expired.")


def render_tool(message, index):
    content = str(message.content)
    try:
        if message.name == "search_vacant_units":
            render_units(as_list(content))
        elif content.startswith("TOUR_CONFIRMED::"):
            payload, _ = json.JSONDecoder().raw_decode(content.removeprefix("TOUR_CONFIRMED::"))
            st.success(f"Unit {payload['unit_number']}: {payload['scheduled_display']}")
            st.download_button("Add to calendar", payload["ics"], file_name=payload["filename"], mime="text/calendar", key=f"calendar_{index}", icon=":material/calendar_month:")
        elif content.startswith("VIP_HOLD_INITIALIZED::"):
            payload, _ = json.JSONDecoder().raw_decode(content.removeprefix("VIP_HOLD_INITIALIZED::"))
            render_hold(payload)
    except (ValueError, KeyError, TypeError):
        st.caption("The result could not be displayed. Please check availability again.")


st.session_state.setdefault("agent_messages", [])
st.session_state.setdefault("inventory", [])
st.session_state.setdefault("analytics_session_id", str(uuid4()))
st.session_state.setdefault("feedback_request", None)


def record_rating(request, key):
    selected = st.session_state.get(key)
    saved = save_feedback(request, None if selected is None else selected + 1)
    st.session_state.feedback_notice = "Rating saved." if saved else "Rating could not be saved. Please try again."


left, right = st.columns([1, 1.2], gap="large")
with left:
    inventory_tab, location_tab, contact_tab = st.tabs(["Available Homes", "Location", "Contact"])
    with inventory_tab:
        with st.form("inventory_search"):
            beds = st.selectbox("Bedrooms", ["Any", "Studio", "1", "2", "3", "4"])
            budget = st.number_input("Maximum monthly rent ($)", min_value=0, value=3000, step=100)
            number = st.text_input("Unit number (optional)")
            specials = st.checkbox("Move-in specials only")
            page = st.number_input("Results page", min_value=1, value=1, step=1)
            searched = st.form_submit_button("Search homes", icon=":material/search:")
        if searched:
            tracking = begin_request(st.session_state.analytics_session_id, "inventory", task="search")
            try:
                result = search_vacant_units.invoke({"max_rent": budget or None, "bedrooms": None if beds == "Any" else 0 if beds == "Studio" else int(beds), "unit_number": number or None, "specials_only": specials, "page": page})
                st.session_state.inventory = as_list(result)
                if not st.session_state.inventory:
                    st.info(result)
                finish_request(tracking, tool_result=("search_vacant_units", result))
            except Exception:
                st.session_state.inventory = []
                st.error("Inventory is temporarily unavailable. Please try again later.")
                finish_request(tracking, error="exception")
        if st.session_state.inventory:
            first = st.session_state.inventory[0]
            total = int(first.get("total_matches", len(st.session_state.inventory)))
            size = int(first.get("page_size", 5))
            st.caption(f"{total} matching homes | Page {first.get('page', 1)} of {(total + size - 1) // size}")
        render_units(st.session_state.inventory)
    with location_tab:
        st.write(OFFICE_HOURS)
        st.iframe(osm_embed_url(), height=320)
        st.link_button("Open map", "https://www.openstreetmap.org/?mlat=29.9437&mlon=-90.0749#map=16/29.9437/-90.0749", icon=":material/map:")
    with contact_tab:
        with st.form("lead"):
            name = st.text_input("Full name")
            email = st.text_input("Email")
            phone = st.text_input("Phone (optional)")
            preferred = st.selectbox("Preferred bedrooms", ["Any", "Studio", "1", "2", "3", "4"])
            maximum = st.number_input("Monthly budget ($)", min_value=0, value=2500, step=100)
            consent = st.checkbox("I agree to save these details and be contacted about apartments.")
            submitted = st.form_submit_button("Request contact", icon=":material/send:")
        if submitted:
            if not consent:
                st.warning("Consent is required to save contact details.")
            else:
                tracking = begin_request(st.session_state.analytics_session_id, "contact", task="lead")
                try:
                    outcome = upsert_lead(name, email, phone or None, None if preferred == "Any" else 0 if preferred == "Studio" else int(preferred), maximum or None)
                    if outcome.startswith("Lead captured"):
                        st.success("Your contact request has been saved.")
                    else:
                        st.warning(outcome)
                    finish_request(tracking, tool_result=("capture_prospect_lead", outcome))
                except Exception:
                    st.error("Your request could not be saved. Please try again later.")
                    finish_request(tracking, error="exception")

with right:
    st.subheader("Leasing Concierge")
    if st.button("Clear conversation", icon=":material/delete:"):
        st.session_state.agent_messages = []
        st.session_state.feedback_request = None
        st.session_state.pop("feedback_notice", None)
        st.rerun()
    chat_ready = bool(os.getenv("GROQ_API_KEY"))
    suggested_prompt = None
    suggestion_index = None
    suggestion_columns = st.columns(2)
    for index, (question, icon) in enumerate(SUGGESTED_QUESTIONS):
        if suggestion_columns[index % 2].button(
            question, key=f"suggestion_{index}", icon=icon,
            width="stretch", disabled=not chat_ready,
        ):
            suggested_prompt = question
            suggestion_index = index
    chat_viewport = st.container(height=560)
    with chat_viewport:
        if not st.session_state.agent_messages:
            st.write("Welcome. What are you looking for in your next home?")
        for index, message in enumerate(st.session_state.agent_messages):
            if isinstance(message, ToolMessage):
                render_tool(message, index)
            elif isinstance(message, HumanMessage) or (isinstance(message, AIMessage) and not message.tool_calls):
                with st.chat_message("user" if isinstance(message, HumanMessage) else "assistant"):
                    st.markdown(message.content)
        feedback_request = st.session_state.feedback_request
        if feedback_request is not None and analytics_enabled():
            st.caption("How helpful was this reply?")
            feedback_key = f"rating_{feedback_request.id}"
            st.feedback("stars", key=feedback_key, on_change=record_rating, args=(feedback_request, feedback_key))
            if st.session_state.get("feedback_notice"):
                st.caption(st.session_state.feedback_notice)
    typed_prompt = st.chat_input("Ask about apartments, policies or tour times", disabled=not chat_ready, submit_mode="disable")
    prompt = suggested_prompt or typed_prompt
    if not chat_ready:
        st.info("Chat is temporarily unavailable.")
    if prompt:
        tracking = begin_request(
            st.session_state.analytics_session_id,
            "suggested" if suggested_prompt else "typed", suggestion_index,
        )
        st.session_state.feedback_request = None
        st.session_state.pop("feedback_notice", None)
        interrupted = False
        history = st.session_state.agent_messages + [HumanMessage(content=prompt)]
        st.session_state.agent_messages = history
        with chat_viewport:
            with st.chat_message("user"):
                st.markdown(prompt)
        try:
            with st.spinner("Checking your request..."):
                for snapshot in leasing_app.stream({"messages": history}, stream_mode="values", config={"recursion_limit": 20}):
                    st.session_state.agent_messages = snapshot["messages"]
        except Exception:
            interrupted = True
            messages = st.session_state.agent_messages
            answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
            for m in list(messages):
                if isinstance(m, AIMessage):
                    for call in m.tool_calls:
                        if call["id"] not in answered:
                            messages.append(ToolMessage(content="Outcome unknown after interruption. Do not retry a booking or hold automatically.", tool_call_id=call["id"], name=call["name"]))
            messages.append(AIMessage(content="The request was interrupted. A booking or hold may have completed; please check before trying it again."))
        if finish_request(tracking, st.session_state.agent_messages, error="interrupted" if interrupted else None):
            st.session_state.feedback_request = tracking
        st.rerun()
