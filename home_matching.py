"""Explicit amenity matching and one-constraint alternatives, without AI scoring."""
import json

from home_choices import money

AMENITIES = {
    "central-ac": "Central air conditioning", "dishwasher": "Dishwasher",
    "in-unit-laundry": "In-unit laundry", "walk-in-closet": "Walk-in closet",
    "patio": "Patio", "balcony": "Balcony", "corner-unit": "Corner unit",
}


def match_reasons(unit, filters):
    amenities = unit.get("amenities") or []
    if isinstance(amenities, str):
        try:
            amenities = json.loads(amenities)
        except ValueError:
            amenities = []
    amenities = set(amenities) if isinstance(amenities, list) else set()
    reasons = []
    rent, budget = money(unit.get("rent_usd")), money(filters.get("max_rent"))
    if rent is not None and budget is not None:
        reasons.append(f"${budget - rent:,.2f} below your rent limit" if rent < budget else
                       "At your rent limit" if rent == budget else f"${rent - budget:,.2f} above your rent limit")
    if filters.get("bedrooms") is not None:
        reasons.append(f"{unit['bedrooms']} bedrooms requested and matched" if unit.get("bedrooms") == filters["bedrooms"] else "Bedroom count differs")
    for feature in filters.get("required_amenities", []):
        reasons.append(f"Must-have: {AMENITIES[feature]}" if feature in amenities else f"Must-have not recorded: {AMENITIES[feature]}")
    for feature in filters.get("preferred_amenities", []):
        if feature not in filters.get("required_amenities", []):
            reasons.append(f"Preference met: {AMENITIES[feature]}" if feature in amenities else f"Preference not recorded: {AMENITIES[feature]}")
    return reasons


def find_alternatives(search, filters):
    """Probe one relaxed constraint per query. Never mutate the submitted filters."""
    base = {**filters, "page": 1, "page_size": 1, "preferred_amenities": []}
    probes = []
    if filters.get("max_rent") is not None:
        probes.append(("budget", None, {**base, "max_rent": None}))
    for feature in filters.get("required_amenities", []):
        probes.append(("amenity", feature, {**base, "required_amenities": [x for x in filters["required_amenities"] if x != feature]}))
    proposals = []
    for kind, feature, query in probes:
        raw = search(query)
        if raw.startswith("No vacant units"):
            continue
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError("Unexpected inventory response")
        if not rows:
            continue
        home = rows[0]
        amended = {**filters, "page": 1}
        if kind == "budget":
            rent, budget = money(home.get("rent_usd")), money(filters["max_rent"])
            if rent is None or rent <= budget:
                continue
            amended["max_rent"] = float(rent)
            label = f"Raise rent limit to ${rent:,.2f} (+${rent - budget:,.2f}/month)"
        else:
            amended["required_amenities"] = query["required_amenities"]
            label = f"Allow homes without a recorded {AMENITIES[feature].lower()}"
        proposals.append({"label": label, "filters": amended, "unit": str(home["unit_number"])})
    return proposals
