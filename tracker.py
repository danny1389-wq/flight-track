"""Logs the cheapest SYD<->SGN return fare for a grid of dates. Run daily by GitHub Actions."""
import csv, os, random, re, time
from datetime import date, datetime, timedelta, timezone
from fast_flights import FlightData, Passengers, get_flights

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST, STEP_DAYS = date(2027, 8, 1), date(2027, 11, 15), 9   # departure window
TRIP_DAYS = [12, 15]                                               # trip lengths to track
OUT = "data/prices.csv"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]


def cheapest(depart, ret):
    res = get_flights(
        flight_data=[
            FlightData(date=depart.isoformat(), from_airport=ORIGIN, to_airport=DEST),
            FlightData(date=ret.isoformat(), from_airport=DEST, to_airport=ORIGIN),
        ],
        trip="round-trip", seat="economy", passengers=Passengers(adults=1),
        fetch_mode="fallback",
    )
    best = None
    for f in res.flights:
        digits = re.sub(r"[^\d.]", "", f.price.replace(",", ""))
        if digits and (best is None or float(digits) < best[0]):
            best = (float(digits), f.name.replace(",", " "), f.stops)
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
        d = FIRST
        while d <= LAST:
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
                time.sleep(random.uniform(4, 8))   # be polite
            d += timedelta(days=STEP_DAYS)
    print(f"saved {ok}, no result {failed}")
    if ok == 0:
        raise SystemExit("No fares saved; check the log above.")


if __name__ == "__main__":
    main()
