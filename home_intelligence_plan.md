# Home Intelligence Expansion Plan
### 1950 Eucalyptus Ave · San Carlos, CA · March 2026

**What I confirmed tonight from public records:** 2,770 sq ft · 5BR/3.5BA · 5,000 sq ft lot
(100×50 ft) · Lower San Carlos, Howard Park subdivision · APN 050313100. Your home is
~70% larger than the California average, which partly explains the energy bills — at
6.2 kWh/sq ft/yr you're running about double the state average per square foot, suggesting
significant AC load, possibly an EV, or both.

What I already know about your home is actually pretty good: a full year of energy data,
real-time thermostat readings, live project and vendor tracking, and tonight I added
weather correlation. But there are meaningful gaps. Here's what's missing, how to get it,
and what I could do with it.

---

## 1. Your PG&E Rate Plan — Potentially the Single Highest-Value Thing

**What's missing:** I don't know which rate plan you're actually on. PG&E has several:
E-1 (tiered, no time-of-use), E-TOU-C (time-of-use with peak 4–9pm), E-TOU-D, and others.
At your usage level (~17,000 kWh/yr), the rate plan choice can swing your annual bill by
$800–1,500.

**How to get it:** It's on your PG&E bill's first page. Takes 30 seconds to look up.
Alternatively, if you connect PG&E Share My Data (already planned in your dashboard),
it would be included automatically.

**What I'd do with it:**
- Simulate what your actual bill would have been on each alternative plan
- Recommend whether switching would save money given your usage pattern
- If you add a battery, determine the optimal charge/discharge schedule for your specific plan
- Flag if PG&E changes rates (they do, usually January)

Your $0.42/kWh average suggests E-1 tiered or a high-tier TOU plan. A Powerwall's
time-of-use arbitrage value depends entirely on this — could be worth $200/yr or $600/yr
depending on plan.

---

## 2. Water Usage — The Missing Utility

**What's missing:** You have Cal Water manual entry set up but no data has been logged yet.
Water is the one utility with zero visibility right now.

**How to get it:** Cal Water has a web portal (calwater.com) where you can view monthly usage.
It doesn't have a developer API, but bills arrive monthly and typically show:
- Gallons used
- Tier breakdown (Cal Water has tiered pricing)
- Comparison to prior year

**What I'd do with it:**
- Add a water section to the dashboard alongside electricity and gas
- Flag unusually high months (often the first sign of a leak or irrigation system issue)
- Track seasonal patterns (summer irrigation adds significantly in San Carlos)
- Calculate your full utility cost picture: electricity + gas + water = true home operating cost
- Over time, build a leak detection heuristic: if winter water usage spikes vs prior December,
  something changed

One Cal Water bill photo sent to me monthly would be enough to build this out.

---

## 3. Your Roof — You Actually Know a Lot, But Not Enough

**What's missing:** The roof is CertainTeed Presidential shingle, installed ~2008 per the
Signature Roofing notes. That makes it ~18 years old. Presidential shingles are rated for
50 years but the *installation warranty* is typically 25 years. You don't know:
- The original installation date precisely
- Whether any repairs have been done
- The warranty transfer status (matters if you sell)
- What the actual quotes are going to say about condition

**How to get it:** San Carlos permit records are public. The city uses a permit portal
(likely PermitSonoma or similar). A permit for the original roof installation would show
the exact date. I can search this for you.

**What I'd do with it:**
- Calculate remaining warranty life
- Estimate remaining useful life and add a "roof replacement countdown" to the dashboard
- Cross-reference with your energy data — old roofs with poor insulation correlate with
  higher heating/cooling loads
- Track the quote process properly once amounts come in

---

## 4. Property Data — Home Value, Equity, and ROI Tracking

**What's missing:** Home value, purchase price, current equity, and the financial ROI of
home improvement projects.

**How to get it:**
- Zillow and Redfin both have APIs (Zillow's "Zestimate" API is free for personal use)
- San Mateo County Assessor's Office has public records: assessed value, purchase price,
  lot size, square footage, year built
- Your mortgage balance (you'd need to provide this manually or I could read it from a
  statement)

**What I'd do with it:**
- Add a "Home Equity" tile to the dashboard: current Zestimate, assessed value, estimated equity
- Track Zestimate month-over-month
- Calculate ROI on projects: if the roof replacement costs $25,000, what does Redfin say
  a new roof adds to value for a 1950s San Carlos home? (Generally 60–70% ROI)
- Before/after: show how each completed project affected the estimated value
- "True Cost of Homeownership" view: mortgage + utilities + maintenance + projects / month

---

## 5. Air Quality — Smarter Filter Maintenance

**What's missing:** The Air Filter Maintenance project is in planning with "filter size unknown."
More importantly, you're changing filters on a calendar schedule rather than an air quality
schedule — these aren't the same thing.

**How to get it:**
- AQI data for San Carlos is available free from the EPA's AirNow API (no key needed for
  basic access) or PurpleAir (San Carlos has several community sensors)
