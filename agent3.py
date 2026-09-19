import os
import re
import json
import time
from html import escape
from datetime import datetime, timezone
from functools import lru_cache
from typing import TypedDict, Annotated, List, Dict, Any

import psycopg2
import streamlit as st
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_groq import ChatGroq
from groq import Groq
import resend

from db_schema import ensure_schema
from demo_features import demo_controls_enabled
from home_matching import AMENITIES
from leasing_utils import (
    PROPERTY_NAME,
    PROPERTY_ADDRESS,
    PROPERTY_PHONE,
    PROPERTY_TZ,
    concession_for_days_vacant,
    parse_booking_datetime,
    validate_tour_time,
    has_tour_collision,
    next_open_tour_slots,
    format_slot_local,
    build_tour_ics,
    fair_housing_refusal,
)

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY")) if os.getenv("GROQ_API_KEY") else None


_schema_ready = False


def get_db_connection():
    global _schema_ready
    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"), cursor_factory=RealDictCursor, connect_timeout=5)
    if not _schema_ready:
        try:
            ensure_schema(conn)
            _schema_ready = True
        except Exception:
            conn.close()
            raise
    return conn


@lru_cache(maxsize=1)
def get_embed_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2")


def normalize_unit_number(unit_number: str) -> str:
    if not isinstance(unit_number, str):
        raise ValueError("Unit number must be a string.")
    normalized = re.sub(r"\s+", "", unit_number.strip()).upper()
    if not normalized:
        raise ValueError("Unit number is required.")
    return normalized


