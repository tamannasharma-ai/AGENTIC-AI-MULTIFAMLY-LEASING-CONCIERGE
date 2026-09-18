"""Render factual answers from tool evidence rather than free-form model prose."""
import json
import re

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def grounded_reply(messages):
    current = []
    answer = ""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and not answer:
            answer = str(message.content)
        if isinstance(message, ToolMessage):
            current.append(message)
    if not current:
        if re.search(r"\$|\bunit\s+[\w-]*\d|\b\d+\s*(?:bed|bath|sq|percent)", answer, re.I):
            return "I need a fresh property lookup to verify those details. Please ask me to search for the unit or policy."
        return answer

    sections = []
    for message in reversed(current):
        content = str(message.content)
        if getattr(message, "status", None) == "error":
            sections.append("The property lookup could not be completed. Please try again.")
            continue
        try:
            if content.startswith("TOUR_CONFIRMED::"):
                data, _ = json.JSONDecoder().raw_decode(content.removeprefix("TOUR_CONFIRMED::"))
                sections.append(f"Tour confirmed for Unit {data['unit_number']} on {data['scheduled_display']}. "
                                + ("Confirmation email sent." if data.get("email_sent") else "Email was not sent. Your calendar download is available."))
            elif content.startswith("VIP_HOLD_INITIALIZED::"):
                data, _ = json.JSONDecoder().raw_decode(content.removeprefix("VIP_HOLD_INITIALIZED::"))
                sections.append(f"Unit {data['unit_number']} is held until {data['expires_at']}. "
                                f"Hold reference: {data['reservation_id']}.")
            elif message.name == "search_vacant_units" and content.startswith("["):
                units = json.loads(content)
                if not units:
                    sections.append("No matching available homes.")
                    continue
                total = units[0].get("total_matches", len(units))
                lines = [f"Found {total} matching homes. Page {units[0].get('page', 1)}:"]
                for unit in units:
                    line = (f"Unit {unit['unit_number']}: ${float(unit['rent_usd']):,.2f}/month, "
                            f"{unit['bedrooms']} bedrooms, {unit['bathrooms']} bathrooms, {unit['sqft']} sq ft.")
                    if unit.get("special_offer"):
                        line += " " + unit["special_offer"]
                    lines.append(line)
                sections.append("\n\n".join(lines))
            elif message.name == "list_tour_availability" and content.startswith("{"):
                data = json.loads(content)
                sections.append("Available tour starts:\n\n" + "\n\n".join(s["display"] for s in data["slots"]))
            elif message.name == "lookup_market_comps" and content.startswith("["):
                sections.append("Nearby listings (not community inventory):\n\n" + "\n\n".join(
                    f"{r['bedrooms']} bedrooms: average ${r['avg_rent']}, range ${r['min_rent']}-${r['max_rent']}, {r['n']} listings."
                    for r in json.loads(content)))
            else:
                # Policies, validation failures and lead receipts are produced by tools.
                sections.append(content)
        except (ValueError, KeyError, TypeError):
            sections.append("The property response could not be verified. Please try the lookup again.")
    return "\n\n".join(sections)
