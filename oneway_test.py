"""One-off test: does SerpApi (Google Flights, Australian prices) show the cheap Vietjet ONE-WAY fares?
Uses 3 searches. Writes what it saw to data/oneway_test.txt."""
import json, os, urllib.parse, urllib.request

KEY = os.environ.get("SERPAPI_KEY")
TESTS = [("SYD", "SGN", "2027-08-16"), ("SGN", "SYD", "2027-08-31"), ("SYD", "SGN", "2027-08-02")]
lines = []
for frm, to, day in TESTS:
    q = urllib.parse.urlencode({"engine": "google_flights", "departure_id": frm, "arrival_id": to,
                                "outbound_date": day, "type": 2, "currency": "AUD", "hl": "en", "gl": "au", "api_key": KEY or ""})
    lines.append(f"=== one-way {frm} -> {to} on {day} ===")
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
            data = json.load(r)
    except Exception as e:
        lines.append(f"request failed: {e}")
        continue
    if "error" in data:
        lines.append(f"error: {data['error']}")
        continue
    for group in ("best_flights", "other_flights"):
        for f in data.get(group, []):
            legs = f.get("flights") or [{}]
            airlines = " + ".join((x.get("airline") or "?") for x in legs)
            stops = len(f.get("layovers") or [])
            lines.append(f"{group:13} {airlines:40} stops={stops} price=A${f.get('price')}")
    lines.append(f"cheapest-from per Google: {data.get('price_insights', {}).get('lowest_price')}")
os.makedirs("data", exist_ok=True)
open("data/oneway_test.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
