"""Session shortlist and explicit, read-only cost checks."""
from datetime import datetime, timezone

import streamlit as st

from home_choices import available, estimate_costs, load_choice_records


def navigate(tab):
    st.session_state.main_tab = tab


def ask(prompt):
    st.session_state.pending_action = prompt
    navigate("Concierge")


def toggle_saved(unit):
    saved = st.session_state.setdefault("shortlist", {})
    number = str(unit["unit_number"])
    if number in saved:
        del saved[number]
    elif len(saved) < 3:
        saved[number] = dict(unit)
    st.session_state.pop("choice_records", None)


def save_button(unit, key):
    saved = st.session_state.setdefault("shortlist", {})
    selected = str(unit["unit_number"]) in saved
    st.button("Remove from shortlist" if selected else "Shortlist", key=key,
              icon=":material/bookmark_remove:" if selected else ":material/bookmark_add:",
              disabled=not selected and len(saved) >= 3,
              help="Up to three homes per browser session.", on_click=toggle_saved, args=(unit,))


def render_shortlist(connect, permit_request, chat_ready):
    saved = st.session_state.shortlist
    st.subheader("Your shortlist")
    st.caption("Up to 3 homes | Saved for this browser session | Not a reservation")
    if not saved:
        st.info("No shortlisted homes yet.")
        st.button("Find homes", icon=":material/search:", on_click=navigate, args=("Available Homes",))
        return
    for number, unit in list(saved.items()):
        with st.container(horizontal=True):
            st.write(f"Unit {number}")
            save_button(unit, f"remove_{number}")
    st.dataframe([{
        "Unit": number, "Rent / month": float(unit["rent_usd"]),
        "Beds": unit["bedrooms"], "Baths": unit["bathrooms"], "Sq ft": unit["sqft"],
        "Amenities": ", ".join(unit.get("amenities", [])) if isinstance(unit.get("amenities"), list) else str(unit.get("amenities", "")),
        "Special (unconfirmed)": unit.get("special_offer") or "None recorded",
    } for number, unit in saved.items()], hide_index=True, width="stretch",
        column_config={"Rent / month": st.column_config.NumberColumn(format="$%.2f")})
    st.caption("Saved search results may be outdated. Specials are subject to eligibility and confirmation.")
    numbers = ", ".join(saved)
    st.button("Ask about these homes", icon=":material/chat:", disabled=not chat_ready,
              on_click=ask, args=(f"Check current availability and compare units {numbers} by rent, size and amenities. Do not reserve or book anything.",))
    st.subheader("Move-in cost estimate")
    with st.form("cost_estimate"):
        household, extras = st.columns(2)
        with household:
            applicants = st.number_input("Adult applicants", min_value=1, max_value=10, value=1)
            pets = st.number_input("Pets", min_value=0, max_value=2, value=0)
            lease = st.selectbox("Lease length (months)", [12, 6])
        with extras:
            parking = st.selectbox("Parking", ["None", "Surface", "Garage", "EV"])
            vehicles = st.number_input("Parking spaces", min_value=1, max_value=3, value=1)
        calculate = st.form_submit_button("Refresh availability and calculate", icon=":material/calculate:")
    if calculate and permit_request():
        st.session_state.pop("choice_records", None)
        try:
            units, policies = load_choice_records(connect, list(saved))
            st.session_state.choice_records = (units, policies, datetime.now(timezone.utc),
                                               dict(applicants=applicants, pets=pets, parking=parking, vehicles=vehicles, lease_months=lease))
        except Exception:
            st.error("Costs could not be verified. Please try again later.")
    snapshot = st.session_state.get("choice_records")
    if not snapshot:
        return
    units, policies, checked, options = snapshot
    st.caption(f"Checked {checked:%d %b %Y, %H:%M:%S} UTC | {options['applicants']} applicant(s), {options['pets']} pet(s), {options['parking']} parking, {options['vehicles']} space(s), {options['lease_months']}-month lease")
    st.warning("Estimate only, not a quote. Unknown costs are excluded. Assumes a full first month; proration, payment dates and special eligibility need leasing-office confirmation. No promotional discounts applied.")
    for number in saved:
        unit = next((u for u in units if str(u["unit_number"]) == number), None)
        st.subheader(f"Unit {number}")
        if not unit or not available(unit):
            st.warning("Not currently available. A move-in estimate is unavailable.")
            continue
        estimate = estimate_costs(unit, policies, **options)
        st.write(f"Known monthly subtotal: **${estimate['monthly']:,.2f}**")
        st.write(f"First full month + known one-time charges: **${estimate['first_month_plus_fees']:,.2f}**")
        st.dataframe([{"Charge": row["Charge"], "Amount": "Unknown" if row["amount"] is None else f"${row['amount']:,.2f}",
                       "Frequency": row["Frequency"], "Source": row["Source"]} for row in estimate["rows"]], hide_index=True, width="stretch")
        st.button(f"Show tour times for Unit {number}", key=f"tour_choice_{number}", icon=":material/calendar_month:",
                  disabled=not chat_ready, on_click=ask,
                  args=(f"Show available tour times for Unit {number}. Do not book or hold anything yet.",))
    with st.expander("Source policies"):
        for category, content in policies.items():
            st.caption(category)
            st.write(content or "Conflicting records; confirmation required.")