def validate_email_address(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Email address is required.")
    candidate = email.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", candidate):
        raise ValueError("Email address is invalid.")
    return candidate


def cleanup_expired_reservations(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE reservations
            SET status = 'expired'
            WHERE status IN ('held', 'pending') AND expires_at <= NOW();
            """
        )
        cur.execute(
            """
            UPDATE units u
            SET status = 'vacant'
            FROM reservations r
            WHERE u.id = r.unit_id
              AND r.status = 'expired'
              AND u.status IN ('held', 'reserved')
              AND NOT EXISTS (
                  SELECT 1 FROM reservations active
                  WHERE active.unit_id = u.id AND
                    (active.status = 'confirmed' OR
                     (active.status IN ('held', 'pending') AND
                      (active.expires_at IS NULL OR active.expires_at > NOW())))
              );
            """
        )
    conn.commit()


def reset_demo_data() -> str:
    """Expire stale holds only. Active reservations and bookings are untouched."""
    if not demo_controls_enabled(st.get_option("server.address")):
        raise PermissionError("Demo reset is available only on the enabled local demo server.")
    conn = get_db_connection()
    try:
        cleanup_expired_reservations(conn)
        lookup_property_policy.func.clear()
        lookup_market_comps.func.clear()
        return "Expired holds cleaned up. Active holds and booked tours were preserved."
    finally:
        conn.close()


LLM_FALLBACK_CONFIG: List[Dict[str, Any]] = [
    {
        "model": os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
        "temperature": 0.1,
        "max_retries": 2,
        "timeout": 20,
    },
    {
        "model": os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b"),
        "temperature": 0.1,
        "max_retries": 2,
        "timeout": 25,
    },
]


def build_llm_chain(tools: list, config: List[Dict[str, Any]]):
    """Ordered list of (label, model_name, bound_llm) to try in turn.

    Explicit rather than langchain's built-in with_fallbacks() so agent_node
    can report back which model actually answered and how long it took —
    used for the "answered in Xs using the primary/fallback model" caption.
    """
    chain = []
    for i, entry in enumerate(config):
        llm = ChatGroq(
            model=entry["model"],
            temperature=entry.get("temperature", 0.1),
            max_retries=entry.get("max_retries", 2),
            request_timeout=entry.get("timeout", 20),
            streaming=True,
            reasoning_format="parsed" if entry["model"].startswith("qwen/") else None,
        ).bind_tools(tools)
        label = "primary" if i == 0 else f"fallback_{i}"
        chain.append((label, entry["model"], llm))
    return chain


def dispatch_tour_confirmation_email(
    to_email: str,
    prospect_name: str,
    unit_number: str,
    tour_time: str,
    tour_type: str,
    tour_id: str,
) -> dict:
    if not resend.api_key:
        raise RuntimeError("Email is not configured")
    prospect_name = escape(prospect_name)
    unit_number = escape(unit_number)
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; padding: 24px; color: #1e293b;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #e2e8f0; overflow: hidden;">
            <div style="background-color: #0f172a; padding: 20px; text-align: center; color: #ffffff;">
                <h2 style="margin: 0; font-size: 20px;">{PROPERTY_NAME}</h2>
                <p style="margin: 4px 0 0 0; font-size: 13px; color: #94a3b8;">Tour Confirmation • #{tour_id[:8]}</p>
            </div>
            <div style="padding: 24px;">
                <p style="font-size: 16px; margin-top: 0;">Hi <strong>{prospect_name}</strong>,</p>
                <p style="font-size: 14px; line-height: 1.6; color: #475569;">
                    Your tour appointment for <strong>Unit {unit_number}</strong> has been secured!
                </p>
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;">
                    <tr style="border-bottom: 1px solid #f1f5f9;">
                        <td style="padding: 10px 0; color: #64748b;">Date & Time:</td>
                        <td style="padding: 10px 0; font-weight: 600; text-align: right;">{tour_time}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #f1f5f9;">
                        <td style="padding: 10px 0; color: #64748b;">Type:</td>
                        <td style="padding: 10px 0; font-weight: 600; text-align: right; text-transform: capitalize;">{tour_type.replace('_', ' ')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; color: #64748b;">Location:</td>
                        <td style="padding: 10px 0; font-weight: 600; text-align: right;">{PROPERTY_ADDRESS}</td>
                    </tr>
                </table>
                <div style="background: #f1f5f9; border-left: 4px solid #0ea5e9; padding: 12px 16px; border-radius: 4px; font-size: 13px; color: #334155;">
                    Please present a valid photo ID upon arrival. Visitor parking stalls are reserved directly in our ground floor courtyard.
                    Download your calendar invite from the leasing portal.
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    params = {
        "from": f"{PROPERTY_NAME} <onboarding@resend.dev>",
        "to": [to_email],
        "subject": f"Tour Confirmed: Unit {unit_number} on {tour_time}",
        "html": html_template,
    }
    return resend.Emails.send(params)


@tool
def search_vacant_units(max_rent: float | None = None, bedrooms: int | None = None,
                       unit_number: str | None = None, specials_only: bool = False,
                       page: int = 1, page_size: int = 5,
                       required_amenities: list[str] | None = None,
                       preferred_amenities: list[str] | None = None) -> str:
    """Search available vacant apartment units in the community by max rent or bedroom count.
    Automatically identifies units eligible for move-in concessions if vacant over 45 days.
    Required amenities are strict filters; preferred amenities rank matches before rent.
    Use only explicitly requested amenity preferences, never inferred personal attributes.
    """
    if max_rent is not None and max_rent < 0:
        return "Maximum rent must be a positive number."
    if bedrooms is not None and bedrooms < 0:
        return "Bedroom count must be a positive integer."
    if page < 1 or not 1 <= page_size <= 25:
        return "Page must be positive and page size must be between 1 and 25."
    required_amenities = list(dict.fromkeys(required_amenities or []))
    preferred_amenities = list(dict.fromkeys(preferred_amenities or []))
    if any(feature not in AMENITIES for feature in required_amenities + preferred_amenities):
        return "Choose supported apartment amenities."

    conn = get_db_connection()
    try:
        cleanup_expired_reservations(conn)
        with conn.cursor() as cur:
            query = """
                SELECT
                    unit_number, bedrooms, bathrooms, sqft, rent_usd, amenities, photos,
                    COUNT(*) OVER() AS total_matches,
                    EXTRACT(DAY FROM (NOW() - COALESCE(vacant_since, NOW() - INTERVAL '8 days')))::int AS days_vacant
                FROM units
                WHERE status = 'vacant'
                  AND (available_from IS NULL OR available_from <= CURRENT_DATE)
            """
            params = []
            if max_rent is not None:
                query += " AND rent_usd <= %s"
                params.append(max_rent)
            if bedrooms is not None:
                query += " AND bedrooms = %s"
                params.append(bedrooms)

            if unit_number:
                query += " AND unit_number = %s"
                params.append(normalize_unit_number(unit_number))
            if specials_only:
                query += " AND vacant_since <= NOW() - INTERVAL '45 days'"
            if required_amenities:
                query += " AND COALESCE(amenities, '[]'::jsonb) ?& %s::text[]"
                params.append(required_amenities)
            query += " ORDER BY "
            if preferred_amenities:
                query += "(SELECT COUNT(*) FROM unnest(%s::text[]) AS pref(feature) WHERE COALESCE(amenities, '[]'::jsonb) ? pref.feature) DESC, "
                params.append(preferred_amenities)
            query += "rent_usd ASC, unit_number ASC LIMIT %s OFFSET %s;"
            params.extend([page_size, (page - 1) * page_size])
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            if not rows:
                return "No vacant units found matching those exact filters."

            enhanced_units = []
            for unit in rows:
                unit = dict(unit)
                days = int(unit.get("days_vacant") or 0)
                unit["days_vacant"] = days
                unit["special_offer"] = concession_for_days_vacant(days)
                unit["page"] = page
                unit["page_size"] = page_size
                enhanced_units.append(unit)

            return json.dumps(enhanced_units, default=str)
    finally:
        conn.close()


@tool
@st.cache_data(ttl=300, max_entries=256, show_spinner=False)
def lookup_property_policy(query: str) -> str:
    """Search community policies, pet rules, parking costs, utility fees, amenity hours, and lease application criteria."""
    query_vector = get_embed_model().encode(query).tolist()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT content, 1 - (embedding <=> %s::vector) AS similarity
                FROM property_knowledge
                ORDER BY similarity DESC
                LIMIT 2;
            """
            cur.execute(sql, (query_vector,))
            rows = cur.fetchall()
            if not rows or rows[0]["similarity"] < 0.35:
                return "No specific written policy matched. Please check directly with our on-site leasing office."
            return " | ".join([r["content"] for r in rows])
    finally:
        conn.close()


@tool
@st.cache_data(ttl=300, max_entries=32, show_spinner=False)
def lookup_market_comps(bedrooms: int | None = None) -> str:
    """Look up nearby apartment rents from the latest RentCast market snapshot. This is neighborhood context, not this community's live inventory."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if bedrooms is not None:
                cur.execute(
                    """
                    SELECT bedrooms, ROUND(AVG(rent_usd)::numeric, 0) AS avg_rent,
                           MIN(rent_usd) AS min_rent, MAX(rent_usd) AS max_rent, COUNT(*) AS n
                    FROM market_comps
                    WHERE rent_usd > 0 AND bedrooms = %s
                    GROUP BY bedrooms;
                    """,
                    (bedrooms,),
                )
            else:
                cur.execute(
                    """
                    SELECT bedrooms, ROUND(AVG(rent_usd)::numeric, 0) AS avg_rent,
                           MIN(rent_usd) AS min_rent, MAX(rent_usd) AS max_rent, COUNT(*) AS n
                    FROM market_comps
                    WHERE rent_usd > 0
                    GROUP BY bedrooms
                    ORDER BY bedrooms;
                    """
                )
            rows = cur.fetchall()
            if not rows:
                return "No nearby market comps are loaded yet. Community pricing still comes from live vacant units."
            return json.dumps([dict(r) for r in rows], default=str)
    finally:
        conn.close()


def can_tour_unit(cur, unit, email=None, reservation_id=None):
    if unit["status"] == "vacant":
        return True
    if unit["status"] != "held" or not email or not reservation_id:
        return False
    # A hold reference plus matching email is required; email alone is not ownership.
    cur.execute("""SELECT id FROM reservations WHERE unit_id = %s AND id::text = %s
        AND lower(prospect_email) = lower(%s) AND status = 'held' AND expires_at > NOW()""",
        (unit["id"], reservation_id, email))
    return cur.fetchone() is not None


@tool
def list_tour_availability(unit_number: str | None = None, reservation_id: str | None = None,
                           prospect_email: str | None = None) -> str:
    """List open 45-minute tour slots Monday-Saturday, 10 AM-6 PM Central."""
    conn = get_db_connection()
    try:
        cleanup_expired_reservations(conn)
        with conn.cursor() as cur:
            if unit_number:
                try:
                    normalized_unit = normalize_unit_number(unit_number)
                except ValueError as exc:
                    return str(exc)
                cur.execute(
                    "SELECT id, status FROM units WHERE unit_number = %s;",
                    (normalized_unit,),
                )
                unit = cur.fetchone()
                if not unit:
                    return f"Unit {normalized_unit} not found."
                if not can_tour_unit(cur, unit, prospect_email, reservation_id):
                    return f"Unit {normalized_unit} is currently '{unit['status']}' and cannot be scheduled for a tour."

            cur.execute("SELECT scheduled_at FROM tours;")
            existing = [row["scheduled_at"] for row in cur.fetchall()]

        slots = next_open_tour_slots(existing, count=8)
        if not slots:
            return "No tour slots are open in the next two weeks. Please contact the leasing office."
        payload = {
            "unit_number": unit_number,
            "slots": [
                {"iso": slot.isoformat(), "display": format_slot_local(slot)}
                for slot in slots
            ],
        }
        return json.dumps(payload)
    finally:
        conn.close()


@tool
def book_tour_appointment(
    unit_number: str,
    prospect_name: str,
    prospect_email: str,
    date_time: str,
    tour_type: str = "in_person",
    reservation_id: str | None = None,
) -> str:
    """Schedule an in-person, self-guided, or virtual tour for an apartment unit.
    Accepts natural language times like 'tomorrow at 2 PM'. Requires two hours notice.
    A held unit requires its full reservation_id and matching prospect_email. Rejects leased units and 45-minute collisions.
    Ask for the prospect name and email before calling this tool.
    """
    try:
        normalized_unit = normalize_unit_number(unit_number)
        valid_email = validate_email_address(prospect_email)
        real_name = (prospect_name or "").strip()
        if len(real_name) < 2:
            return "Prospect name is required for tour scheduling."

        allowed_tours = {"in_person", "self_guided", "virtual"}
        normalized_tour_type = (tour_type or "in_person").strip().lower()
        if normalized_tour_type not in allowed_tours:
            return "Tour type is invalid. Please choose one of: in_person, self_guided, or virtual."

        parsed_dt = parse_booking_datetime(date_time)
        validate_tour_time(parsed_dt)
    except ValueError as exc:
        return str(exc)

    conn = get_db_connection()
    try:
        cleanup_expired_reservations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(702101);")
            cur.execute("SELECT id, status FROM units WHERE unit_number = %s FOR UPDATE;", (normalized_unit,))
            unit = cur.fetchone()
            if not unit:
                return f"Unit {normalized_unit} not found."

            if not can_tour_unit(cur, unit, valid_email, reservation_id):
                return f"Unit {normalized_unit} is currently '{unit['status']}' and cannot be scheduled for a tour."

            cur.execute("SELECT scheduled_at FROM tours;")
            existing = [row["scheduled_at"] for row in cur.fetchall()]
            conflict = has_tour_collision(parsed_dt, existing)
            if conflict:
                conflicting_time = format_slot_local(conflict)
                return (
                    f"Time Conflict: An appointment is already booked around {conflicting_time}. "
                    "Please choose a slot at least 45 minutes before or after. "
                    "Call list_tour_availability for open times."
                )

            insert_query = """
                INSERT INTO tours (unit_id, prospect_name, prospect_email, tour_type, scheduled_at)
                VALUES (%s, %s, %s, %s, %s::timestamptz) RETURNING id;
            """
            cur.execute(
                insert_query,
                (unit["id"], real_name, valid_email, normalized_tour_type, parsed_dt),
            )
            tour_id = str(cur.fetchone()["id"])
            conn.commit()

            ics = build_tour_ics(
                unit_number=normalized_unit,
                prospect_name=real_name,
                prospect_email=valid_email,
                start_utc=parsed_dt,
                tour_type=normalized_tour_type,
                tour_id=tour_id,
            )
            local_when = format_slot_local(parsed_dt)

            email_sent = False
            try:
                dispatch_tour_confirmation_email(
                    to_email=valid_email,
                    prospect_name=real_name,
                    unit_number=normalized_unit,
                    tour_time=local_when,
                    tour_type=normalized_tour_type,
                    tour_id=tour_id,
                )
                email_sent = True
            except Exception as mail_err:
                print(f"⚠️ Email notice: {mail_err}")

            payload = {
                "unit_number": normalized_unit,
                "tour_id": tour_id,
                "scheduled_display": local_when,
                "ics": ics,
                "filename": f"tour-unit-{normalized_unit}.ics",
                "email_sent": email_sent,
            }
            return (
                f"TOUR_CONFIRMED::{json.dumps(payload)}:: "
                f"Tour confirmed for Unit {normalized_unit} on {local_when}. "
                f"Guest: {real_name}. "
                + ("Confirmation email dispatched." if email_sent else "Email unavailable; download the calendar invite.")
            )
    finally:
        conn.close()


@tool
def create_reservation_hold(
    unit_number: str,
    prospect_name: str,
    prospect_email: str,
) -> str:
    """Place a temporary 15-minute VIP lock on an apartment unit to hold it exclusively for a prospect.
    Ask for name and email before calling this tool.
    """
    try:
        normalized_unit = normalize_unit_number(unit_number)
        valid_email = validate_email_address(prospect_email)
        real_name = (prospect_name or "").strip()
        if len(real_name) < 2:
            return "Prospect name is required for a reservation hold."
    except ValueError as exc:
        return str(exc)

    conn = get_db_connection()
    try:
        cleanup_expired_reservations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM units WHERE unit_number = %s FOR UPDATE;", (normalized_unit,))
            unit = cur.fetchone()
            if not unit:
                return f"Unit {normalized_unit} not found."
            if unit["status"] != "vacant":
                return f"Unit {normalized_unit} is currently '{unit['status']}' and cannot be placed on hold."

            cur.execute(
                """
                SELECT id, expires_at
                FROM reservations
                WHERE unit_id = %s AND status = 'held' AND expires_at > NOW()
                LIMIT 1;
                """,
                (unit["id"],),
            )
            existing_hold = cur.fetchone()
            if existing_hold:
                return (
                    f"Unit {normalized_unit} already has a VIP hold active until "
                    f"{existing_hold['expires_at'].strftime('%Y-%m-%d %H:%M UTC')}."
                )

            now_utc = datetime.now(timezone.utc)
            from datetime import timedelta

            expires_at = now_utc + timedelta(minutes=15)

            cur.execute(
                """
                INSERT INTO reservations (unit_id, prospect_name, prospect_email, status, expires_at)
                VALUES (%s, %s, %s, 'held', %s) RETURNING id;
                """,
                (unit["id"], real_name, valid_email, expires_at),
            )
            res_id = str(cur.fetchone()["id"])
            cur.execute("UPDATE units SET status = 'held' WHERE id = %s;", (unit["id"],))
            conn.commit()

            payload = {
                "unit_number": normalized_unit,
                "reservation_id": res_id,
                "prospect_name": real_name,
                "expires_at": expires_at.isoformat(),
                "seconds_remaining": 900,
            }

            return (
                f"VIP_HOLD_INITIALIZED::{json.dumps(payload)}:: "
                f"Unit {normalized_unit} is now locked under a VIP hold for {real_name} ({valid_email}). "
                f"Reference #{res_id[:8]}. The apartment has been pulled off the market for 15 minutes."
            )
    except Exception as e:
        conn.rollback()
        return f"Failed to place hold: {str(e)}"
    finally:
        conn.close()


def upsert_lead(
    full_name: str,
    email: str,
    phone: str | None = None,
    preferred_beds: int | None = None,
    max_budget_usd: float | None = None,
) -> str:
    try:
        name = (full_name or "").strip()
        if len(name) < 2:
            return "Full name is required to capture a lead."
        valid_email = validate_email_address(email)
        if preferred_beds is not None and preferred_beds < 0:
            return "Preferred bed count cannot be negative."
        if max_budget_usd is not None and max_budget_usd < 0:
            return "Maximum budget cannot be negative."
    except ValueError as exc:
        return str(exc)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            upsert_query = """
                INSERT INTO leads (full_name, email, phone, preferred_beds, max_budget_usd)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET full_name = EXCLUDED.full_name,
                    phone = COALESCE(EXCLUDED.phone, leads.phone),
                    preferred_beds = COALESCE(EXCLUDED.preferred_beds, leads.preferred_beds),
                    max_budget_usd = COALESCE(EXCLUDED.max_budget_usd, leads.max_budget_usd)
                RETURNING id;
            """
            cur.execute(
                upsert_query,
                (name, valid_email, phone, preferred_beds, max_budget_usd),
            )
            lead_id = cur.fetchone()["id"]
            conn.commit()
            return f"Lead captured for {name} ({valid_email}) with ID: {lead_id}."
    finally:
        conn.close()


@tool
def capture_prospect_lead(
    full_name: str,
    email: str,
    phone: str | None = None,
    preferred_beds: int | None = None,
    max_budget_usd: float | None = None,
) -> str:
    """Record prospective tenant contact details and criteria in the CRM database."""
    return upsert_lead(full_name, email, phone, preferred_beds, max_budget_usd)


SECURITY_ATTACK_REFUSAL = (
    "I cannot process this request because it violates our security boundaries. "
    "I can only answer questions related to available apartments, pricing, property policies, and tour scheduling."
)


def validate_user_input(text: str) -> tuple[bool, str]:
    if not isinstance(text, str) or not text.strip():
        return False, SECURITY_ATTACK_REFUSAL

    refusal = fair_housing_refusal(text)
    if refusal:
        return False, refusal

    try:
        resp = groq_client.chat.completions.create(
            model="meta-llama/llama-prompt-guard-2-86m",
            messages=[{"role": "user", "content": text}],
            max_tokens=30,
            temperature=0.0,
        )
        res_text = resp.choices[0].message.content.strip().lower()
        if any(term in res_text for term in ["injection", "jailbreak", "unsafe"]):
            return False, SECURITY_ATTACK_REFUSAL
    except Exception as err:
        print(f"⚠️ Prompt guard unavailable ({err}); continuing with Fair Housing checks only.")

    return True, ""


def verify_grounding(messages: list) -> tuple[bool, str]:
    from grounded_replies import grounded_reply

    clean = grounded_reply(messages)
    answer = next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage)), "")
    return clean == answer, clean

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


tools = [
    search_vacant_units,
    lookup_property_policy,
    lookup_market_comps,
    list_tour_availability,
    book_tour_appointment,
    create_reservation_hold,
    capture_prospect_lead,
]
tool_node = ToolNode(tools)
llm_chain = build_llm_chain(tools, LLM_FALLBACK_CONFIG) if os.getenv("GROQ_API_KEY") else None

SYSTEM_PROMPT = f"""You are the 24/7 AI Leasing Concierge for {PROPERTY_NAME} located at {PROPERTY_ADDRESS}.Behave properly and humanly.
1. Search units using search_vacant_units. If a unit has a special_offer, proactively highlight it.
Use unit_number for a specific unit, specials_only for promotions, and page for more results.
Always retrieve current tool evidence for factual property answers; do not reuse stale availability.
2. Answer policy/fee/amenity questions using lookup_property_policy.
3. Use list_tour_availability before booking when the guest has not picked a time.
4. Schedule tours using book_tour_appointment. Natural language times are OK. Always collect name and email first.
5. Place 15-minute VIP holds using create_reservation_hold after collecting name and email.
For a held unit's tour, pass the full reservation_id from its tool result and matching email.
6. Nearby market rents (not this building's inventory) come from lookup_market_comps.
7. Capture leads only when the guest asks to save their details or be contacted.
Only book tours or create holds when explicitly requested. Never invent names or emails.
This is a fictional demonstration community, including its policies, photos and contact number.
8. Obey U.S. Fair Housing Act rules: NEVER comment on safety, crime rates, or neighborhood demographics.
If systems fail, invite the guest to call {PROPERTY_PHONE}.
"""


def guardrail_node(state: AgentState):
    last_msg = state["messages"][-1].content
    is_valid, refusal = validate_user_input(last_msg)
    if not is_valid:
        return {"messages": [AIMessage(content=refusal, response_metadata={"analytics_outcome": "blocked"})]}
    return {"messages": []}


def agent_node(state: AgentState):
    messages = [SystemMessage(content=SYSTEM_PROMPT + "\nCurrent property time: " + datetime.now(PROPERTY_TZ).isoformat())] + state["messages"]
    if llm_chain is None:
        return {"messages": [AIMessage(content="Chat is unavailable until the model connection is configured.", response_metadata={"analytics_outcome": "model_unavailable"})]}

    started = time.perf_counter()
    fallback_attempted = False
    for label, model_name, llm in llm_chain:
        fallback_attempted = fallback_attempted or label != "primary"
        try:
            accumulated = None
            for token_chunk in llm.stream(messages, config={
                "metadata": {"leasing_attempt": label, "leasing_model": model_name},
            }):
                accumulated = token_chunk if accumulated is None else accumulated + token_chunk
            if accumulated is None or (not accumulated.content and not accumulated.tool_calls):
                raise RuntimeError("Model returned an empty stream.")
            if accumulated.invalid_tool_calls:
                raise ValueError("Model returned an incomplete tool call.")
            elapsed = time.perf_counter() - started
            response = AIMessage(
                id=accumulated.id,
                content=accumulated.content,
                tool_calls=accumulated.tool_calls,
                response_metadata={
                    **(accumulated.response_metadata or {}),
                    "served_by": label,
                    "served_model": model_name,
                    "elapsed_seconds": round(elapsed, 2),
                    "model_attempted": True,
                    "fallback_attempted": fallback_attempted,
                },
            )
            return {"messages": [response]}
        except Exception:
            continue

    emergency_reply = (
        f"I am temporarily experiencing high traffic connecting to our leasing systems. "
        f"Please view current inventory on the left or contact our leasing office at {PROPERTY_PHONE}."
    )
    return {"messages": [AIMessage(content=emergency_reply, response_metadata={
        "analytics_outcome": "model_error", "model_attempted": True,
        "fallback_attempted": fallback_attempted,
    })]}


def post_eval_node(state: AgentState):
    is_grounded, clean_text = verify_grounding(state["messages"])
    if not is_grounded:
        original = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
        return {"messages": [AIMessage(content=clean_text, id=original.id, response_metadata=original.response_metadata)]}
    return {"messages": []}


workflow = StateGraph(AgentState)
workflow.add_node("guardrail", guardrail_node)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.add_node("evaluator", post_eval_node)

workflow.add_edge(START, "guardrail")


def guardrail_decision(state: AgentState):
    if state["messages"] and isinstance(state["messages"][-1], AIMessage):
        return END
    return "agent"


workflow.add_conditional_edges("guardrail", guardrail_decision)
workflow.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "evaluator"})
workflow.add_edge("tools", "agent")
workflow.add_edge("evaluator", END)

leasing_app = workflow.compile()
