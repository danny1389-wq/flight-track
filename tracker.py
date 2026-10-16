"""Hourly free sweep SYD<->SGN via fast-flights. Nonstop only, 12 and 15 day trips.
Saves the latest estimated Australian price per trip to data/latest.json (the dashboard reads this),
logs price changes to data/prices.csv, and writes report.md only when there is something to email."""
import csv, json, os, random, re, signal, time, urllib.parse
from datetime import date, datetime, timedelta, timezone
from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST, STEP_DAYS = date(2027, 8, 1), date(2027, 11, 15), 1
TRIP_DAYS = [12, 15]
AIRLINES = ("vietjet", "jetstar")   # only these airlines are tracked
ALERT = 400      # A$ a trip newly at or under this triggers its own urgent email
CAP = 500        # A$ estimated Australian price at or under this counts as a deal
RATIO = 0.837    # Google's A$ price for you divided by what this tracker sees (487 / 582)
HIST = "data/prices.csv"
LATEST = "data/latest.json"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]
USER = "danny1389-wq"


def _too_slow(signum, frame):
    raise TimeoutError("search took longer than 60 seconds")


signal.signal(signal.SIGALRM, _too_slow)


def cheapest(depart, ret):
    filt = create_filter(
        flight_data=[FlightData(date=depart.isoformat(), from_airport=ORIGIN, to_airport=DEST),
                     FlightData(date=ret.isoformat(), from_airport=DEST, to_airport=ORIGIN)],
        trip="round-trip", seat="economy", passengers=Passengers(adults=1))
    res = get_flights_from_filter(filt, currency="AUD", mode="fallback")
    best = None
    for f in res.flights:
        if f.stops != 0:
            continue   # nonstop only
        if not any(a in f.name.lower() for a in AIRLINES):
            continue   # budget airlines only
        digits = re.sub(r"[^\d.]", "", f.price.replace(",", ""))
        if digits and (best is None or float(digits) < best[0]):
            best = (float(digits), f.name.replace(",", " "))
    if best:
        return round(best[0] * RATIO), best[1]   # estimated Australian price
    return None


def pretty(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def link(d, ret):
    q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def table(rows):
    out = ["| Trip | Est. price | Airline | Link |", "|---|---|---|---|"]
    for t in rows:
        out.append(f"| {pretty(t['depart'])} to {pretty(t['return'])} | A${t['price']} | {t['airline']} | [Check on Google]({link(t['depart'], t['return'])}) |")
    return out


def write_report(trips, new_deals, summary):
    ordered = sorted(trips.values(), key=lambda t: t["price"])
    deals = [t for t in ordered if t["price"] <= CAP]
    out = [f"@{USER} Fare update: Sydney to Ho Chi Minh City, nonstop, 12 and 15 day trips.", ""]
    if new_deals:
        out += [f"**New: now estimated at or under A${CAP}**", ""] + table(sorted(new_deals, key=lambda t: t["price"])) + [""]
    if summary or not new_deals:
        if deals:
            out += [f"**All trips estimated at or under A${CAP} right now ({len(deals)})**", ""] + table(deals[:15]) + [""]
        else:
            out.append(f"**Nothing estimated at or under A${CAP} right now.**")
            if ordered:
                t = ordered[0]
                out.append(f"Cheapest: about A${t['price']} with {t['airline']}, {pretty(t['depart'])} to {pretty(t['return'])}.")
            out.append("")
        out.append(f"Tracking {len(trips)} trips.")
        out.append("")
    out.append("Prices are estimates of what Google shows in Australia (this tracker sees a US view, so they can be off by a few percent). Click the link and confirm before buying. Checked baggage may not be included.")
    open("report.md", "w").write("\n".join(out) + "\n")


def write_alert(great):
    out = [f"@{USER} **A trip has dropped to A${ALERT} or under.** Sydney to Ho Chi Minh City, nonstop.", ""]
    out += table(sorted(great, key=lambda t: t["price"]))
    out += ["", "Prices are estimates. Click the link and confirm on Google Flights before buying, and check what checked baggage costs."]
    open("alert.md", "w").write("\n".join(out) + "\n")


def main():
    os.makedirs("data", exist_ok=True)
    for old_file in ("report.md", "alert.md"):
        if os.path.exists(old_file):
            os.remove(old_file)
    now = datetime.now(timezone.utc)
    prev = {}
    if os.path.exists(LATEST):
        try:
            prev = json.load(open(LATEST))
        except Exception:
            prev = {}
    prev_trips = {k: t for k, t in prev.get("trips", {}).items()
                  if any(a in t["airline"].lower() for a in AIRLINES)}
    trips = dict(prev_trips)
    new_hist = not os.path.exists(HIST)
    new_deals, great, ok, none = [], [], 0, 0
    with open(HIST, "a", newline="") as fh:
        w = csv.writer(fh)
        if new_hist:
            w.writerow(FIELDS)
        d = FIRST
        while d <= LAST:
            for n in TRIP_DAYS:
                ret = d + timedelta(days=n)
                key = f"{d}|{ret}"
                try:
                    signal.alarm(60)   # hard stop if a search hangs
                    best = cheapest(d, ret)
                    signal.alarm(0)
                except Exception as e:
                    signal.alarm(0)
                    best = None
                    print(f"{d} +{n}d failed: {e}", flush=True)
                if best:
                    price, airline = best
                    old = prev_trips.get(key)
                    trips[key] = {"depart": str(d), "return": str(ret), "days": n,
                                  "price": price, "airline": airline, "seen": now.isoformat()}
                    if not old or old["price"] != price:
                        w.writerow([now.isoformat(), d, ret, n, price, airline, 0])
                    if price <= CAP and (not old or old["price"] > CAP):
                        new_deals.append(trips[key])
                    if price <= ALERT and (not old or old["price"] > ALERT):
                        great.append(trips[key])
                    ok += 1
                else:
                    none += 1
                fh.flush()
                                time.sleep(random.uniform(1, 2.5))
            d += timedelta(days=STEP_DAYS)
    print(f"saved {ok}, no nonstop/no result {none}")
    if ok == 0:
        raise SystemExit("No fares found; check the log above.")
    # forget trips not seen for 3 days (for example, flights that stopped being sold)
    cutoff = now - timedelta(days=3)
    trips = {k: t for k, t in trips.items() if datetime.fromisoformat(t["seen"]) >= cutoff}
    # one summary a day, around 7am Sydney (20:00 UTC)
    summary_key = (now - timedelta(hours=20)).date().isoformat()
    summary_due = prev.get("last_summary") != summary_key
    manual = os.environ.get("EVENT") == "workflow_dispatch"
    if new_deals or summary_due or manual:
        write_report(trips, new_deals, summary_due or manual)
    if great:
        write_alert(great)
    json.dump({"updated": now.isoformat(), "cap": CAP, "last_summary": summary_key if summary_due else prev.get("last_summary"),
               "trips": trips}, open(LATEST, "w"))


if __name__ == "__main__":
    main()
