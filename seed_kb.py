import os

import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()


KNOWLEDGE_DOCS = [
    {
        "category": "pet_policy",
        "content": "Pet Policy: Dogs and cats are welcome (maximum 2 pets per apartment). Dogs must be under 55 lbs. Aggressive breeds are prohibited. Monthly pet rent is $35 per pet, with a one-time refundable pet deposit of $300.",
    },
    {
        "category": "parking_and_storage",
        "content": "Parking: Covered garage parking is available for $125 per month per vehicle. Reserved EV charging stalls are $175 per month including electricity. Surface outdoor lot is first-come, first-served for $50 per month.",
    },
    {
        "category": "lease_terms_and_application",
        "content": "Application Requirements: All applicants over 18 must complete an application. Requirements include a minimum 650 credit score and gross monthly income equal to at least 3x monthly rent. Application fee is $50 per applicant. Standard leases are 12 months; 6-month terms are available with a $150 short-term premium.",
    },
    {
        "category": "utilities_and_trash",
        "content": "Utilities: Valet trash service is included. Water, sewer, and electricity are individually sub-metered and billed monthly based on usage. High-speed fiber internet is pre-installed for $60 per month.",
    },
    {
        "category": "office_hours",
        "content": "Leasing office hours: Monday through Saturday 10:00 AM to 6:00 PM Central Time. Tours last 45 minutes, start on 15-minute boundaries between 10:00 AM and 5:15 PM, and require at least two hours notice. No Sunday tours. After hours, the virtual concierge can search units, answer policy questions, capture leads, and book future tours.",
    },
    {
        "category": "amenity_hours",
        "content": "Amenity hours: Fitness center is open 24 hours with fob access. Skyline lounge is open 7:00 AM to 10:00 PM. Courtyard grill deck is open 8:00 AM to 9:00 PM. Quiet hours begin at 10:00 PM.",
    },
    {
        "category": "packages_and_guests",
        "content": "Package lockers are in the ground-floor mailroom; codes are sent by email when a parcel arrives. Guests must be registered at the lobby kiosk. Overnight guests are limited to 14 nights per calendar quarter.",
    },
    {
        "category": "move_in_fees",
        "content": "Move-in costs: Security deposit equals one month of rent. Admin fee is $100 (waived when a 60-day vacancy special is active). Parking and pet fees are optional add-ons and billed separately from rent.",
    },
]

def seed_knowledge():
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode([doc["content"] for doc in KNOWLEDGE_DOCS]).tolist()
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS policy_backup (id uuid PRIMARY KEY, original_row jsonb NOT NULL, backed_up_at timestamptz DEFAULT now())")
                cur.execute("INSERT INTO policy_backup(id, original_row) SELECT id, to_jsonb(p) FROM property_knowledge p ON CONFLICT DO NOTHING")
                for doc, embedding in zip(KNOWLEDGE_DOCS, embeddings):
                    cur.execute("SELECT id FROM property_knowledge WHERE category = %s", (doc["category"],))
                    ids = cur.fetchall()
                    if ids:
                        cur.execute("UPDATE property_knowledge SET content=%s, embedding=%s::vector WHERE category=%s", (doc["content"], str(embedding), doc["category"]))
                    else:
                        cur.execute("INSERT INTO property_knowledge(category,content,embedding) VALUES (%s,%s,%s::vector)", (doc["category"], doc["content"], str(embedding)))
        print(f"Seeded {len(KNOWLEDGE_DOCS)} policy categories; originals preserved in policy_backup.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed_knowledge()
