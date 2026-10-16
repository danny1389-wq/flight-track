"""Rotating nonstop sweep SYD<->SGN (Australian market, AUD) via SerpApi. Flags fares at or under CAP and writes report.md."""
import csv, json, os, random, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST, STEP_DAYS = date(2027, 8, 1), date(2027, 11, 15), 4   # departure dates to sweep
TRIP_DAYS = [12, 15]                                               # trip lengths to sweep
CAP = 500        # A$ - fares at or under this are flagged
PER_RUN = 7      # searches per run: about 217 a month, inside SerpApi's free 250
OUT = "data/prices.csv"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]
KEY = os.environ["SERPAPI_KEY"]
USER = "danny1389-wq"   # GitHub username that gets the report email


class HardError(Exception):
    pass


def all_combos():
    combos, d = [], FIRST
    while d <= LAST:
        for n in TRIP_DAYS:
            combos.append((d, d + timedelta(days=n), n))
        d += timedelta(days=STEP_DAYS)
    return combos


def todays_batch(today):
    combos = all_combos()
    start = (today.toordinal() * PER_RUN) % len(combos)
    return [combos[(start + i) % len(combos)] for i in range(PER_RUN)]


def cheapest(depart, ret):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": ORIGIN, "arrival_id": DEST,
        "outbound_date": depart.isoformat(), "return_date": ret.isoformat(),
        "type": 1, "stops": 1, "currency": "AUD", "hl": "en", "gl": "au", "api_key": KEY})
    with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
        data = json.load(r)
    if "error" in data:
        msg = str(data["error"])
        if any(w in msg.lower() for w in ("api key", "run out", "limit", "plan", "account")):
            raise HardError(msg)
        return None   # no flights for these dates (usually not on sale yet)
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


def link(d, ret):
    q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def write_report(today):
    hist = defaultdict(list)
    with open(OUT) as fh:
        for r in csv.DictReader(fh):
            hist[(r["depart"], r["return"])].append(r)
    now = date.fromisoformat(today)
    recent, todays = [], []
    for (d, ret), a in hist.items():
        a.sort(key=lambda r: r["checked"])
        last = a[-1]
        price = float(last["price"])
        age = (now - date.fromisoformat(last["checked"])).days
        if age <= 10:
            recent.append((price, d, ret, last["airline"], last["checked"]))
        if last["checked"] == today:
            before = [float(r["price"]) for r in a[:-1]]
            if not before:
                change = "first reading"
            elif price < before[-1]:
                change = f"down A${before[-1] - price:.0f}"
            elif price > before[-1]:
                change = f"up A${price - before[-1]:.0f}"
            else:
                change = "no change"
            todays.append((price, d, ret, last["airline"], change))
    recent.sort(); todays.sort()
    deals = [r for r in recent if r[0] <= CAP]
    out = [f"@{USER} Fare report for {today}: Sydney to Ho Chi Minh City, nonstop, 12 to 15 day trips.", ""]
    if deals:
        out += [f"**Under A${CAP} (latest reading in the last 10 days):**", "",
                "| Trip | Price | Airline | Checked | Link |", "|---|---|---|---|---|"]
        for price, d, ret, airline, checked in deals:
            out.append(f"| {pretty(d)} to {pretty(ret)} | A${price:.0f} | {airline} | {pretty(checked)} | [Search]({link(d, ret)}) |")
    else:
        out.append(f"**Nothing at or under A${CAP} right now.**")
        if recent:
            price, d, ret, airline, _ = recent[0]
            out.append(f"Cheapest recent reading: A${price:.0f} with {airline}, {pretty(d)} to {pretty(ret)}.")
    out += ["", "**Checked today:**", ""]
    if todays:
        out += ["| Trip | Price | Change | Airline |", "|---|---|---|---|"]
        for price, d, ret, airline, change in todays:
            out.append(f"| {pretty(d)} to {pretty(ret)} | A${price:.0f} | {change} | {airline} |")
    else:
        out.append("No nonstop fares found in today's batch (those dates may not be on sale yet).")
    out += ["", "Prices are Australian dollars for 1 adult and may not include checked baggage. Confirm on the booking page before buying."]
    open("report.md", "w").write("\n".join(out) + "\n")


def main():
    os.makedirs("data", exist_ok=True)
    new_file = not os.path.exists(OUT)
    today = datetime.now(timezone.utc).date()
    ok = empty = hard = 0
    with open(OUT, "a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(FIELDS)
        for d, ret, n in todays_batch(today):
            try:
                best = cheapest(d, ret)
                if best:
                    w.writerow([today.isoformat(), d, ret, n, *best]); ok += 1
                else:
                    empty += 1
            except (HardError, urllib.error.HTTPError) as e:
                hard += 1
                print(f"{d} +{n}d error: {e}")
            except Exception as e:
                empty += 1
                print(f"{d} +{n}d no result: {e}")
            fh.flush()
            time.sleep(random.uniform(1, 3))
    print(f"saved {ok}, no fares {empty}, errors {hard}")
    if hard == PER_RUN:
        raise SystemExit("Every search failed; check the SerpApi key and monthly allowance.")
    write_report(today.isoformat())


if __name__ == "__main__":
    main()
