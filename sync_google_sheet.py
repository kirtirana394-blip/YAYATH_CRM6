<<<<<<< HEAD
import csv
import io
import json
import os
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
sheet_tab = os.getenv("GOOGLE_SHEET_TAB", "Sheet1").strip()
published_csv_url = os.getenv("GOOGLE_SHEET_CSV_URL", "").strip()
sync_token = os.getenv("GOOGLE_SHEET_SYNC_TOKEN", "").strip()
crm_url = os.getenv("CRM_SYNC_URL", "http://127.0.0.1:5000/api/google-sheet/leads").strip()

if not published_csv_url and not sheet_id:
    raise SystemExit("Add GOOGLE_SHEET_CSV_URL or GOOGLE_SHEET_ID to .env first.")
if not sync_token:
    raise SystemExit("Add GOOGLE_SHEET_SYNC_TOKEN to .env first.")

query = urllib.parse.urlencode({"format": "csv", "gid": sheet_tab})
csv_url = published_csv_url or f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{query}"
with urllib.request.urlopen(csv_url, timeout=30) as response:
    csv_text = io.TextIOWrapper(response, encoding="utf-8-sig").read()

csv_rows = list(csv.reader(io.StringIO(csv_text)))
if len(csv_rows) < 2:
    raise SystemExit("The published sheet does not contain a header row and data.")
def normalize_header(value):
    return "".join(str(value).lower().split())

header_row = next(
    (position for position, row in enumerate(csv_rows[:5])
     if "name" in [normalize_header(value) for value in row]
     and any(normalize_header(value) in ("phoneno.", "phoneno", "phone") for value in row)),
    0,
)
headers = [str(header).strip() for header in csv_rows[header_row]]
rows = [dict(zip(headers, row)) for row in csv_rows[header_row + 1:]]

def value(row, *names):
    normalized = {normalize_header(key): item for key, item in row.items()}
    for name in names:
        if normalize_header(name) in normalized:
            return normalized[normalize_header(name)]
    return ""

payload = []
for row in rows:
    payload.append({
        "date": value(row, "Date"),
        "full_name": value(row, "Name"),
        "phone": value(row, "Phone No.", "Phone"),
        "listing_id": value(row, "Listing ID"),
        "property_type": value(row, "Property Type"),
        "budget": value(row, "Price of Property"),
        "location": value(row, "Locality"),
        "property_name": value(row, "Project"),
        "source": value(row, "Response From") or "99Acres",
        "notes": value(row, "Sunil Remarks", "Remarks", "Notes"),
    })

payload = [lead for lead in payload if str(lead["full_name"]).strip() and str(lead["phone"]).strip()]
created = 0
duplicates = 0
duplicate_details = []
errors = []
for start in range(0, len(payload), 100):
    request = urllib.request.Request(
        crm_url,
        data=json.dumps(payload[start:start + 100]).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-CRM-Sync-Token": sync_token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
        created += result.get("created", 0)
        duplicates += result.get("duplicates", 0)
        duplicate_details.extend(result.get("duplicate_details", []))
        errors.extend(result.get("errors", []))

print(f"Google Sheet sync complete: {created} new, {duplicates} duplicate, {len(errors)} invalid.")
if duplicate_details:
    print("Duplicate leads:")
    for duplicate in duplicate_details:
        print(f"- {duplicate['name']} | {duplicate['phone']} | existing CRM ID: {duplicate['lead_id']}")
=======
import csv
import io
import json
import os
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
sheet_tab = os.getenv("GOOGLE_SHEET_TAB", "Sheet1").strip()
published_csv_url = os.getenv("GOOGLE_SHEET_CSV_URL", "").strip()
sync_token = os.getenv("GOOGLE_SHEET_SYNC_TOKEN", "").strip()
crm_url = os.getenv("CRM_SYNC_URL", "http://127.0.0.1:5000/api/google-sheet/leads").strip()

if not published_csv_url and not sheet_id:
    raise SystemExit("Add GOOGLE_SHEET_CSV_URL or GOOGLE_SHEET_ID to .env first.")
if not sync_token:
    raise SystemExit("Add GOOGLE_SHEET_SYNC_TOKEN to .env first.")

query = urllib.parse.urlencode({"format": "csv", "gid": sheet_tab})
csv_url = published_csv_url or f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{query}"
with urllib.request.urlopen(csv_url, timeout=30) as response:
    csv_text = io.TextIOWrapper(response, encoding="utf-8-sig").read()

csv_rows = list(csv.reader(io.StringIO(csv_text)))
if len(csv_rows) < 2:
    raise SystemExit("The published sheet does not contain a header row and data.")
def normalize_header(value):
    return "".join(str(value).lower().split())

header_row = next(
    (position for position, row in enumerate(csv_rows[:5])
     if "name" in [normalize_header(value) for value in row]
     and any(normalize_header(value) in ("phoneno.", "phoneno", "phone") for value in row)),
    0,
)
headers = [str(header).strip() for header in csv_rows[header_row]]
rows = [dict(zip(headers, row)) for row in csv_rows[header_row + 1:]]

def value(row, *names):
    normalized = {normalize_header(key): item for key, item in row.items()}
    for name in names:
        if normalize_header(name) in normalized:
            return normalized[normalize_header(name)]
    return ""

payload = []
for row in rows:
    payload.append({
        "date": value(row, "Date"),
        "full_name": value(row, "Name"),
        "phone": value(row, "Phone No.", "Phone"),
        "listing_id": value(row, "Listing ID"),
        "property_type": value(row, "Property Type"),
        "budget": value(row, "Price of Property"),
        "location": value(row, "Locality"),
        "property_name": value(row, "Project"),
        "source": value(row, "Response From") or "99Acres",
        "notes": value(row, "Sunil Remarks", "Remarks", "Notes"),
    })

payload = [lead for lead in payload if str(lead["full_name"]).strip() and str(lead["phone"]).strip()]
created = 0
duplicates = 0
duplicate_details = []
errors = []
for start in range(0, len(payload), 100):
    request = urllib.request.Request(
        crm_url,
        data=json.dumps(payload[start:start + 100]).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-CRM-Sync-Token": sync_token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
        created += result.get("created", 0)
        duplicates += result.get("duplicates", 0)
        duplicate_details.extend(result.get("duplicate_details", []))
        errors.extend(result.get("errors", []))

print(f"Google Sheet sync complete: {created} new, {duplicates} duplicate, {len(errors)} invalid.")
if duplicate_details:
    print("Duplicate leads:")
    for duplicate in duplicate_details:
        print(f"- {duplicate['name']} | {duplicate['phone']} | existing CRM ID: {duplicate['lead_id']}")
>>>>>>> 2dfde9a6f2b20d139cc6a99df0de44195959d580
