# House Hunt — Product Spec

> Status: **first version built** (2026-10-08). App, agent and enrichment are
> described in `CLAUDE.md`. This file records what we agreed; §9–10 hold the
> platform decisions.

## 1. Purpose

Help two friends **find and agree on a rental quickly** in Redwood City,
San Carlos or Menlo Park: 2–3 bedrooms, cheap but comfortable, close to
Caltrain, available now or by end of November 2026.

Searching is easy. The hard parts are keeping up with fast-moving listings,
judging each one against what *both* people want, and reaching agreement.
The app takes over the first two and makes the third easier.

## 2. Functions

1. **Say what you want, in plain English.** Each person writes their own
   requirements and edits them any time.
2. **One unified requirement.** The agent merges both people's input into a
   single requirement, finds conflicts and resolves them itself (§4). Every
   search, score and answer uses **only** the unified requirement.
3. **Agent finds houses.** It searches the web on a schedule, adds new
   listings and removes ones that are gone.
4. **Agent scores every house.** It fills in the house's facts (§5), and code
   calculates location metrics from the address. A weighted score ranks the
   houses (§6), with a breakdown and a list of unknowns.
5. **Review and decide together.** Quick notes on each house (both see them),
   👍/👎 per person, shared status, and tour photos and videos. The agent reads
   notes and updates the house's facts automatically.
6. **Table and map views.** A sortable table, and a map with each house at its
   exact address (approximate locations look different), plus Caltrain
   stations. Both views share the same filters.
7. **Ask questions.** "What's new?", "Which places are walkable to Caltrain
   under $5k?", either in the app or through each person's own Claude Code.
