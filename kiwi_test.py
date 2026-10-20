"""One-off test: does Kiwi's public MCP endpoint return the cheap Vietjet fares?
Plain HTTPS JSON-RPC, no browser, no proxies. 4 target searches, 15s apart. Writes data/kiwi_test.txt"""
import json, time, datetime, urllib.request

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
        txt = r.read().decode()
        new = r.headers.get("mcp-session-id") or sid
    line = next((l for l in txt.split("\n") if l.startswith("data:")), None)
    return json.loads(line[5:] if line else txt), new

log("Kiwi MCP test run at " + datetime.datetime.utcnow().isoformat() + "Z (UTC)")
sid = None
try:
    r, sid = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "fare-test", "version": "1"}}})
    log("initialize OK: " + json.dumps(r)[:300])
    try: rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception: pass
    r, _ = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    for t in r.get("result", {}).get("tools", []):
        log("TOOL " + t["name"] + " params: " + ",".join(t.get("inputSchema", {}).get("properties", {}).keys()))
except Exception as e:
    log("INIT/TOOLS ERROR: %r" % e)

SEARCHES = [("SYD","SGN","2027-08-16"),("SGN","SYD","2027-08-29"),("SGN","SYD","2027-08-31"),("SYD","SGN","2027-08-29")]
n = 3
for a, b, d in SEARCHES:
    for stops in (0, None):
        y, m, dd = d.split("-")
        args = {"flyFrom": a, "flyTo": b, "departureDate": f"{dd}/{m}/{y}", "adults": 1,
                "cabinClass": "M", "currency": "AUD", "sort": "price"}
        if stops is not None: args["max_sector_stopovers"] = stops
        log(f"\n=== {a}->{b} {d} {'NONSTOP' if stops == 0 else 'ANY STOPS'} (UTC {datetime.datetime.utcnow().strftime('%H:%M:%S')})")
        try:
            n += 1
            r, _ = rpc({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                        "params": {"name": "search-flight", "arguments": args}}, sid)
            txt = (r.get("result", {}).get("content") or [{}])[0].get("text", "")
            if not txt or r.get("result", {}).get("isError"):
                log("ERROR/EMPTY: " + (txt or json.dumps(r))[:400]); continue
            its = json.loads(txt).get("itineraries", [])
            log(f"{len(its)} itineraries")
            for it in its[:25]:
                o = it.get("outbound") or {}
                segs = o.get("segments", [])
                car = "/".join(dict.fromkeys(s.get("carrierName", "?") for s in segs))
                fn = ",".join(str(s.get("flightNumber") or s.get("carrierCode", "")) for s in segs)
                log(f"  A${it.get('price')}  {car}  {fn}  stops={o.get('stops')}  {o.get('departureTime')}")
            vj = [i for i in its if any("viet" in (s.get("carrierName","")).lower() for s in (i.get("outbound") or {}).get("segments", []))]
            log(f"Vietjet itineraries: {len(vj)}" + (f", cheapest A${min(i['price'] for i in vj)}" if vj else ""))
            if its: log("RAW first itinerary: " + json.dumps(its[0])[:700])
        except Exception as e:
            log("ERROR: %r" % e)
        time.sleep(15)

import os
os.makedirs("data", exist_ok=True)
open("data/kiwi_test.txt", "w").write("\n".join(out))
