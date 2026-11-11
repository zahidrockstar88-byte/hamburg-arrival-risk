# Hamburg Arrival Risk Monitor

Watches ships on their way to the Port of Hamburg and flags the ones whose own arrival time doesn't fit
the distance still to go.

## Ships

**Hamburg-bound ship**:
A ship whose crew-entered final destination means Hamburg. A voyage that only passes through Hamburg on the
way somewhere else is not Hamburg-bound.
_Avoid_: Inbound ship, arriving ship

**Container ship (likely)**:
A Hamburg-bound ship judged to probably carry containers, from its name or from being moored at a container
terminal. Always a judgement, never a fact reported by the ship.
_Avoid_: Box ship, containership (as a certain fact)

**Shipping line**:
The carrier that runs a ship's service and sells its cargo space, such as MSC or Maersk. Not the ship's owner,
not the owner of the containers, and not the owner of the cargo.
_Avoid_: Carrier (in UI text), operator, owner, company

## Arrival

**Arrival**:
The moment a Hamburg-bound ship is moored at a berth in the Port of Hamburg. Every ETA, every accuracy check and
every "late" judgement refers to this moment.
_Avoid_: Arrival at the pilot station, entering the port area, reaching the Elbe

**Arriving**:
A Hamburg-bound ship on its final approach: in the port area or on the river close to Hamburg, but not yet moored.
_Avoid_: Arrived (unless moored)

**Arrived**:
A Hamburg-bound ship that has made its arrival: moored at a Hamburg berth.
_Avoid_: In port (ambiguous: anchored ships are also "in port")

**Reported ETA**:
The arrival time the ship's crew entered themselves and broadcasts.
_Avoid_: ETA (on its own), crew ETA, AIS ETA

**Calculated ETA**:
The arrival time worked out from the distance still to go along the sea route and the ship's speed.
_Avoid_: Predicted ETA, real ETA, correct ETA

**ML ETA**:
An experimental arrival time that corrects the calculated ETA using what happened to earlier ships. Always shown
as experimental, next to its measured error.
_Avoid_: Predicted ETA, AI ETA

## Not moving

**Waiting**:
A Hamburg-bound ship that is not moving at sea or at anchor, usually waiting for a berth, the tide or a pilot.
A delay signal.
_Avoid_: Stopped, idle, anchored (when the reason is unknown)

**In another port**:
A Hamburg-bound ship moored at a berth somewhere else, working cargo before it sails on to Hamburg. Normal, not
a delay signal.
_Avoid_: Stopped, waiting, delayed

**Promised ETA**:
The reported ETA a ship gave the first time we saw it under way. The carrier scorecard checks arrivals
against it.
_Avoid_: Scheduled arrival (the published schedule is something else)

**Schedule reliability**:
The share of judged arrivals that berthed within a day of their promised ETA, per shipping line.
_Avoid_: On-time performance (when it means something measured differently)

**Berthing window**:
The time span in which a ship must have berthed: after we last saw it under way, and no later than the first
time we saw it moored.
_Avoid_: Arrival time (when only the window is known)

## After the berth

**Container availability**:
The time from which a container unloaded in Hamburg can be collected by truck: after unloading and yard
release.
_Avoid_: Discharge time (that's when it leaves the ship)

**Delay cost**:
The estimated cost of a ship that is likely to berth later than the ETA its crew reports now: the ship's time
plus the capital tied up in its Hamburg cargo.
_Avoid_: Demurrage, detention (fees for containers left at the terminal or returned late, after unloading)

## Risk

**Risk flag**:
The judgement shown for each ship: Likely late, Check, On track, In another port, Arriving or Arrived.
It is a warning, not a forecast.
_Avoid_: Prediction, status (when meaning the flag)

**Stale position**:
A ship's last known position that is too old to trust for judging its arrival.
_Avoid_: Old data, lost ship

## Route

**Chokepoint**:
A narrow or exposed passage on the way to Hamburg where conflict, closure or congestion can change routes and
arrival times, such as the Red Sea or the Strait of Hormuz.
_Avoid_: Risk zone, hotspot

**Disruption**:
A reported event that can delay ships on the way to Hamburg: a storm, strike, closure, congestion, accident or
attack.
_Avoid_: Incident, news (when meaning the event itself)

## Data

**Snapshot**:
One saved picture of every Hamburg-bound ship at a moment in time. Snapshots taken one after another are the
project's only record of what happened to a ship.
_Avoid_: Run, dump, export
