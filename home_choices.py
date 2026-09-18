"""Deterministic comparisons and estimates from recognized database policies."""
from decimal import Decimal, InvalidOperation


# Whole-document matches deliberately fail closed when policy terms change.
SUPPORTED_POLICIES = {
    "pet_policy": "Pet Policy: Dogs and cats are welcome (maximum 2 pets per apartment). Dogs must be under 55 lbs. Aggressive breeds are prohibited. Monthly pet rent is $35 per pet, with a one-time refundable pet deposit of $300.",
    "parking_and_storage": "Parking: Covered garage parking is available for $125 per month per vehicle. Reserved EV charging stalls are $175 per month including electricity. Surface outdoor lot is first-come, first-served for $50 per month.",
    "lease_terms_and_application": "Application Requirements: All applicants over 18 must complete an application. Requirements include a minimum 650 credit score and gross monthly income equal to at least 3x monthly rent. Application fee is $50 per applicant. Standard leases are 12 months; 6-month terms are available with a $150 short-term premium.",
    "utilities_and_trash": "Utilities: Valet trash service is included. Water, sewer, and electricity are individually sub-metered and billed monthly based on usage. High-speed fiber internet is pre-installed for $60 per month.",
    "move_in_fees": "Move-in costs: Security deposit equals one month of rent. Admin fee is $100 (waived when a 60-day vacancy special is active). Parking and pet fees are optional add-ons and billed separately from rent.",
}


def money(value):
    try:
        amount = Decimal(str(value))
        return amount.quantize(Decimal("0.01")) if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def estimate_costs(unit, policies, *, applicants=1, pets=0, parking="None", vehicles=1, lease_months=12):
    if not 1 <= applicants <= 10 or not 0 <= pets <= 2 or not 1 <= vehicles <= 3:
        raise ValueError("Invalid household counts")
    if lease_months not in (6, 12) or parking not in ("None", "Surface", "Garage", "EV"):
        raise ValueError("Invalid lease or parking option")
    recognized = {key: policies.get(key) == value for key, value in SUPPORTED_POLICIES.items()}
    rows = []

    def add(label, value, frequency, source):
        rows.append({"Charge": label, "amount": money(value), "Frequency": frequency, "Source": source})

    add("Base rent", unit.get("rent_usd"), "Monthly", "Live unit record")
    add("Internet", 60 if recognized["utilities_and_trash"] else None, "Monthly", "utilities_and_trash")
    add("Security deposit (refundable)", unit.get("rent_usd") if recognized["move_in_fees"] else None, "One-time", "move_in_fees")
    add("Admin fee", 100 if recognized["move_in_fees"] else None, "One-time", "move_in_fees")
    add("Application fees", 50 * applicants if recognized["lease_terms_and_application"] else None, "One-time", "lease_terms_and_application")
    if lease_months == 6:
        add("Short-term premium", 150 if recognized["lease_terms_and_application"] else None, "Monthly", "lease_terms_and_application")
    if pets:
        add("Pet rent", 35 * pets if recognized["pet_policy"] else None, "Monthly", "pet_policy")
        # The policy does not specify whether the deposit is per pet or apartment.
        add("Pet deposit (basis needs confirmation)", None, "One-time", "pet_policy")
    if parking != "None":
        rate = {"Surface": 50, "Garage": 125, "EV": 175}[parking]
        add(f"{parking} parking", rate * vehicles if recognized["parking_and_storage"] else None, "Monthly", "parking_and_storage")
    add("Water, sewer and electricity (usage-based)", None, "Monthly", "utilities_and_trash")
    monthly = sum((row["amount"] for row in rows if row["Frequency"] == "Monthly" and row["amount"] is not None), Decimal(0))
    upfront = sum((row["amount"] for row in rows if row["Frequency"] == "One-time" and row["amount"] is not None), Decimal(0))
    return {"rows": rows, "monthly": monthly, "first_month_plus_fees": monthly + upfront}


def load_choice_records(connect, numbers):
    """One read transaction; never create a hold or modify availability."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT unit_number, bedrooms, bathrooms, sqft, rent_usd, amenities,
                status, available_from, CURRENT_DATE AS checked_date
                FROM units WHERE unit_number = ANY(%s) ORDER BY unit_number""", (list(numbers),))
            units = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT category, content FROM property_knowledge WHERE category = ANY(%s)", (list(SUPPORTED_POLICIES),))
            policies = {}
            for row in cur.fetchall():
                category = row["category"]
                # Duplicate records are ambiguous even when one matches the supported policy.
                policies[category] = row["content"] if category not in policies else None
        return units, policies
    finally:
        conn.close()


def available(unit):
    return unit.get("status") == "vacant" and (
        unit.get("available_from") is None or unit["available_from"] <= unit["checked_date"])
