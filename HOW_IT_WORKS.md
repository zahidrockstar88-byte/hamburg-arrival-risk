# How it works: your interview guide

Read this until you can explain each part in your own words. Interviewers care more about
**why you made each choice** than about the code.

---

## The 30-second pitch

> "I built a dashboard that watches container ships heading to Hamburg using live AIS data.
> For each ship it measures the remaining distance along the real sea route, calculates when the ship
> can arrive at its current speed, and compares that with the ETA the crew reported.
> If the gap is large, or the data is old, or the ship is waiting at anchor, it gets a risk flag.
> It also shows chokepoint risks like the Red Sea and Hormuz. It's a risk flag, not a precise
> prediction, and I'm clear about that."

---

## The problem it addresses

- Carrier schedule reliability fell to **29% in August 2026** (Xeneta). Most ships don't arrive on time.
- Importers, forwarders and terminals plan trucks, warehouse staff and berths around the ETA.
- The ETA a ship broadcasts is **typed by the crew** and often not updated. A quick sanity check
  catches ships whose reported ETA no longer fits reality.

## The data: AIS

- Every large ship broadcasts by radio: position, speed, course, destination and ETA.
- **AISStream.io** collects these signals from receivers on land and streams them for free.
- **Limit:** land-based receivers only reach roughly 40–60 nm out to sea, so coverage is strong near Europe
  and weak in the open ocean. That's why the project focuses on the **last part of the journey**, where the
  data is reliable.

## The six steps

**1. Find ships going to Hamburg.**
The destination is free text. The code accepts `HAMBURG` or the UN/LOCODE `DEHAM`, in any spacing.
`NLRTM>DEHAM` means "from Rotterdam to Hamburg", so only the part after `>` counts.
`DEHAM>NLRTM` means the ship is *leaving* Hamburg, so it is ignored.

**2. Measure the distance along the sea route, not a straight line.**
A straight line from Lisbon to Hamburg crosses France. So the code uses waypoints a real ship passes:
Gibraltar → Cape Finisterre → Ushant → Dover Strait → Elbe 1 (river entrance) → Hamburg.
It picks only the waypoints still ahead, based on which sea area the ship is in.

**3. Calculate an ETA.**
- Sea part: distance ÷ the ship's current speed.
- River Elbe (about 75 nm): fixed 10 knots, because of speed limits, pilots and tide.
- Plus 1 hour for pilot boarding and berthing.
- Counted from the time of the ship's **last position**, not from now. Otherwise old data would look fine.

**4. Compare and flag.** The first rule that matches wins. "Arrival" always means **moored at a Hamburg berth**
(see [GLOSSARY.md](GLOSSARY.md) and [ADR 0001](docs/adr/0001-arrival-means-berthing.md)):

| Flag | Rule | Why it matters |
|---|---|---|
| Arrived | Within 15 nm of Hamburg and moored | This is the arrival: moored at a Hamburg berth |
| Arriving | Within 15 nm of Hamburg, still moving | Final approach, nothing left to judge |
| 🟡 Data too old | No position for 24+ hours | Can't trust anything else |
| In another port | Moored at a berth elsewhere (e.g. Rotterdam) | Working cargo before sailing to Hamburg: normal, departure time unknown |
| 🟡 Waiting | At anchor, or under 1 kn at sea | Waiting for berth, tide or pilot: a real delay signal |
| 🟡 No ETA sent | Crew entered no valid ETA | Nothing to compare |
| 🔴 ETA already passed | Reported ETA is in the past, ship still 50+ nm away | Clearly out of date |
| 🔴 Likely late | Calculated ETA is 12+ hours after reported ETA | Reported ETA looks unrealistic |
| 🟢 On track | Everything else | |

The 12-hour limit is a setting you can change in the sidebar.

**5. Add route context.**
If the ship was seen off West Africa, it probably came around the Cape of Good Hope instead of through Suez
(roughly 10–14 extra days from Asia). If it was seen in the Mediterranean, it came via Suez or a Med port.
Chokepoint notes (Red Sea, Hormuz, port congestion) come from a file updated by hand each week.

**6. Guess which ships are container ships, and which shipping line runs them.**
AIS only says "cargo ship" (types 70–79). It never says what is on board. So the code makes an educated guess:
- **By name:** most big container ships carry their line's name: `MSC SINDY`, `MAERSK SEOUL`, `CMA CGM GEMINI`,
  `EVER GREET`. A list of about 15 container lines is in `config.py`. Whole words only, so `EVERGREEN SPIRIT`
  does not count as Evergreen.
- **By berth:** a cargo ship (or a ship with no reported type) moored at Waltershof (Burchardkai / Eurogate),
  Altenwerder or Tollerort is almost certainly a container ship. This catches feeder ships with no line name.
  The berth does **not** tell us the shipping line, so those ships show "—".
