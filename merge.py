"""Combined Jetstar + Vietjet comparison, SYD<->SGN, nonstop, AUD, trips of exactly 12 or 15 days.
READ-ONLY on the other trackers' data: reads data/latest.json (Jetstar tracker) and data/kiwi_vj/legs.json (Kiwi checker).
Writes only inside data/combined/. Makes NO web requests (except the optional GitHub issue email when alerts are switched on).
A date with no reading is UNKNOWN. It is never treated as 'no flight'."""
import csv, json, os, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

JETSTAR_FILE = "data/latest.json"
KIWI_FILE = "data/kiwi_vj/legs.json"
OUT = "data/combined"
ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST = date(2027, 8, 1), date(2027, 11, 15)
TRIP_DAYS = [12, 15]
CAP, ALERT = 500, 400
FRESH_HOURS = {"jetstar": 3, "kiwi": 12}     # older than this = stale
USER = "danny1389-wq"
JETSTAR_BAG = "Checked baggage not verified"
# Estimated-total alerts: seat-only return fare + the baggage costs that are actually known (per passenger, 1 x 20 kg checked + 7 kg carry-on per flight).
# Jetstar legs: A$58 checked + A$33 carry-on (confirmed by the user's own check). Vietjet legs: nothing added (no confirmed price), so the total is "so far".
JETSTAR_BAG_AUD, JETSTAR_CARRY_AUD = 58, 33


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def parse_time(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def gf_link(day):
    q = f"Flights from {ORIGIN} to {DEST} on {day} one way nonstop"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def make_leg(direction, day, raw, source, now):
    """Normalise one one-way reading. Keeps the original source, timestamp, price and baggage text."""
    frm, to = (ORIGIN, DEST) if direction == "out" else (DEST, ORIGIN)
    seen = parse_time(raw.get("seen"))
    age = (now - seen).total_seconds() / 3600 if seen else None
    status = "current" if age is not None and age <= FRESH_HOURS[source] else "stale"
    leg = {"direction": direction, "date": day, "from": frm, "to": to, "price": float(raw["p"]),
           "airline": raw.get("a") or ("Jetstar" if source == "jetstar" else "Vietjet"),
           "source": "jetstar-tracker (Google Flights reading)" if source == "jetstar" else "kiwi.com MCP",
           "seen": raw.get("seen"), "age_hours": round(age, 1) if age is not None else None, "status": status}
    if source == "jetstar":
        leg.update({"flight": None, "itinerary_id": None, "url": gf_link(day), "baggage": JETSTAR_BAG,
                    "price_note": "Google Flights estimate"})
    else:
        bag = raw.get("checked_bag")
        leg.update({"flight": raw.get("flight"), "itinerary_id": raw.get("id"), "url": raw.get("url"),
                    "baggage": ("No checked bag in this fare (per Kiwi)" if bag == 0 else
                                f"{bag} checked bag(s) (per Kiwi)" if isinstance(bag, int) else JETSTAR_BAG),
                    "price_note": "Kiwi all-in price, includes Kiwi service fee"})
    return leg


def post_issue(title, body):
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token, no email sent.", flush=True)
        return
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues",
                                 data=json.dumps({"title": title, "body": body}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "fare-tracker"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print(f"Email sent: {title}", flush=True)
    except Exception as e:
        print(f"Could not send email ({e})", flush=True)


def build(jet, kiwi, now):
    sources = {"jetstar": (jet or {}).get("legs") or {}, "kiwi": (kiwi or {}).get("legs") or {}}
    legs = {"out": {}, "back": {}}   # direction -> date -> [leg, ...]
    for src, data in sources.items():
        for direction in ("out", "back"):
            for day, raw in (data.get(direction) or {}).items():
                legs[direction].setdefault(day, []).append(make_leg(direction, day, raw, src, now))
    trips, d = [], FIRST
    while d <= LAST:
        for n in TRIP_DAYS:
            r = (d + timedelta(days=n)).isoformat()
            for o in legs["out"].get(d.isoformat(), []):
                for b in legs["back"].get(r, []):
                    status = "current" if o["status"] == b["status"] == "current" else "stale"
                    trips.append({"id": f"{d}|{r}|{o['airline']}|{b['airline']}", "depart": str(d), "return": r, "days": n,
                                  "price": round(o["price"] + b["price"]), "combo": f"{o['airline']} + {b['airline']}",
                                  "has_vietjet": "Vietjet" in (o["airline"], b["airline"]),
                                  "status": status, "verified": False, "out": o, "back": b})
        d += timedelta(days=1)
    trips.sort(key=lambda t: (t["price"], t["depart"]))
    return trips, legs


def coverage(legs):
    cov = {}
    for src in ("jetstar-tracker (Google Flights reading)", "kiwi.com MCP"):
        cov[src] = {}
        for direction in ("out", "back"):
            days = sorted(day for day, ls in legs[direction].items() if any(l["source"] == src for l in ls))
            cov[src][direction] = {"dates_with_price": len(days), "first": days[0] if days else None, "last": days[-1] if days else None}
    return cov


def alerts(trips, state, now, enabled):
    """Dedupe: a trip alerts once per price. Again only if its price drops below the last alerted price, or a CURRENT
    reading showed it above the cap and it later falls back into range. Missing data never resets anything."""
    todo = {"deal": [], "urgent": []}
    cur = {t["id"]: t for t in trips if t["status"] == "current"}
    for tid, st in state.items():                       # re-arm only on a current reading above the cap
        t = cur.get(tid)
        if t and t["price"] > CAP:
            st["deal"], st["urgent"] = None, None
    for t in cur.values():
        if not t["has_vietjet"] or t["price"] > CAP:    # Jetstar-only trips already get the Jetstar tracker's emails
            continue
        st = state.setdefault(t["id"], {"deal": None, "urgent": None})
        if st["deal"] is None or t["price"] < st["deal"]:
            todo["deal"].append(t)
            st["deal"] = t["price"]
        if t["price"] <= ALERT and (st["urgent"] is None or t["price"] < st["urgent"]):
            todo["urgent"].append(t)
            st["urgent"] = t["price"]
    return todo


def est_total(t):
    """(estimated total so far, known baggage extras, True if a Vietjet leg's baggage is NOT included)."""
    extra, vj = 0, False
    for leg in (t["out"], t["back"]):
        if leg["airline"] == "Jetstar":
            extra += JETSTAR_BAG_AUD + JETSTAR_CARRY_AUD
        else:
            vj = True
    return t["price"] + extra, extra, vj


def total_alerts(trips, state):
    """Same A$500 / A$400 thresholds and the same once-per-price dedupe as alerts(), but on the estimated total.
    Uses its own memory keys (tdeal / turgent) so the seat-only alerts are not affected."""
    todo = {"deal": [], "urgent": []}
    cur = {t["id"]: t for t in trips if t["status"] == "current"}
    for tid, st in state.items():
        t = cur.get(tid)
        if t and est_total(t)[0] > CAP:
            st["tdeal"], st["turgent"] = None, None
    for t in cur.values():
        total = est_total(t)[0]
        if total > CAP:
            continue
        st = state.setdefault(t["id"], {"deal": None, "urgent": None})
        if st.get("tdeal") is None or total < st["tdeal"]:
            todo["deal"].append(t)
            st["tdeal"] = total
        if total <= ALERT and (st.get("turgent") is None or total < st["turgent"]):
            todo["urgent"].append(t)
            st["turgent"] = total
    todo["deal"].sort(key=lambda t: est_total(t)[0])
    todo["urgent"].sort(key=lambda t: est_total(t)[0])
    return todo


def main():
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(timezone.utc)
    jet, kiwi = load(JETSTAR_FILE), load(KIWI_FILE)
    trips, legs = build(jet, kiwi, now)
    cov = coverage(legs)
    json.dump({"updated": now.isoformat(), "cap": CAP, "alert": ALERT, "fresh_hours": FRESH_HOURS,
               "inputs": {"jetstar_updated": (jet or {}).get("updated"), "kiwi_updated": (kiwi or {}).get("updated"),
                          "kiwi_stopped": (kiwi or {}).get("stopped")},
               "coverage": cov, "trips": trips}, open(f"{OUT}/trips.json", "w", encoding="utf-8"))
    new = not os.path.exists(f"{OUT}/history.csv")
    with open(f"{OUT}/history.csv", "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["checked", "depart", "return", "days", "price", "out_airline", "out_price", "out_seen", "back_airline",
                        "back_price", "back_seen", "status"])
        for t in [x for x in trips if x["price"] <= CAP] or trips[:10]:
            w.writerow([now.isoformat(), t["depart"], t["return"], t["days"], t["price"], t["out"]["airline"], t["out"]["price"],
                        t["out"]["seen"], t["back"]["airline"], t["back"]["price"], t["back"]["seen"], t["status"]])
    deals = [t for t in trips if t["price"] <= CAP]
    print(f"{len(trips)} combined trips. {len(deals)} at or under A${CAP}. "
          f"{sum(1 for t in deals if t['status'] == 'current')} of those are current.", flush=True)
    enabled = (os.environ.get("COMBINED_ALERTS") or "").strip().lower() == "yes"
    if not enabled:
        print("Alerts are OFF (nothing sent, alert memory untouched).", flush=True)
        return
    state = load(f"{OUT}/state.json") or {}
    todo = alerts(trips, state, now, True)
    row = lambda t: (f"| {t['depart']} to {t['return']} | {t['days']} days | A${t['price']} | {t['out']['airline']} {t['out'].get('flight') or ''} "
                     f"A${t['out']['price']:.0f} + {t['back']['airline']} {t['back'].get('flight') or ''} A${t['back']['price']:.0f} | "
                     f"[out]({t['out']['url']}) [back]({t['back']['url']}) |")
    head = ["| Dates | Length | Total | Legs | Links |", "|---|---|---|---|---|"]
    note = ("Two separate one-way tickets. Kiwi prices are all-in per adult (include Kiwi's service fee). "
            "Jetstar prices are Google Flights readings. Checked baggage is not verified for any leg. "
            "Nothing here is confirmed bookable until you check the links.")
    if todo["deal"]:
        post_issue(f"Combined Vietjet/Jetstar fares {now:%Y-%m-%d %H:%M} UTC",
                   "\n".join([f"@{USER} Trips at or under A${CAP} that include a Vietjet leg:", ""] + head + [row(t) for t in todo["deal"][:15]] + ["", note]))
    if todo["urgent"]:
        post_issue(f"ALERT - combined trip at or under A${ALERT}",
                   "\n".join([f"@{USER} **Trip at or under A${ALERT}.**", ""] + head + [row(t) for t in todo["urgent"]] + ["", note]))
    ttodo = total_alerts(trips, state)
    trow = lambda t: (f"| {t['depart']} to {t['return']} | {t['days']} days | **A${est_total(t)[0]}** | A${t['price']} | "
                      f"{t['out']['airline']} {t['out'].get('flight') or ''} A${t['out']['price']:.0f} + {t['back']['airline']} {t['back'].get('flight') or ''} A${t['back']['price']:.0f} | "
                      f"[out]({t['out']['url']}) [back]({t['back']['url']}) |")
    thead = ["| Dates | Length | Est. total | Seat-only | Legs | Links |", "|---|---|---|---|---|---|"]
    tnote = ("Estimated total per passenger = seat-only return fare + known baggage: Jetstar legs add A$58 checked bag + A$33 carry-on each. "
             "Vietjet baggage is NOT included, so a total marked 'so far' will be higher (Vietjet Deluxe was about A$57 extra per flight in one recent example, subject to live pricing). "
             "Vietjet fares are Kiwi indicative prices, not confirmed on Vietjet's website. Nothing here is confirmed bookable until you check the links.")
    if ttodo["deal"]:
        post_issue(f"Estimated total at or under A${CAP} {now:%Y-%m-%d %H:%M} UTC",
                   "\n".join([f"@{USER} Trips with an estimated total (seat-only + known baggage) at or under A${CAP}:", ""] + thead + [trow(t) for t in ttodo["deal"][:15]] + ["", tnote]))
    if ttodo["urgent"]:
        post_issue(f"ALERT - estimated total at or under A${ALERT}",
                   "\n".join([f"@{USER} **Estimated total at or under A${ALERT}.**", ""] + thead + [trow(t) for t in ttodo["urgent"]] + ["", tnote]))
    json.dump(state, open(f"{OUT}/state.json", "w", encoding="utf-8"))


if __name__ == "__main__":
    main()
