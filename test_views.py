import asyncio
import base64
import urllib.parse

from fast_flights.core import parse_response
from playwright.async_api import async_playwright

DEPART, RETURN = "2027-08-09", "2027-08-21"
TFU = "EgoIABAAGAAgAigB"   # copied from the address bar of a normal Chrome search


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field(num, value):
    if isinstance(value, int):
        return varint(num << 3) + varint(value)
    return varint((num << 3) | 2) + varint(len(value)) + value


def airport(code):
    return field(1, 1) + field(2, code.encode())


def leg(date, a, b):
    return field(3, field(2, date.encode()) + field(13, airport(a)) + field(14, airport(b)))


def browser_style_tfs(depart, ret):
    raw = (field(1, 28) + field(2, 2) + leg(depart, "SYD", "SGN") + leg(ret, "SGN", "SYD")
           + field(8, 1) + field(9, 1) + field(14, 1)
           + field(16, bytes.fromhex("08ffffffffffffffffff01")) + field(19, 1))
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


EXPECTED = ("CBwQAhoeEgoyMDI3LTA4LTA5agcIARIDU1lEcgcIARIDU0dOGh4SCjIwMjctMDgtMjFqBwgBEgNTR05yBwgBEgNTWURAAUgBcAGC"
            "AQsI____________AZgBAQ")
URL = ("https://www.google.com/travel/flights/search?tfs=" + browser_style_tfs(DEPART, RETURN)
       + "&tfu=" + TFU + "&hl=en&curr=AUD")


class Page:
    def __init__(self, text):
        self.text = text


def report(flights):
    print(f"{len(flights)} flights in total. Nonstop flights:", flush=True)
    for f in flights:
        if f.stops == 0:
            print(f"   {f.name} | {f.price}", flush=True)
    cheapest = sorted(flights, key=lambda f: int("".join(c for c in f.price if c.isdigit()) or 10**9))[:3]
    print("   cheapest overall:", [f"{f.name} {f.price}" for f in cheapest], flush=True)


def attempt(label, fn):
    print(f"\n===== {label} =====", flush=True)
    try:
        report(fn())
    except Exception as e:
        print(f"FAILED: {e!r}", flush=True)


async def browser_fetch(url, real_chrome):
    async with async_playwright() as p:
        if real_chrome:
            browser = await p.chromium.launch(channel="chrome", headless=False)
        else:
            browser = await p.chromium.launch()
        ctx = await browser.new_context(locale="en-AU", timezone_id="Australia/Sydney")
        page = await ctx.new_page()
        await page.goto(url)
        if page.url.startswith("https://consent.google.com"):
            await page.click('text="Accept all"')
        await page.locator(".eQ35Ce").wait_for()
        await page.wait_for_timeout(4000)
        grab = "() => document.querySelector('[role=\"main\"]').innerHTML"
        before = await page.evaluate(grab)
        print(f"   'Separate tickets' appears {before.count('Separate tickets')} times before clicking", flush=True)
        try:
            await page.get_by_text("Cheapest", exact=False).first.click()
            await page.wait_for_timeout(5000)
        except Exception as e:
            print("   could not click Cheapest:", repr(e), flush=True)
        body = await page.evaluate(grab)
        print(f"   'Separate tickets' appears {body.count('Separate tickets')} times after clicking", flush=True)
        text = await page.evaluate("() => document.querySelector('[role=\"main\"]').innerText")
        i = text.find("Vietjet")
        print("   page text around Vietjet:",
              repr(text[max(0, i - 120): i + 260]) if i >= 0 else "Vietjet is not on the page", flush=True)
        await browser.close()
    return body


print("Rebuilt address matches the one from your Chrome:", browser_style_tfs(DEPART, RETURN) == EXPECTED, flush=True)
attempt("H: browser (Chromium), click the Cheapest tab, then read",
        lambda: parse_response(Page(asyncio.run(browser_fetch(URL, False)))).flights)
attempt("I: your installed Chrome (a window will flash up), click the Cheapest tab, then read",
        lambda: parse_response(Page(asyncio.run(browser_fetch(URL, True)))).flights)
