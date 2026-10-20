"""One-off MANUAL Kiwi test for Western Sydney (WSI) <-> Ho Chi Minh City (SGN). 9 requests, 15 s apart.
Read-only: prints and appends to data/kiwi_repeat.txt. Does not touch any tracker data."""
import json, time, datetime, os, urllib.request

URL = "https://mcp.kiwi.com"
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
out = []
def log(s=""):
    print(s); out.append(str(s))

def rpc(body, sid=None, t=90):
    h = dict(H)
    if sid: h["mcp-session-id"] = sid
    req = urllib.request.Request(URL, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=t) as r:
        txt = r.read().decode(); new = r.headers.get("mcp-session-id") or sid
    line = next((l for l in txt.split("\n") if l.startswith("data:")), None)
    return json.loads(line[5:] if line else txt), new

def wd(s):
    try: return datetime.date.fromisoformat(s[:10]).strftime("%a")
    except Exception: return "?"

now = datetime.datetime.utcnow()
log("\n##### WSI TEST RUN " + now.isoformat() + "Z (UTC) = " + (now + datetime.timedelta(hours=11)).strftime("%H:%M Sydney"))
sid = None
try:
    r, sid = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "fare-test", "version": "1"}}})
    try: rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception: pass
except Exception as e:
    log("INIT ERROR: %r" % e)

# (label, from, to, first date, last date or None, airline filter or None)
S = [("CONTROL: schedule start window", "WSI", "SGN", "10/01/2027", "31/01/2027", "VJ"),
     ("RANGE out", "WSI", "SGN", "01/08/2027", "15/11/2027", "VJ"),
     ("RANGE back", "SGN", "WSI", "01/08/2027", "15/11/2027", "VJ"),
     ("Sunday out", "WSI", "SGN", "15/08/2027", None, "VJ"),
     ("Wednesday out", "WSI", "SGN", "18/08/2027", None, "VJ"),
     ("Sunday back", "SGN", "WSI", "15/08/2027", None, "VJ"),
     ("Wednesday back", "SGN", "WSI", "18/08/2027", None, "VJ"),
     ("ANY AIRLINE out (nonstop)", "WSI", "SGN", "01/08/2027", "15/11/2027", None),
     ("ANY AIRLINE back (nonstop)", "SGN", "WSI", "01/08/2027", "15/11/2027", None)]
n = 2
res = {}
for lab, a, b, d, d2, al in S:
    args = {"flyFrom": a, "flyTo": b, "departureDate": d, "adults": 1, "cabinClass": "M",
            "currency": "AUD", "sort": "price", "max_sector_stopovers": 0}
    if d2: args["departureDateTo"] = d2
    if al: args["select_airlines"] = al
    log(f"\n=== {lab}: {a}->{b} {d}" + (f" to {d2}" if d2 else "") + (f" airline={al}" if al else " (any airline)"))
    try:
        n += 1
        r, _ = rpc({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                    "params": {"name": "search-flight", "arguments": args}}, sid)
        txt = (r.get("result", {}).get("content") or [{}])[0].get("text", "")
        if not txt or r.get("result", {}).get("isError"):
            log("ERROR/EMPTY (not the same as 'no flights'): " + (txt or json.dumps(r))[:500]); res[lab] = "error"; continue
        its = json.loads(txt).get("itineraries", [])
        res[lab] = len(its)
        log(f"{len(its)} itineraries" + ("  -> NO RESULTS" if not its else ""))
        for it in its[:20]:
            o = it.get("outbound") or {}
            sg = o.get("segments", [])
            fn = ",".join(f"{s.get('carrierCode','')}{s.get('flightNumber','')}" for s in sg)
            car = "/".join(dict.fromkeys(s.get("carrierName", "?") for s in sg))
            dep, arr = o.get("departureTime", ""), o.get("arrivalTime", "")
            log(f"  A${it.get('price')}  {car}  {fn}  stops={o.get('stops')} segments={len(sg)}  dep {wd(dep)} {dep}  arr {arr}  "
                f"bag={json.dumps(it.get('baggage'))}  {it.get('bookingUrl')}")
        if its: log("FULL cheapest: " + json.dumps(its[0])[:3000])
    except Exception as e:
        log("ERROR: %r" % e); res[lab] = "error"
    time.sleep(15)

log("\nSUMMARY: " + json.dumps(res))
os.makedirs("data", exist_ok=True)
with open("data/kiwi_repeat.txt", "a") as f:
    f.write("\n".join(out) + "\n")
