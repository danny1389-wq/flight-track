"""Fare tracker SYD<->SGN, nonstop Jetstar only, 12 and 15 day trips.
Scans every one-way Jetstar flight (Sydney to Ho Chi Minh City, and back) and adds the outbound and return legs for every trip.
Saves data/latest.json (the dashboard reads it), data/prices.csv (price history) and emails you through GitHub issues."""
import csv, json, os, random, re, threading, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST = date(2027, 8, 1), date(2027, 11, 15)
TRIP_DAYS = [12, 15]
AIRLINES = ("jetstar",)
ALERT = 400      # A$ a trip newly at or under this triggers its own urgent email
CAP = 500        # A$ at or under this counts as a deal
RATIO = 1.0      # Australian price divided by the price this scanner sees (set after comparing with Google)
HIST = "data/prices.csv"
LATEST = "data/latest.json"
FIELDS = ["checked", "depart", "return", "days", "price", "airline"]
USER = "danny1389-wq"


def run_with_timeout(fn, *args, seconds=60):
    box = {}

    def work():
        try:
            box["value"] = fn(*args)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"took longer than {seconds} seconds")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def post_issue(title, body):
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token here, so no email was sent.", flush=True)
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "fare-tracker"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print(f"Email sent: {title}", flush=True)
    except Exception as e:
        print(f"Could not send email ({e})", flush=True)


def leg_dates():
    """Every outbound date and every return date we need."""
    out, d = [], FIRST
    while d <= LAST:
        out.append(d)
        d += timedelta(days=1)
    back, d = [], FIRST + timedelta(days=min(TRIP_DAYS))
    while d <= LAST + timedelta(days=max(TRIP_DAYS)):
        back.append(d)
        d += timedelta(days=1)
    return out, back


def scan_leg(frm, to, day):
    """Cheapest nonstop Jetstar one-way fare on this day as (raw price, airline), or None."""
    from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
    filt = create_filter(
        flight_data=[FlightData(date=day.isoformat(), from_airport=frm, to_airport=to)],
        trip="one-way", seat="economy", passengers=Passengers(adults=1))
    res = get_flights_from_filter(filt, currency="AUD", mode="fallback")
    best = None
    for f in res.flights:
        if f.stops != 0:
            continue
        name = f.name.lower()
        airline = next((a for a in AIRLINES if a in name), None)
        if not airline:
            continue
        digits = re.sub(r"[^\d.]", "", f.price.replace(",", ""))
        if digits and (best is None or float(digits) < best[0]):
            best = (float(digits), airline.capitalize())
    return best


