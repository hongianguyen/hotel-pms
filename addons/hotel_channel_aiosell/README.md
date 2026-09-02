# Hotel Channel Manager — Aiosell

Connects this PMS to [Aiosell](https://aiosell.com), a channel manager that
redistributes to Booking.com, Agoda, Expedia, Airbnb, Goibibo/MakeMyTrip and
others.

**Why Aiosell and not the OTAs directly.** Booking.com's Connectivity API is
open to connectivity *partners* — software companies — not to individual
properties, and Expedia and Airbnb are the same. A channel manager is the
supported route for a single hotel, and its PMS-connectivity API is open to
whoever runs the PMS. That is the whole reason this module can exist where the
direct-OTA work could not.

## The upstream contract

Aiosell publishes its API only through a JavaScript app at
`https://apidocs.aiosell.com`, whose bundle URL is content-hashed and changes
on every docs deploy; the public KB pages behind it are thinner and also
JS-rendered. So the contract is written down here. Verified against the live
API on 2 September 2026.

**Base URL:** `https://live.aiosell.com/api/v2/cm`
**Auth:** HTTP Basic on every call — `Authorization: Basic base64(user:pass)`.
**Rate limit:** no more than 30 updates per second.

`{pms}` in a path is the *partner slug* Aiosell assigns to the PMS (e.g.
`sample-pms`). `hotelCode` in a body is the *property* identifier. They are
different values and both are required.

> **The status code lies.** A bad credential comes back as **HTTP 400** with
> `{"success": false, "message": "Authentication Required!"}` — not 401. Never
> treat 2xx as success or 4xx as auth-failure; read `success` in the body.
> `_call()` in `models/aiosell_config.py` does exactly this.

### PMS → Aiosell

| Purpose | Method | Path |
| --- | --- | --- |
| Property / mapping details | GET | `/property_details/{hotelCode}?partnerId={pms}` |
| Inventory push | POST | `/update/{pms}` |
| Inventory restrictions push | POST | `/update/{pms}` |
| Rate push | POST | `/update-rates/{pms}` |
| Rate restrictions push | POST | `/update-rates/{pms}` |
| Mark no-show | POST | `/marknoshow/{pms}` |
| Fetch inventory / rates / reservations | POST | `/data/{pms}` |
| Channel multiplier | POST | `/channel_multiplier/{pms}` |

Two gotchas in that table: `/update/{pms}` serves **both** inventory and
inventory-restrictions, distinguished only by the body shape, and the three
Fetch calls share `/data/{pms}`, distinguished by a `type` field whose
reservation value is the **singular** `"reservation"`.

Call `property_details` first — the `hotel_id`, `room_id` and `rateplan_id` it
returns are the exact codes every other call expects. The "Import Mapping from
Aiosell" button does this and pre-fills the mapping tables.

```jsonc
// POST /update/{pms} — inventory
{"hotelCode": "sandbox-pms",
 "updates": [{"startDate": "2023-01-24", "endDate": "2023-01-26",
              "rooms": [{"roomCode": "executive", "available": 3}]}]}

// POST /update/{pms} — restrictions (same URL, different body)
{"hotelCode": "sandbox-pms",
 "toChannels": ["agoda", "booking.com"],          // required, non-empty
 "updates": [{"startDate": "2023-01-24", "endDate": "2023-01-26",
              "rooms": [{"roomCode": "SUITE", "restrictions": {
                  "stopSell": false, "minimumStay": 1,
                  "closeOnArrival": false, "closeOnDeparture": false,
                  "maximumStay": null, "minimumStayArrival": null,
                  "maximumStayArrival": null, "exactStayArrival": null,
                  "minimumAdvanceReservation": null,
                  "maximumAdvanceReservation": null}}]}]}

// POST /update-rates/{pms}
{"hotelCode": "sandbox-pms",
 "updates": [{"startDate": "2023-02-22", "endDate": "2023-02-24",
              "rates": [{"roomCode": "executive", "rateplanCode": "executive-s-ep",
                         "rate": 1749.0}]}]}

// POST /marknoshow/{pms}   — channel is "booking.com" or "gommt" only
{"hotelCode": "SANDBOX-OTA", "bookingId": "111222350", "channel": "gommt"}

// POST /data/{pms}
{"type": "inventory" | "rates" | "reservation",
 "hotelCode": "sandbox-pms", "startDate": "2025-07-20", "endDate": "2025-07-22"}
```

Dates are `YYYY-MM-DD` and **inclusive at both ends**. Inventory and rates are
upserts: a new value for a range overwrites the old one. Rates are plain
numbers **in the property's own currency** — there is no currency field in the
payload, which is why `action_import_mapping` refuses to proceed when Aiosell's
property currency differs from the company's.

### Aiosell → PMS

Aiosell POSTs reservations to an endpoint *we* host and register with them.
This module exposes `POST /aiosell/reservation`, guarded by HTTP Basic using
the webhook credentials on the connection record.

`book`, `modify` and `cancel` all arrive at that one URL, told apart by
`action`. `book` and `modify` carry the full payload; `cancel` carries only
`action`, `hotelCode`, `channel` and `bookingId`. The expected reply is a bare

```json
{"success": true, "message": "Reservation Updated Successfully"}
```

— which is why the route is `type='http'` and not `type='jsonrpc'`: a jsonrpc
route would wrap that in `{"jsonrpc": "2.0", "result": ...}` and every delivery
would look malformed to Aiosell.

Full booking payload:

```jsonc
{"action": "book", "hotelCode": "sandbox-pms", "channel": "Goibibo",
 "bookingId": "111222333", "cmBookingId": "AAABBBCCC",
 "bookedOn": "2022-12-08 15:25:35",
 "checkin": "2022-12-10", "checkout": "2022-12-12",
 "segment": "OTA", "specialRequests": "Airport Taxi Required",
 "pah": false,                                  // true = collect at hotel
 "amount": {"amountAfterTax": 1204.0, "amountBeforeTax": 1075.0, "tax": 129.0,
            "currency": "INR", "commission": 215.0, "tcs": 5.38, "tds": 1.08},
 "guest": {"firstName": "...", "lastName": "...", "email": "...", "phone": "...",
           "address": {"line1": "...", "city": "...", "state": "...",
                       "country": "...", "zipCode": "..."}},
 "rooms": [{"roomCode": "executive", "rateplanCode": "executive-s-ep",
            "guestName": "...", "occupancy": {"adults": 1, "children": 0},
            "prices": [{"date": "2022-12-10", "sellRate": 537.5}]}]}
```

**Every `guest.*` field is optional.** OTAs mask or withhold e-mail, phone and
address routinely, and a booking must never be rejected for their absence.
`specialRequests` is free text whose meaning varies per channel — store it, do
not parse it.

## Decisions this module makes

* **Draft bookings hold inventory** (`draft_holds_inventory`, on by default).
  New bookings in this PMS start as draft, so counting only confirmed ones
  would offer a room the front desk has already promised on the phone.
* **Run-of-House types are never published.** ROH is virtual and overlaps the
  physical types; sending both double-counts the same beds. An unassigned ROH
  booking is instead subtracted from whichever physical type has the most left
  that night.
* **A closed rate is absent, never zero.** `get_rate_for_date` returns `False`
  for stop-sell, out-of-season and excluded weekdays. Pushing that as `0.0`
  would list the room free on every OTA.
* **Consecutive identical nights collapse into one block** before pushing, so a
  year's horizon is a handful of updates rather than 365.
* **Availability is computed in memory** from one room query and one
  reservation query, not by calling `get_available_rooms` per day — that shape
  is thousands of queries per push against a table with ~19,000 reservations.
* **The OTA's price wins.** `ota_nightly_rate` overrides the PMS price list
  while a booking is draft or confirmed, because the channel already sold the
  room at an agreed rate and the folio has to charge what the guest owes. It is
  the per-night average of the channel's `prices[]`, so the stay total matches
  the OTA statement even when nights are priced differently.
* **A prepaid stay is billed to the channel, not the guest.** When `pah` is
  false the channel already took the money, so the guest settles nothing on
  departure. The booking is given the channel as an agency on credit terms,
  which puts the room charge on a company folio; the check-out balance guard
  reads that as a city-ledger balance and lets the guest leave, while the debt
  stays visible until the channel's remittance is reconciled. Without this
  every prepaid OTA guest is a departure reception cannot complete — and only
  a Hotel Administrator can override the guard. Turn it off with *Bill Prepaid
  Bookings to the Channel* if you would rather post the money yourself.
* **A push that sends nothing is recorded, not shrugged off.** If rates are
  switched on but no rate plan mapping resolves, availability would keep
  flowing while the OTAs sold at the last price they heard. That case writes a
  `refused` row in the Sync Log.
* **Retry contract.** Unexpected failures answer HTTP 500 so Aiosell retries.
  Changes we *refuse* — a modify or cancel for a guest already checked in —
  answer 200 with `success: true`, log the line as `refused`, and raise an
  activity for reception. Retrying could never make those succeed, and
  swallowing them silently would lose them.
* **Crons ship inactive.** Installing this module must not start pushing a live
  property's inventory to the OTAs.

## Known limitations

* A multi-room OTA booking becomes one `hotel.reservation` per room sharing an
  `aiosell_booking_id`, not a `hotel.booking.group`. Simpler and less to go
  wrong; group them by hand if the front desk wants a master folio.
* Aiosell prices per occupancy (`executive-s-ep` vs `executive-d-ep`) but
  `hotel.rate.plan` has no occupancy dimension, so every code mapped to a room
  currently receives that room's single nightly rate.
* Rate *restrictions* (`/update-rates/{pms}` with a `restrictions` body) and
  the channel multiplier are documented above but not wired to the UI.
* No outbound push on reservation write: the cron batches every 15 minutes.
  Availability is therefore up to 15 minutes stale on the OTAs.
* Aiosell's `amount.commission`, `tcs` and `tds` are recorded in the booking
  notes but not posted to the ledger.

## Setting it up

1. Get from Aiosell: hotel code, partner id (PMS slug), and the API username
   and password. Give them the webhook URL shown on the form plus a webhook
   username and password you choose.
2. Hotel → Channel Manager → Aiosell Connection, fill those in.
3. **Test Connection**, then **Import Mapping from Aiosell**.
4. Pair anything the import left blank in the two mapping tabs. Unmapped codes
   are never synced. The importer matches by name, and Aiosell's stock plan
   names ("Room Only", "Breakfast") rarely match a property's own — expect the
   rate tab to need pairing by hand even when the room tab looks complete.
   Check too that no staff, owner or house room sits inside a mapped room
   type, or it will be offered for sale.
5. **Push Availability & Rates Now**, and check the Sync Log.
6. Only then enable the cron *Aiosell: push availability and rates*
   (Settings → Technical → Scheduled Actions), and the log cleanup alongside it.

The webhook must be reachable from the internet for inbound bookings to land.
Put it behind a dedicated nginx location that rate-limits and, once Aiosell's
egress addresses are known, allowlists them.