- Filter size: one look at the current filter when you're home

**What I'd do with it:**
- Track cumulative AQI exposure since the last filter change
- Send you a filter change alert when air quality has been bad for extended periods
  (wildfire smoke weeks are the key driver — one bad smoke week consumes months of filter life)
- The dashboard already has a maintenance section; this would make the filter reminder
  actually intelligent instead of just calendar-based
- Correlate AQI with thermostat humidity and fan usage to understand HVAC behavior

---

## 6. Solar Insolation — More Precise Than My Estimates

**What's missing:** My solar calculations use 5.2 peak sun hours/day for San Carlos, which
is a reasonable average. But NREL (National Renewable Energy Laboratory) has a free tool
called PVWatts that gives site-specific production estimates accounting for:
- Exact roof tilt and azimuth
- Local shading factors
- Monthly production variation (not just annual average)
- System losses from wiring, inverters, etc.

**How to get it:** NREL's PVWatts API is free, no key required for basic queries.
I'd need to know the garage roof's exact tilt angle (probably 4:12 to 6:12 pitch —
roughly 18–26°) and the precise south azimuth.

**What I'd do with it:**
- Replace my rule-of-thumb estimates with actual month-by-month production projections
- Show which months the solar would cover >100% of usage vs which would have a shortfall
- Include in the solar proposal review: if Sunergy or NRG gives you a production estimate,
  I can compare it against NREL's independent number and flag if they're being optimistic

---

## 7. Appliance Inventory and Warranty Tracking

**What's missing:** There's no record of what appliances you have, how old they are,
or when warranties expire.

**How to get it:** This is the one that requires manual input — a one-time 30-minute
walkthrough of the house with model numbers and approximate purchase dates. Alternatively,
for appliances purchased recently, receipts or credit card records.

**What I'd do with it:**
- Add an "Appliances" section to the dashboard showing age, expected lifespan, and
  remaining estimated life (e.g., "Water heater: 8 years old, avg lifespan 10–12 years")
- Warranty expiration alerts before they lapse
- Replacement planning: if the water heater is 10 years old, now is the time to research
  heat pump water heaters (eligible for 30% ITC through 2032)
- Energy correlation: older refrigerators and HVAC systems draw more power; quantify
  the upgrade ROI

---

## 8. Permit History — What Work Has Been Done

**What's missing:** A complete record of permitted work done on the house since it was built
in 1950. This matters for:
- Verifying the roof age precisely
- Understanding what's been upgraded vs original
- Catching unpermitted work before it becomes a problem at sale

**How to get it:** San Carlos Building Department has public permit records. I can search
the city's permit portal using the property address. This is fully automated.

**What I'd do with it:**
- Build a "Known History" timeline for the house
- Flag any obvious gaps (e.g., if there's no electrical permit since 1960, original wiring
  is a likely issue)
- Feed into project planning: if the 2008 permit shows a roof replacement, we know the
  exact install date and warranty start

---

## What I'd Recommend Prioritizing

In rough order of value vs effort:

**You do in 5 minutes:**
1. Tell me your PG&E rate plan (it's on your bill)
2. Tell me your filter size (it's printed on the current filter)
3. Tell me approximately when major appliances were purchased (HVAC, water heater, fridge)

**I do automatically once set up:**
4. PG&E Share My Data connection (already in your project list) — unlocks hourly data and rate plan
5. NREL PVWatts query for the garage roof once you have roof pitch measurements from a solar installer

**Monthly manual (5 min/month):**
6. Log your Cal Water bill — I'll build a simple form or just accept a photo

**One-time research I can do right now:**
7. Pull San Carlos permit history for 1950 Eucalyptus
8. Pull San Mateo County Assessor data (square footage, year built, assessed value)
9. Pull current Zillow/Redfin estimates and neighborhood comparables

---

*Generated March 27, 2026 · Ready to execute on any of the above when you are.*
