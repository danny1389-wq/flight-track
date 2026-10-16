"""Logs the cheapest nonstop SYD<->SGN return fare (Australian market, AUD) via SerpApi and writes report.md."""
import csv, json, os, random, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
DEPARTURES = [date(2027, 8, 1), date(2027, 8, 10), date(2027, 8, 19), date(2027, 8, 28),
              date(2027, 9, 15), date(2027, 10, 12), date(2027, 11, 8)]
TRIP_DAYS = 14   # 7 searches a day = about 217 a month, inside SerpApi's free 250
OUT = "data/prices.csv"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]
KEY = os.environ["SERPAPI_KEY"]
USER = "danny1389-wq"   # GitHub username that gets the report email


def cheapest(depart, ret):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": ORIGIN, "arrival_id": DEST,
        "outbound_date": depart.isoformat(), "return_date": ret.isoformat(),
        "type": 1, "stops": 1, "currency": "AUD", "hl": "en", "gl": "au", "api_key": KEY})
    with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(data["error"])
    best = None
    for f in data.get("best_flights", []) + data.get("other_flights", []):
        price = f.get("price")
        if price is None or f.get("layovers"):
            continue   # nonstop only
        if best is None or price < best[0]:
            legs = f.get("flights") or [{}]
            airline = (legs[0].get("airline") or "").replace(",", " ")
            best = (float(price), airline, 0)
    return best


def pretty(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def write_report(today):
    hist = defaultdict(list)
    with open(OUT) as fh:
        for r in csv.DictReader(fh):
            hist[(r["depart"], r["return"])].append(r)
    rows = []
    for (d, ret), a in hist.items():
        a.sort(key=lambda r: r["checked"])
        if a[-1]["checked"] != today:
            continue
        price = float(a[-1]["price"])
        prices_before = [float(r["price"]) for r in a[:-1]]
        rows.append((price, d, ret, a[-1]["airline"], prices_before))
    rows.sort()
    table, drops, lows = [], [], []
    for price, d, ret, airline, before in rows:
        name = f"{pretty(d)} to {pretty(ret)}"
        if not before:
            change = "first reading"
        elif price < before[-1]:
            change = f"down A${before[-1] - price:.0f}"; drops.append(f"{name} (A${before[-1]:.0f} to A${price:.0f})")
        elif price > before[-1]:
            change = f"up A${price - before[-1]:.0f}"
        else:
            change = "no change"
        if before and price < min(before):
            lows.append(name)
        low = min(before + [price])
        q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
        url = "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)
        table.append(f"| {name} | A${price:.0f} | {change} | A${low:.0f} | {airline} | [Search]({url}) |")
    out = [f"@{USER} Fare report for {today}: Sydney to Ho Chi Minh City, nonstop, {TRIP_DAYS}-day trips.", ""]
    if rows:
        p, d, ret, airline, _ = rows[0]
        out.append(f"**Cheapest today:** A${p:.0f} with {airline}, {pretty(d)} to {pretty(ret)}.")
    out.append(f"**New lows:** {', '.join(lows) if lows else 'none'}")
    out.append(f"**Price drops since last check:** {'; '.join(drops) if drops else 'none'}")
    out += ["", "| Trip | Today | Change | Lowest seen | Airline | Link |", "|---|---|---|---|---|---|"] + table
    out += ["", "Prices are Australian dollars for 1 adult and may not include checked baggage. Confirm on the booking page before buying."]
    open("report.md", "w").write("\n".join(out) + "\n")


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
            ret = d + timedelta(days=TRIP_DAYS)
            try:
                best = cheapest(d, ret)
                if best:
                    w.writerow([today, d, ret, TRIP_DAYS, *best]); ok += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"{d} failed: {e}")
            fh.flush()
            time.sleep(random.uniform(1, 3))
    print(f"saved {ok}, no result {failed}")
    if ok == 0:
        raise SystemExit("No fares saved; check the log above.")
    write_report(today)


if __name__ == "__main__":
    main()
