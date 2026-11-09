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

## The five steps

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

**4. Compare and flag.** The first rule that matches wins:

| Flag | Rule | Why it matters |
|---|---|---|
| ⚪ Arriving | Within 15 nm of Hamburg | Nothing to predict |
| 🟡 Data too old | No position for 24+ hours | Can't trust anything else |
| 🟡 Stopped | Speed under 1 kn or at anchor | Waiting for berth, tide or pilot: time unknown |
| 🟡 No ETA sent | Crew entered no valid ETA | Nothing to compare |
| 🔴 ETA already passed | Reported ETA is in the past, ship still 50+ nm away | Clearly out of date |
| 🔴 Likely late | Calculated ETA is 12+ hours after reported ETA | Reported ETA looks unrealistic |
| 🟢 On track | Everything else | |

The 12-hour limit is a setting you can change in the sidebar.

**5. Add route context.**
If the ship was seen off West Africa, it probably came around the Cape of Good Hope instead of through Suez
(roughly 10–14 extra days from Asia). If it was seen in the Mediterranean, it came via Suez or a Med port.
Chokepoint notes (Red Sea, Hormuz, port congestion) come from a file updated by hand each week.

---

## Questions you will get, and honest answers

**"How accurate is it?"**
"It's not trying to predict the exact arrival. It flags ETAs that don't fit the distance and speed.
Ships slow down to save fuel, wait for berths and follow tides, so a calculated ETA is a sanity check."
*(After your first live runs, compare 3 ships with their real arrival and quote the result. Much stronger answer.)*

**"Why not use machine learning?"**
"Companies like project44 and Kpler do that with years of historical data. For a student project,
a transparent rule anyone can check is more useful and easier to explain to an operations team."

**"Why only Hamburg?"**
"To keep it focused and reliable. Adding ports is easy in the code, but one port done well is better."

**"Why not track ships from Asia?"**
"Free AIS from land receivers doesn't cover the open ocean. Satellite AIS covers it but is paid.
Focusing on the European approach uses the data where it's reliable."

**"What would you improve next?"**
"Log every flagged ship and check later whether it really arrived late. That measures how often
the flag is right, and lets me tune the 12-hour limit with data instead of a guess."

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
