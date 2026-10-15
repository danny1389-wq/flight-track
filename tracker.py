"""Logs the cheapest SYD<->SGN return fare (Australian market, AUD) via SerpApi. Run by GitHub Actions."""
import csv, json, os, random, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
DEPARTURES = [date(2027, 8, 1), date(2027, 8, 10), date(2027, 8, 19), date(2027, 8, 28),
              date(2027, 9, 15), date(2027, 10, 12), date(2027, 11, 8)]
TRIP_DAYS = [12, 15]
OUT = "data/prices.csv"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]
KEY = os.environ["SERPAPI_KEY"]


def cheapest(depart, ret):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": ORIGIN, "arrival_id": DEST,
        "outbound_date": depart.isoformat(), "return_date": ret.isoformat(),
        "type": 1, "currency": "AUD", "hl": "en", "gl": "au", "api_key": KEY})
    with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(data["error"])
    best = None
    for f in data.get("best_flights", []) + data.get("other_flights", []):
        price = f.get("price")
        if price is None:
            continue
        if best is None or price < best[0]:
            legs = f.get("flights") or [{}]
            airline = (legs[0].get("airline") or "").replace(",", " ")
            best = (float(price), airline, len(f.get("layovers", [])))
    return best


def main():
    os.makedirs("data", exist_ok=True)
    new_file = not os.path.exists(OUT)
    today = datetime.now(timezone.utc).date().isoformat()
    ok = failed = 0
    with open(OUT, "a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(FIELDS)
        for d in DEPARTURES:
            for n in TRIP_DAYS:
                ret = d + timedelta(days=n)
                try:
                    best = cheapest(d, ret)
                    if best:
                        w.writerow([today, d, ret, n, *best]); ok += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    print(f"{d} +{n}d failed: {e}")
                fh.flush()
                time.sleep(random.uniform(1, 3))
    print(f"saved {ok}, no result {failed}")
    if ok == 0:
        raise SystemExit("No fares saved; check the log above.")


if __name__ == "__main__":
    main()
