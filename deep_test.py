"""One-off test: does SerpApi's deep_search mode (which mirrors the browser) show the cheap Vietjet fares?
Uses 3 searches. Writes what it saw to data/deep_test.txt."""
import json, os, urllib.parse, urllib.request

KEY = os.environ.get("SERPAPI_KEY")
TESTS = [("one-way", dict(departure_id="SYD", arrival_id="SGN", outbound_date="2027-08-16", type=2)),
         ("one-way", dict(departure_id="SGN", arrival_id="SYD", outbound_date="2027-08-31", type=2)),
         ("round trip", dict(departure_id="SYD", arrival_id="SGN", outbound_date="2027-08-16", return_date="2027-08-31", type=1))]
lines = []
for label, params in TESTS:
    p = dict(engine="google_flights", currency="AUD", hl="en", gl="au", deep_search="true", show_hidden="true", api_key=KEY or "")
    p.update(params)
    lines.append(f"=== {label} {params['departure_id']} -> {params['arrival_id']} on {params['outbound_date']}"
                 + (f" returning {params['return_date']}" if "return_date" in params else "") + " (deep_search + show_hidden) ===")
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=180) as r:
            data = json.load(r)
    except Exception as e:
        lines.append(f"request failed: {e}")
        continue
    if "error" in data:
        lines.append(f"error: {data['error']}")
        continue
    meta = data.get("search_metadata", {})
    lines.append(f"status={meta.get('status')} time={meta.get('total_time_taken')}s")
    n = 0
    for group in ("best_flights", "other_flights"):
        for f in data.get(group, []):
            n += 1
            legs = f.get("flights") or [{}]
            airlines = " + ".join((x.get("airline") or "?") for x in legs)
            lines.append(f"{group:13} {airlines:40} stops={len(f.get('layovers') or [])} price=A${f.get('price')}")
    lines.append(f"{n} flights; cheapest-from per Google: {data.get('price_insights', {}).get('lowest_price')}")
os.makedirs("data", exist_ok=True)
open("data/deep_test.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