- Weak words that other ships also use (`EXPRESS`, `ONE`) only count when the ship reports a cargo type.
- A reported non-cargo type (tug, ferry, tanker) gives "Unlikely", even if the name contains a line's word.
  It says "unlikely", not "no", because the crew sets the type and it can be wrong.
- The table shows the clue: `Likely, by name` (with the line in the next column) or `Likely, berth at Waltershof`.

---

## Questions you will get, and honest answers

**"How accurate is it?"**
"It's not trying to predict the exact arrival. It flags ETAs that don't fit the distance and speed.
Ships slow down to save fuel, wait for berths and follow tides, so a calculated ETA is a sanity check."
*(After your first live runs, compare 3 ships with their real arrival and quote the result. Much stronger answer.)*

**"Did you use machine learning?"**
"Yes, as an experiment, and I measure it honestly. The GitHub Action saves a snapshot every 3 hours, and git
keeps every version, so I rebuild which ships were at sea and when they really arrived. A straight-line model
learns how far off the calculated ETA usually is. I test it with 'leave one ship out': each ship is predicted
by a model that never saw it. With the first ~24 ships the model was *not* better than the plain calculation
(about 9 h average error for both), so the dashboard says so and keeps the calculation as the main number.
It retrains after every collection, so it can improve as data grows. Companies like project44 and Kpler use
years of history; this shows I understand the method and its limits."

**"Where does the news come from?"**
"Public RSS feeds: maritime news sites (gCaptain, Splash247, The Loadstar, Hellenic Shipping News,
Container News) and Google News searches in English and German for the Port of Hamburg, the Elbe and nearby
waters. A headline is kept only if it names a place on the way to Hamburg, a disruption (storm, strike,
closure, congestion, accident, attack) and is clearly about ships, from the last 7 days. Disruptions near
Hamburg are shown first, because they can delay ships arriving in the next days. I chose no AI on purpose:
keyword matching can't invent facts, and the reader clicks through to the original article."

**"Why only Hamburg?"**
"To keep it focused and reliable. Adding ports is easy in the code, but one port done well is better."

**"Why not track ships from Asia?"**
"Free AIS from land receivers doesn't cover the open ocean. Satellite AIS covers it but is paid.
Focusing on the European approach uses the data where it's reliable."

**"What would you improve next?"**
"Log every flagged ship and check later whether it really arrived late. That measures how often
the flag is right, and lets me tune the 12-hour limit with data instead of a guess."

**"Can you see who owns the containers or the cargo?"**
"No, and that's on purpose. Containers are often leased from companies like Triton or Textainer, and the
cargo owner is only in the bill of lading, which is confidential. AIS never carries that. What I *can* show
is whether it's likely a container ship (from its name or its berth) and the shipping line running it
(from its name), and I label both as guesses."

**"Is it secure?"**
"Ship names are typed by crews and sent by radio, so anyone can send anything. I treat all AIS text as
untrusted: the collector keeps only characters the AIS standard allows and checks numbers are in their
AIS range, saved data is checked again whenever it's loaded, and the dashboard escapes every ship value
so it can't turn into a link. There are tests for both.
The API key is never in the code, and the GitHub Action is pinned to exact versions."

**"How does this cover procurement, warehousing and costs?"**
"Three additions. A shipping-line scorecard: from the saved history I rebuild which cargo ships really berthed and check
each one against the ETA it promised, with a 24-hour tolerance; a buyer uses that to pick and negotiate with
shipping lines. After the berth: from the ship's length I estimate its size, how long unloading takes with
typical crane rates, and when containers could leave by train or reach a warehouse by truck. And the cost of a
delay: the ship's charter rate from the New ConTex index plus the capital tied up in the cargo, using
Sea-Intelligence's $40,000-per-TEU benchmark. I left demurrage and detention out on purpose: they're fees for
containers left at the terminal or returned late, so a late ship doesn't cause them. Everything is a range, and
every assumption is written down in config.py."

**"How accurate is the shipping-line score?"**
"We only look every 3 hours, so I never know the exact berthing time, only a window. I only call a ship on
time or late when the whole window agrees; otherwise it's 'unclear'. And a line needs at least three judged
arrivals before it gets a percentage."

**"Who would use this?"**
"A forwarder or importer planning trucks and warehouse slots, or a terminal planning berths.
Anyone who needs an early warning that an ETA is unrealistic."

---

## Words to know

| Word | Meaning |
|---|---|
| AIS | Automatic Identification System: radio signals ships send with their position and details |
| ETA | Estimated time of arrival |
| MMSI | A ship's 9-digit radio ID |
| IMO number | A ship's permanent 7-digit ID |
| Knot (kn) | 1 nautical mile per hour (about 1.85 km/h) |
| Nautical mile (nm) | 1,852 metres |
| UN/LOCODE | Standard port code. Hamburg = DEHAM |
| Chokepoint | Narrow sea passage many ships must use (Suez, Hormuz, Dover Strait) |
| Elbe 1 | The point where ships enter the River Elbe towards Hamburg |
