"""One-off test: how reliably does SerpApi deep_search show the cheap Vietjet one-way fares?
Uses 7 searches. Writes only the nonstop Vietjet/Jetstar rows to data/deep_test.txt."""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

KEY = os.environ.get("SERPAPI_KEY")
TESTS = [("SYD", "SGN", "2027-08-16"), ("SYD", "SGN", "2027-08-16"), ("SYD", "SGN", "2027-08-16"),
         ("SYD", "SGN", "2027-08-02"), ("SYD", "SGN", "2027-08-23"),
         ("SGN", "SYD", "2027-08-14"), ("SGN", "SYD", "2027-08-29")]
lines = [f"run at {datetime.now(timezone.utc).isoformat()}"]
for frm, to, day in TESTS:
    p = dict(engine="google_flights", currency="AUD", hl="en", gl="au", type=2, departure_id=frm, arrival_id=to,
             outbound_date=day, deep_search="true", show_hidden="true", api_key=KEY or "")
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=180) as r:
            data = json.load(r)
    except Exception as e:
        lines.append(f"{frm}->{to} {day}: request failed: {e}")
        continue
    if "error" in data:
        lines.append(f"{frm}->{to} {day}: error: {data['error']}")
        continue
    rows, total = [], 0
    for group in ("best_flights", "other_flights"):
        for f in data.get(group, []):
            total += 1
            legs = f.get("flights") or [{}]
            airline = (legs[0].get("airline") or "?")
            if not f.get("layovers") and any(a in airline.lower() for a in ("vietjet", "jetstar")):
                rows.append(f"{airline} A${f.get('price')} ({group})")
    lines.append(f"{frm}->{to} {day}: {total} flights; nonstop Vietjet/Jetstar: {', '.join(rows) or 'NONE'}; "
                 f"cheapest-from {data.get('price_insights', {}).get('lowest_price')}")
    time.sleep(2)
os.makedirs("data", exist_ok=True)
open("data/deep_test.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
