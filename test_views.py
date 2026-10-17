import asyncio
import urllib.parse

import primp
from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
from fast_flights.core import parse_response
from playwright.async_api import async_playwright

DEPART, RETURN = "2027-08-09", "2027-08-21"
FILT = create_filter(
    flight_data=[FlightData(date=DEPART, from_airport="SYD", to_airport="SGN"),
                 FlightData(date=RETURN, from_airport="SGN", to_airport="SYD")],
    trip="round-trip", seat="economy", passengers=Passengers(adults=1))
TFS_URL = ("https://www.google.com/travel/flights?tfs=" + urllib.parse.quote(FILT.as_b64().decode())
           + "&hl=en&tfu=EgQIABABIgA&curr=AUD")
Q_URL = ("https://www.google.com/travel/flights?hl=en&curr=AUD&q="
         + urllib.parse.quote(f"Flights from SYD to SGN on {DEPART} through {RETURN}"))


class Page:
    def __init__(self, text):
        self.text = text


def report(label, flights):
    print(f"\n===== {label} =====", flush=True)
    print(f"{len(flights)} flights in total. Nonstop flights:", flush=True)
    for f in flights:
        if f.stops == 0:
            print(f"   {f.name} | {f.price}", flush=True)
    cheapest = sorted(flights, key=lambda f: int("".join(c for c in f.price if c.isdigit()) or 10**9))[:3]
    print("   cheapest overall:", [f"{f.name} {f.price}" for f in cheapest], flush=True)


def attempt(label, fn):
    try:
        report(label, fn())
    except Exception as e:
        print(f"\n===== {label} =====\nFAILED: {e!r}", flush=True)


async def browser_fetch(url, australian):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        opts = {}
        if australian:
            opts = dict(locale="en-AU", timezone_id="Australia/Sydney",
                        geolocation={"latitude": -33.87, "longitude": 151.21}, permissions=["geolocation"],
                        extra_http_headers={"Accept-Language": "en-AU,en;q=0.9"})
        ctx = await browser.new_context(**opts)
        page = await ctx.new_page()
        await page.goto(url)
        if page.url.startswith("https://consent.google.com"):
            await page.click('text="Accept all"')
        await page.locator(".eQ35Ce").wait_for()
        await page.wait_for_timeout(4000)
        body = await page.evaluate("() => document.querySelector('[role=\"main\"]').innerHTML")
        await browser.close()
    return body


def plain_q():
    res = primp.Client(impersonate="chrome_126", verify=False).get(Q_URL)
    return parse_response(Page(res.text)).flights


attempt("A: plain request, search-by-parameters (tracker today)",
        lambda: get_flights_from_filter(FILT, currency="AUD", mode="common").flights)
attempt("B: real browser, search-by-parameters",
        lambda: get_flights_from_filter(FILT, currency="AUD", mode="local").flights)
attempt("C: real browser set to Australia, search-by-parameters",
        lambda: parse_response(Page(asyncio.run(browser_fetch(TFS_URL, True)))).flights)
attempt("D: real browser set to Australia, same kind of link as the dashboard",
        lambda: parse_response(Page(asyncio.run(browser_fetch(Q_URL, True)))).flights)
attempt("E: plain request, same kind of link as the dashboard", plain_q)