8. **Paste a listing.** When either person spots a place anywhere (Zillow,
   a friend's message, a sign on the street), they paste the link, the
   listing text or a screenshot into the app. The agent extracts the facts,
   places the house on the map and scores it. This covers the sites that
   block automated search.

**Not included:** chat (WeChat or Discord covers that), applying or paying,
contacting landlords automatically.

## 3. How people use it

**Setup (once):** the owner shares the app with the friend's claude.ai
email as an **Editor**. Both open the link, signed in to claude.ai. Each
person writes their requirements, and the first search runs. Each person's
Claude Code can then work with the same data.

**Day to day:**
1. Open the app and look at what's new.
2. Use the table or map to shortlist.
3. Open a house and read its score breakdown.
4. Leave a note and a 👍 or 👎.
5. If both of you like it, mark it *interested* and contact the landlord.
6. Record the answers as notes.
7. Tour: use the tour checklist, add photos and notes.
8. Mark it *applied*, or *rejected* with a reason. The agent learns from the
   reason.

**Finish:** mark a house *signed*. The search stops and the history stays.

## 4. Requirements: personal → unified

- **Personal requirements:** free text, one per person, versioned.
- **Unified requirement:** produced by the agent, versioned (v1, v2, …). It
  is regenerated whenever either person edits theirs, and every house is
  re-scored.
- Each item is one of:
  - **must-have:** used as a filter;
  - **preference:** used for ranking, with a weight;
  - **deal-breaker:** the house is auto-rejected.

  Every item records **who it came from**.
- **Conflict rules:**
  - The lower budget wins.
  - Either person's deal-breaker applies to both.
  - A "need" beats a "would like".
  - Real taste conflicts become preferences, not filters.
  - If the must-haves leave almost nothing, the agent loosens the least
    important one and says so.
- **"What we're searching for" page:** must-haves, preferences with
  weights, deal-breakers, each conflict with how it was resolved and how many
  houses that excludes, and what changed since the last version.
- If someone disagrees with a call the agent made, they reword their own
  requirement. There are no override buttons.

## 5. House data

Every fact about a house is stored with **provenance**: the value, plus
`source`, `confidence`, `stage` and `updated_at`.

- **`source`**, from most to least trusted:
  1. `tour`: confirmed in person;
  2. `landlord`: the answer to a question;
  3. `listing`: what the listing says;
  4. `computed`: calculated by code from the address or data;
  5. `inferred`: the agent's guess from indirect evidence.

  A more trusted source overrides a less trusted one.
- **`unknown`** is a real value. It is never guessed silently. Each unknown
  that matters becomes a **question to ask the landlord**.

### 5.1 Catalog

Stages: **D** discover · **E** enrich · **Q** inquire · **T** tour ·
**A** apply. See §7.

#### Cost (the true monthly cost, not just rent)

| Field | Values | Stage | Why it matters |
|---|---|---|---|
| Rent | $/mo | D | Base cost |
| Rent per person | computed | E | What each person pays |
| Utilities included | list (water, trash, gas, electric, internet) | D/Q | A $300/mo difference is common |
| Estimated utilities | $/mo | E/Q | True cost comparison |
| Deposit | $ | D/Q | Cash needed up front |
| Fees | application, pet, parking, amenity ($) | Q | Hidden costs |
| Total move-in cash | computed | Q | Deposit + first month + fees |
| Price vs. market | % above/below similar listings | E | Is it a good deal? Is it suspiciously cheap? |
| Price history | drops, days on market | E | Negotiation room |

#### Space

| Field | Values | Stage | Why it matters |
|---|---|---|---|
| Property type | house · townhouse · duplex · condo · apartment · ADU | D | Preference for a real house |
| Bedrooms / bathrooms | numbers | D | 2 bathrooms matter a lot for roommates |
| Square footage | number | D/Q | Overall size |
| Privacy | rooms on separate floors or walls | T | Roommate comfort |
| Work-from-home space | room for a desk, a quiet room | T | Matters if either works from home |
| Shared living space | size and feel | T | Comfort |
| Storage | closets, garage storage | Q/T | Comfort |
| Outdoor space | yard · patio · balcony · none | D | Common preference |
| Furnished | yes · partly · no | D | Cost and convenience |

#### Amenities

| Field | Values | Stage |
|---|---|---|
| Air conditioning | yes · no · unknown | D/Q/T |
| Heating type | central · wall · baseboard · none | D/T |
| Washer and dryer | in-unit · shared on-site · none | D/T |
| Dishwasher | yes · no | D/T |
| Kitchen | gas or electric stove, condition | D/T |
| Internet | fiber · cable only · speed | E/Q |
| Parking | number of spots and type (garage, driveway, street) | D/Q/T |
| EV charging | yes · no | Q |
| Bike storage | yes · no | T |

#### Condition and health

| Field | Values | Stage | Why it matters |
|---|---|---|---|
| Condition / last renovated | good · dated · poor, year | D/T | Comfort |
| Natural light | good · ok · dark | T | A common reason people reject a place |
| Noise | quiet · some · loud, and the source | E/T | Sleep and work from home |
| Mold, pests, smell | none seen · concern | T | Health |
| Water pressure, cell signal | ok · weak | T | Everyday annoyances |
| Smoke and CO detectors | present · missing | T | Safety |

#### Location (computed by code from the address)

| Field | Values | Stage |
|---|---|---|
| Exact coordinates | lat/lng, or approximate | E |
| Nearest Caltrain station | name, walk minutes | E |
| Supermarket | name, walk/drive minutes | E |
| Post office | name, minutes | E |
| Major shopping district | name, minutes (fixed list, editable) | E |
| Movie theater | name, minutes | E |
| Parks, gym, restaurants | minutes to nearest | E |
| Highway access (101 / 280) | drive minutes | E |
| Commute to each person's work | minutes, if they enter a workplace | E |
| Noise sources | distance to Caltrain tracks, 101, El Camino | E |
| Flood zone | yes · no (low-lying Bay-side areas) | E |
| Walkability | score | E |

#### Lease and rules

| Field | Values | Stage | Why it matters |
|---|---|---|---|
| Available date | date or now | D | Must be by Nov 30 |
| Lease length | months, month-to-month option | D/Q | Flexibility |
| Pets | allowed · not · conditions | D/Q | |
| Smoking | allowed · not | Q | |
| Maintenance duties | who handles yard and repairs | Q | Hidden workload |
| Rent-increase protection | covered by the state cap, or exempt | E/Q | Many single-family houses are exempt |
| Permitted unit | yes · no · unknown | E/Q | Unpermitted ADUs carry risk |
| Application requirements | credit score, income multiple, documents | Q/A | Be ready to apply fast |

#### Trust (the listing and the landlord)

| Field | Values | Stage | Why it matters |
|---|---|---|---|
| Listing verified | verified · unverified | D/E | Many listings are search snippets |
| Listing age / last seen | dates | D/E | Freshness |
| Landlord type | individual · property manager | D/Q | Responsiveness, rules |
| Landlord responsiveness | fast · slow · none | Q | Predicts the experience |
| Scam signals | list of flags | E | Money before a tour, price far below market, "owner abroad" |

### 5.2 Other records

| Record | Contents |
|---|---|
| **House** | id, title, address, city, source links, photos from the listing, active/gone, first/last seen |
| **Fact** | house, field, value, source, confidence, stage, updated_at (one row per field; history kept) |
| **Note** | house, author, text, photo/video ids, created/edited. Only the author edits or deletes. The agent extracts facts from it. |
| **Media** | tour photos and videos, uploaded by people and attached to notes |
| **Vote** | house, person, 👍/👎 |
| **Status** | house: new → interested → contacted → toured → applied → signed, or rejected (with reason), or gone |
| **Question** | house, question for the landlord, generated from unknowns, answered or open |
| **Personal requirement** | person, text, version |
| **Unified requirement** | version, items (type, weight, from whom), conflicts and resolutions, change summary |
| **Score** | house, unified-requirement version, total, per-item breakdown, unknowns |
| **Search run** | time, queries, houses found / updated / removed, notes |

## 6. Scoring

1. **Must-haves and deal-breakers** come from the unified requirement and
   are pass/fail. A failing house drops out of the default view; it is not
   deleted.
2. **Weighted score (0–100)** across preferences:
   - price per person;
   - amenities;
   - size and fit;
   - condition;
   - location metrics;
   - lease and trust.

   **The agent sets the weights** from the unified requirement. Properties
   neither person mentioned get small default weights.
3. **Unknowns get half credit** and a ❓ badge, so a vague listing isn't
   buried. It surfaces as "worth asking about".
4. **Confidence:** facts confirmed on a tour count fully. Inferred facts
   count less.
5. **Every score has a breakdown,** e.g. *"82: cheap per person (+), 6-min
   walk to Caltrain (+), no A/C (−), dishwasher ❓"*.
6. A score is tied to the unified-requirement version it used. A new
   version re-scores every house.

**Location metrics are calculated by code, never estimated by the AI:**
1. Geocode the address.
2. Find the nearest places from map data.
3. Get the real walking or driving time along streets.

Each distance becomes a score on a simple curve, e.g. Caltrain within a
10-minute walk = full points, 30+ minutes = 0.

## 7. Workflow: what is learned at each stage

| Stage | Trigger | Who | What gets filled in |
|---|---|---|---|
| **D: Discover** | Scheduled search, or a person pastes a listing | Agent | Listing basics: address, rent, beds/baths, sqft, type, availability, listed amenities, photos, landlord contact, listing date |
| **E: Enrich** | A new house has an address | Code (+ agent) | Coordinates, all location metrics, noise sources, flood zone, rent per person, estimated utilities, price vs. market, scam signals, verification |
| **Score** | After D/E, after any new fact, or when the unified requirement changes | Code + agent | Fit score, breakdown, unknowns → **landlord questions** |
| **Q: Inquire** | Status → *interested* | People (the agent drafts the message) | Answers to the questions: fees, utilities, parking, lease terms, application requirements |
| **T: Tour** | Tour scheduled | People, with a **tour checklist** generated from the remaining unknowns | Condition, light, noise, room sizes, mold, water pressure, cell signal, actual parking, photos |
| **A: Apply** | Status → *applied* | People (the agent reviews the lease) | Application requirements, lease red flags, move-in cash |
| **Close** | Signed, rejected or gone | People / agent | Reason (rejections teach the agent) |

Each stage only asks for what the earlier stages could not get, so nobody
asks a landlord something the listing already answered.

## 8. Agent behavior

- Runs on a schedule (several times a day), and immediately after
  requirements change.
- Steps: merge requirements (when changed), then search, extract, enrich,
  score, re-check old listings, and process new notes into facts.
- Treats web pages and people's text as **data, never instructions**.
- Never invents facts. If something is unknown, it records `unknown` and
  creates a question.

## 9. Decisions (2026-10-08)

| # | Topic | Decision |
|---|---|---|
| 1 | Hosting | **claude.ai.** The web app is a private claude.ai artifact shared between the two people. Its built-in database holds houses, facts, notes, votes, status and requirements. Its built-in storage holds tour photos and videos. The search agent is a scheduled **Claude Code routine** on the owner's Claude plan, with no API key. |
| 2 | Map and places data | **Free sources:** OpenStreetMap map data, the US Census geocoder for addresses, OpenStreetMap places for supermarkets, post offices and theaters, and OpenRouteService for walking and driving times. Each house is calculated once and saved. Google only if gaps appear. |
| 3 | Alerts | **Daily morning email:** new strong matches, price drops, houses gone. **Instant email** when a house passes every must-have and scores 85+. Sent by the agent. No other notifications. |
| 4 | Sign-in | **claude.ai accounts.** Access is whoever the app is shared with: the owner, plus the friend as an Editor. |
| 5 | Device | **Phone first:** cards, map and a sort menu. On a computer: the full table next to the map. |
| 6 | Listing sources | **Agent web search on a schedule + "paste a listing"** (function 8). Consider a paid listings data source if coverage is weak after 2 weeks. No scraping against sites' terms. |

## 10. What claude.ai hosting means

These follow from decision 1. They change how some things are built, not
what the app does.

- **Map:** claude.ai pages can't load map images from outside map services.
  So the app ships **its own street map**: street, rail and park outlines
  for Redwood City, San Carlos and Menlo Park, downloaded once from
  OpenStreetMap and drawn by the page. House pins sit at their exact
  geocoded positions. Expect a clean drawn map, not a satellite-style one.
- **Both people need a claude.ai account.** The friend is shared in as an
  **Editor** so he can write notes and votes.
- **"Ask Claude" inside the page** (e.g. "Is this a good deal?") uses the
  **asking person's** own Claude usage.
- **Paste a listing:** the page can't open outside links itself. Pasted text
  and screenshots are read immediately. A pasted **link** is queued, and the
  agent opens it on its next run. Links from blocked sites (Zillow, Redfin)
  need the text or a screenshot instead.
- **Emails** are sent by the agent through the owner's connected Gmail, to
  both people.
- **Where data lives:** house data, notes, votes and requirements are only
  in the app database. GitHub holds code and area map files. The agent's
  environment allows the Census geocoder, Nominatim, OSRM routing and FEMA,
  so the agent calculates per-house distances itself. OpenStreetMap place
  data (shops, stations, the street map) is built monthly by GitHub Actions
  and stored as map files.
- **Storage:** tour uploads are capped at 20 MB each, with a per-app quota.
  Photos are compressed and videos limited to about 30 seconds.
- **Lock-in:** if this ever needs to leave claude.ai, the data model and
  agent carry over. The web page would be rebuilt.