def pretty(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')}"


def link(d, ret):
    q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def table(rows):
    out = ["| Trip | Total | Outbound | Return | Link |", "|---|---|---|---|---|"]
    for t in rows:
        out.append(f"| {pretty(t['depart'])} to {pretty(t['return'])} | A${t['price']} | {t['out_airline']} A${t['out']} | "
                   f"{t['ret_airline']} A${t['back']} | [Check on Google]({link(t['depart'], t['return'])}) |")
    return out


def build_trips(legs, now_iso):
    trips = {}
    d = FIRST
    while d <= LAST:
        for n in TRIP_DAYS:
            r = d + timedelta(days=n)
            o, b = legs["out"].get(d.isoformat()), legs["back"].get(r.isoformat())
            if not o or not b:
                continue
            out_p, back_p = round(o["p"] * RATIO), round(b["p"] * RATIO)
            airline = o["a"] if o["a"] == b["a"] else f"{o['a']} + {b['a']}"
            trips[f"{d}|{r}"] = {"depart": str(d), "return": str(r), "days": n, "price": out_p + back_p,
                                 "airline": airline, "out": out_p, "out_airline": o["a"],
                                 "back": back_p, "ret_airline": b["a"],
                                 "seen": min(o["seen"], b["seen"])}
        d += timedelta(days=1)
    return trips


def main():
    os.makedirs("data", exist_ok=True)
    now = datetime.now(timezone.utc)
    prev = {}
    if os.path.exists(LATEST):
        try:
            prev = json.load(open(LATEST, encoding="utf-8"))
        except Exception:
            prev = {}
    if prev.get("source") != "jetstar":
        prev = {}
        with open(HIST, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(FIELDS)
    legs = prev.get("legs") or {"out": {}, "back": {}}
    old_trips = prev.get("trips", {})

    outs, backs = leg_dates()
    ok = fail = 0
    jobs = [("out", ORIGIN, DEST, d) for d in outs] + [("back", DEST, ORIGIN, d) for d in backs]
    for kind, frm, to, d in jobs:
        try:
            res = run_with_timeout(scan_leg, frm, to, d, seconds=60)
        except Exception as e:
            fail += 1
            print(f"{frm}->{to} {d} failed: {e}", flush=True)
            continue   # keep what we knew
        ok += 1
        if res is None:
            legs[kind].pop(d.isoformat(), None)
        else:
            legs[kind][d.isoformat()] = {"p": res[0], "a": res[1], "seen": now.isoformat()}
            print(f"{frm}->{to} {d}: {res[1]} raw {res[0]:.0f}", flush=True)
        time.sleep(random.uniform(1, 2.5))
    print(f"scan: {ok} legs read, {fail} failed", flush=True)
    if ok == 0:
        raise SystemExit("The scan read nothing; check the log above.")

    # keep legs for 3 days after they were last seen (e.g. flights no longer sold)
    cutoff = (now - timedelta(days=3)).isoformat()
    for kind in ("out", "back"):
        legs[kind] = {k: v for k, v in legs[kind].items() if v["seen"] >= cutoff}
    trips = build_trips(legs, now.isoformat())
    print(f"{len(trips)} trips have a price", flush=True)

    new_deals, great = [], []
    with open(HIST, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for k, t in trips.items():
            old = old_trips.get(k)
            if not old or old["price"] != t["price"]:
                w.writerow([now.isoformat(), t["depart"], t["return"], t["days"], t["price"], t["airline"]])
            if t["price"] <= CAP and (not old or old["price"] > CAP):
                new_deals.append(t)
            if t["price"] <= ALERT and (not old or old["price"] > ALERT):
                great.append(t)

    # one summary a day, around 7am Sydney (20:00 UTC)
    summary_key = (now - timedelta(hours=20)).date().isoformat()
    summary_due = prev.get("last_summary") != summary_key
    manual = os.environ.get("EVENT") == "workflow_dispatch"
    ordered = sorted(trips.values(), key=lambda t: t["price"])
    deals = [t for t in ordered if t["price"] <= CAP]
    if new_deals or summary_due or manual:
        out = [f"@{USER} Fare update: Sydney to Ho Chi Minh City, nonstop Jetstar, 12 and 15 day trips.", ""]
        if new_deals:
            out += [f"**New: now at or under A${CAP}**", ""] + table(sorted(new_deals, key=lambda t: t["price"])) + [""]
        if summary_due or manual or not new_deals:
            if deals:
                out += [f"**All trips at or under A${CAP} right now ({len(deals)})**", ""] + table(deals[:15]) + [""]
            else:
                out.append(f"**Nothing at or under A${CAP} right now.**")
                if ordered:
                    t = ordered[0]
                    out.append(f"Cheapest: A${t['price']} ({t['airline']}), {pretty(t['depart'])} to {pretty(t['return'])}.")
                out.append("")
            out += [f"{len(trips)} trips currently have a price.", ""]
        out.append("Each trip is two separate one-way tickets (outbound and return), booked separately, so check baggage and the link before buying. "
                   "Prices are estimates of what Google Flights shows in Australia.")
        post_issue(f"Fare update {now.strftime('%Y-%m-%d %H:%M')} UTC", "\n".join(out) + "\n")
    if great:
        a = ([f"@{USER} **A trip has dropped to A${ALERT} or under.** Sydney to Ho Chi Minh City, nonstop.", ""]
             + table(sorted(great, key=lambda t: t["price"]))
             + ["", "Two separate one-way tickets. Click the link and confirm on Google Flights before buying."])
        post_issue(f"ALERT - trip at or under A${ALERT} ({now.strftime('%Y-%m-%d %H:%M')} UTC)", "\n".join(a) + "\n")

    json.dump({"source": "jetstar", "updated": now.isoformat(), "cap": CAP, "ratio": RATIO,
               "last_summary": summary_key if summary_due else prev.get("last_summary"),
               "legs": legs, "trips": trips}, open(LATEST, "w", encoding="utf-8"))


if __name__ == "__main__":
    main()
