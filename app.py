"""Leasing portal with complete session-scoped agent history."""
import json
import os
from pathlib import Path
from time import perf_counter, sleep
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

load_dotenv()
try:
    for key in ("SUPABASE_DB_URL", "GROQ_API_KEY", "RESEND_API_KEY", "GROQ_MODEL", "GROQ_FALLBACK_MODEL", "ANALYTICS_ENABLED", "ANALYTICS_MODE", "DEMO_CONTROLS"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = str(st.secrets[key])
except FileNotFoundError:
    pass

from agent3 import leasing_app, search_vacant_units, upsert_lead, reset_demo_data, get_db_connection
from leasing_utils import PROPERTY_NAME, PROPERTY_ADDRESS, OFFICE_HOURS, osm_embed_url
from leasing_analytics import begin_request, finish_request, save_feedback, load_demo_summary, enabled as analytics_enabled
from chat_suggestions import SUGGESTED_QUESTIONS, BLOCKED_EXAMPLE_INDEX
from demo_features import ARCHITECTURE, ReplyStream, consume_request, demo_controls_enabled, reply_caption
from conversation_state import remember_conversation, switch_conversation
from choice_ui import save_button, render_shortlist, ask, navigate
from home_matching import AMENITIES, match_reasons, find_alternatives


st.set_page_config(page_title=f"{PROPERTY_NAME} | Leasing", page_icon=":material/apartment:", layout="wide")
st.html(Path(__file__).with_name("chat_theme.css"))
st.subheader(PROPERTY_NAME)
st.caption(f"{PROPERTY_ADDRESS} | Fictional community demo")


def as_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def render_units(units, context="inventory"):
    for position, unit in enumerate(units):
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
            if context == "inventory" and st.session_state.get("inventory_filters"):
                with st.expander("Why this home?"):
                    for reason in match_reasons(unit, st.session_state.inventory_filters):
                        st.write(reason)
                    st.caption("Based on recorded unit features. Unlisted features need confirmation.")
            save_button(unit, f"save_{context}_{position}_{unit['unit_number']}")


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
            render_units(as_list(content), f"chat_{index}")
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
st.session_state.setdefault("shortlist", {})
remember_conversation(st.session_state)


def record_rating(request, key):
    selected = st.session_state.get(key)
    saved = save_feedback(request, None if selected is None else selected + 1)
    st.session_state.feedback_notice = "Rating saved." if saved else "Rating could not be saved. Please try again."


def permit_request():
    wait = consume_request(st.session_state)
    if wait:
        st.warning(f"Too many requests. Please try again in {wait} seconds.")
    return not wait


@st.cache_data(ttl=30, max_entries=1, show_spinner=False)
def demo_summary():
    return load_demo_summary()


blocked_example_clicked = False
with st.sidebar:
    st.subheader("Leasing Concierge")
    if st.button("New chat", icon=":material/edit_square:", width="stretch"):
        switch_conversation(st.session_state)
        st.rerun()
    st.caption("RECENT CONVERSATIONS")
    for conversation_id, conversation in reversed(list(st.session_state.conversations.items())):
        if st.button(conversation["title"], key=f"conversation_{conversation_id}",
                     icon=":material/chat_bubble:", width="stretch",
                     type="primary" if conversation_id == st.session_state.conversation_id else "secondary"):
            switch_conversation(st.session_state, conversation_id)
            st.rerun()
    st.caption("Chat history lasts for this browser session.")
    if st.button("Clear conversation", icon=":material/delete:"):
        st.session_state.agent_messages = []
        st.session_state.feedback_request = None
        st.session_state.pop("feedback_notice", None)
        st.rerun()
    with st.expander("How this works", icon=":material/account_tree:"):
        st.markdown(f"```mermaid\n{ARCHITECTURE}\n```")
    st.divider()
    if demo_controls_enabled(st.get_option("server.address")):
        st.subheader("Demo controls")
        if st.button("Reset demo", icon=":material/restart_alt:", help="Clean expired holds, clear this conversation and refresh cached lookups. Active holds and tours are preserved."):
            try:
                st.session_state.reset_notice = reset_demo_data()
                st.session_state.agent_messages = []
                st.session_state.inventory = []
                for state_key in ("inventory_filters", "alternatives", "accepted_filters", "no_exact_matches"):
                    st.session_state.pop(state_key, None)
                st.session_state.feedback_request = None
                st.session_state.pop("feedback_notice", None)
                demo_summary.clear()
                st.rerun()
            except Exception:
                st.error("Reset could not be completed. Please check the database connection.")
        if st.session_state.get("reset_notice"):
            st.caption(st.session_state.reset_notice)
        st.subheader("Demo metrics")
        st.caption("Last 24 hours | Demo traffic")
        if st.button("Refresh metrics", icon=":material/refresh:"):
            demo_summary.clear()
        if analytics_enabled():
            try:
                summary = demo_summary()
                st.metric("Blocked prompts", summary["blocked"])
                question, icon = SUGGESTED_QUESTIONS[BLOCKED_EXAMPLE_INDEX]
                blocked_example_clicked = st.button(
                    question, key="blocked_prompt_example", icon=icon,
                    help="Submit a blocked-prompt example to the concierge.",
                )
                rating = summary["mean_rating"]
                st.metric("Average rating", "N/A" if rating is None else f"{float(rating):.1f} / 5", help=f"{summary['ratings']} rated replies")
                attempts = summary["model_requests"]
                st.metric("Fallback-trigger rate", "N/A" if not attempts else f"{100 * summary['fallback_requests'] / attempts:.1f}%", help=f"{summary['fallback_requests']} of {attempts} requests with recorded model attempts. A trigger does not imply a successful fallback.")
            except Exception:
                st.caption("Metrics temporarily unavailable.")
        else:
            st.caption("Analytics disabled.")
chat_tab, homes_tab, shortlist_tab, location_tab, contact_tab = st.tabs(
    ["Concierge", "Available Homes", "Shortlist", "Location", "Contact"], key="main_tab", on_change="rerun")
with shortlist_tab:
    render_shortlist(get_db_connection, permit_request, bool(os.getenv("GROQ_API_KEY")))
with homes_tab:
    inventory_tab = st.container()
    with inventory_tab:
        if st.session_state.get("accepted_filters"):
            accepted_values = st.session_state.accepted_filters
            st.session_state.search_budget = accepted_values.get("max_rent") or 0
            st.session_state.search_required = accepted_values.get("required_amenities", [])
            st.session_state.search_page = 1
        with st.form("inventory_search"):
            beds = st.selectbox("Bedrooms", ["Any", "Studio", "1", "2", "3", "4"])
            budget = st.number_input("Maximum monthly rent ($)", min_value=0.0, value=3000.0, step=100.0, key="search_budget")
            number = st.text_input("Unit number (optional)")
            specials = st.checkbox("Move-in specials only")
            required = st.multiselect("Must-have amenities", list(AMENITIES), format_func=AMENITIES.get, key="search_required")
            preferred_features = st.multiselect("Nice-to-have amenities", list(AMENITIES), format_func=AMENITIES.get)
            page = st.number_input("Results page", min_value=1, value=1, step=1, key="search_page")
            searched = st.form_submit_button("Search homes", icon=":material/search:")
        accepted = st.session_state.pop("accepted_filters", None)
        if (searched or accepted is not None) and permit_request():
            filters = accepted or {"max_rent": budget or None, "bedrooms": None if beds == "Any" else 0 if beds == "Studio" else int(beds), "unit_number": number or None, "specials_only": specials, "page": page,
                                   "required_amenities": required, "preferred_amenities": preferred_features}
            st.session_state.inventory_filters = filters
            st.session_state.pop("alternatives", None)
            st.session_state.no_exact_matches = False
            tracking = begin_request(st.session_state.analytics_session_id, "inventory", task="search")
            try:
                result = search_vacant_units.invoke(filters)
                st.session_state.inventory = as_list(result)
                st.session_state.no_exact_matches = not st.session_state.inventory and filters["page"] == 1 and result.startswith("No vacant units")
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
        if st.session_state.get("inventory_filters"):
            applied = st.session_state.inventory_filters
            st.caption(f"Applied rent limit: {'None' if applied.get('max_rent') is None else '$' + format(applied['max_rent'], ',.2f')} | Must-haves: {', '.join(AMENITIES[x] for x in applied.get('required_amenities', [])) or 'None'}")
        if st.session_state.get("no_exact_matches"):
            st.info("No exact matches. Alternatives keep your bedroom, unit-number and specials filters unchanged.")
            if st.button("Check one-change alternatives", icon=":material/tune:") and permit_request():
                st.session_state.pop("alternatives", None)
                try:
                    st.session_state.alternatives = find_alternatives(search_vacant_units.invoke, st.session_state.inventory_filters)
                except Exception:
                    st.error("Alternatives could not be checked. Please try again.")
            if "alternatives" in st.session_state:
                if not st.session_state.alternatives:
                    st.info("No one-change alternatives found. Consider revising your search.")
                for index, proposal in enumerate(st.session_state.alternatives):
                    st.write(f"{proposal['label']} | Example: Unit {proposal['unit']}")
                    if st.button("Accept change and search", key=f"alternative_{index}", icon=":material/search:"):
                        st.session_state.accepted_filters = proposal["filters"]
                        st.rerun()
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
            elif permit_request():
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

with chat_tab:
    chat_ready = bool(os.getenv("GROQ_API_KEY"))
    action_prompt = st.session_state.pop("pending_action", None)
    suggested_prompt = SUGGESTED_QUESTIONS[BLOCKED_EXAMPLE_INDEX][0] if blocked_example_clicked else None
    suggestion_index = BLOCKED_EXAMPLE_INDEX if blocked_example_clicked else None
    chat_viewport = st.container(height=560, border=False, key="chat_viewport", autoscroll=bool(st.session_state.agent_messages))
    with chat_viewport:
        if not st.session_state.agent_messages:
            st.subheader("Find your next home")
            st.write("What are you looking for?")
        with st.expander("Explore apartments and policies", expanded=not st.session_state.agent_messages):
            with st.container(key="chat_suggestions"):
                suggestion_columns = st.columns(2)
                for index, (question, icon) in enumerate(SUGGESTED_QUESTIONS):
                    if index == BLOCKED_EXAMPLE_INDEX:
                        continue
                    if suggestion_columns[index % 2].button(
                        question, key=f"suggestion_{index}", icon=icon,
                        width="stretch", disabled=not chat_ready,
                    ):
                        suggested_prompt = question
                        suggestion_index = index
        for index, message in enumerate(st.session_state.agent_messages):
            if isinstance(message, ToolMessage):
                render_tool(message, index)
            elif isinstance(message, HumanMessage) or (isinstance(message, AIMessage) and not message.tool_calls):
                with st.chat_message("user" if isinstance(message, HumanMessage) else "assistant"):
                    st.markdown(message.content)
                    if isinstance(message, AIMessage):
                        caption = reply_caption(message)
                        if caption:
                            st.caption(caption)
        current_turn = []
        for message in reversed(st.session_state.agent_messages):
            if isinstance(message, HumanMessage):
                break
            current_turn.append(message)
        if any(isinstance(m, ToolMessage) and m.name == "search_vacant_units" and as_list(str(m.content)) for m in current_turn):
            with st.container(horizontal=True):
                st.button("Compare shortlisted homes", icon=":material/compare_arrows:", on_click=navigate, args=("Shortlist",))
                st.button("View pet policy", icon=":material/pets:", disabled=not chat_ready,
                          on_click=ask, args=("What are the current pet rules, deposits and monthly fees?",))
                st.button("Show tour times", icon=":material/calendar_month:", disabled=not chat_ready,
                          on_click=ask, args=("Show available tour times for the homes we just discussed. Do not book or hold anything yet.",))
        feedback_request = st.session_state.feedback_request
        if feedback_request is not None and analytics_enabled():
            st.caption("How helpful was this reply?")
            feedback_key = f"rating_{feedback_request.id}"
            st.feedback("stars", key=feedback_key, on_change=record_rating, args=(feedback_request, feedback_key))
            if st.session_state.get("feedback_notice"):
                st.caption(st.session_state.feedback_notice)
    typed_prompt = st.chat_input("Ask about apartments, policies or tour times", disabled=not chat_ready, submit_mode="disable")
    prompt = suggested_prompt or action_prompt or typed_prompt
    if not chat_ready:
        st.info("Chat is temporarily unavailable.")
    if prompt and permit_request():
        tracking = begin_request(
            st.session_state.analytics_session_id,
            "suggested" if suggested_prompt else "typed", suggestion_index,
        )
        st.session_state.feedback_request = None
        st.session_state.pop("feedback_notice", None)
        interrupted = False
        history = st.session_state.agent_messages + [HumanMessage(content=prompt)]
        history_length = len(history)
        st.session_state.agent_messages = history
        with chat_viewport:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                draft_label = st.empty()
                assistant_placeholder = st.empty()
        stream = ReplyStream()
        previous_draft = ""
        pacing_budget = 8.0
        started = perf_counter()
        draft_label.caption("Draft response (being checked)")
        assistant_placeholder.markdown("Thinking...")
        try:
            for stream_kind, payload in leasing_app.stream(
                {"messages": history},
                stream_mode=["values", "messages"],
                config={"recursion_limit": 20},
            ):
                if stream_kind == "values":
                    st.session_state.agent_messages = payload["messages"]
                elif stream_kind == "messages":
                    message_chunk, chunk_meta = payload
                    text = stream.accept(message_chunk, chunk_meta)
                    if text is not None:
                        # Pace visible changes only; cap added latency for long replies.
                        if text and text != previous_draft and pacing_budget > 0:
                            delay = min(0.10, pacing_budget)
                            sleep(delay)
                            pacing_budget -= delay
                        previous_draft = text
                        assistant_placeholder.markdown(text or "Checking property records...")
        except Exception:
            interrupted = True
            messages = st.session_state.agent_messages
            answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
            for m in list(messages):
                if isinstance(m, AIMessage):
                    for call in m.tool_calls:
                        if call["id"] not in answered:
                            messages.append(ToolMessage(content="Outcome unknown after interruption. Do not retry a booking or hold automatically.", tool_call_id=call["id"], name=call["name"]))
            messages.append(AIMessage(content="The request was interrupted. A booking or hold may have completed; please check before trying it again.", response_metadata={"analytics_outcome": "interrupted"}))
        final_messages = st.session_state.agent_messages
        final_index = next((i for i in range(len(final_messages) - 1, history_length - 1, -1)
                            if isinstance(final_messages[i], AIMessage) and not final_messages[i].tool_calls), None)
        if final_index is not None:
            final = final_messages[final_index]
            final = final.model_copy(update={"response_metadata": {
                **final.response_metadata, "request_elapsed_seconds": round(perf_counter() - started, 2),
            }})
            final_messages[final_index] = final
            # Replace the draft before telemetry I/O, not only on the following rerun.
            assistant_placeholder.markdown(final.content)
            draft_label.caption(reply_caption(final))
        else:
            assistant_placeholder.empty()
            draft_label.empty()
        if finish_request(tracking, st.session_state.agent_messages, error="interrupted" if interrupted else None):
            st.session_state.feedback_request = tracking
            demo_summary.clear()
        st.rerun()
