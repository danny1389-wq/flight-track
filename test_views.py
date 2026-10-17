from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter


def show(label, mode):
    print(f"\n===== {label} =====", flush=True)
    try:
        filt = create_filter(
            flight_data=[FlightData(date="2027-08-09", from_airport="SYD", to_airport="SGN"),
                         FlightData(date="2027-08-21", from_airport="SGN", to_airport="SYD")],
            trip="round-trip", seat="economy", passengers=Passengers(adults=1))
        res = get_flights_from_filter(filt, currency="AUD", mode=mode)
        for f in res.flights[:25]:
            print(f"{f.name} | stops={f.stops} | {f.price}", flush=True)
        print(f"({len(res.flights)} flights in total)", flush=True)
    except Exception as e:
        print("FAILED:", repr(e), flush=True)


show("METHOD A: plain request (what the tracker uses now)", "common")
show("METHOD B: real browser on this PC", "local")
