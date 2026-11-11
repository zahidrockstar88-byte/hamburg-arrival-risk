# Arrival means moored at a Hamburg berth

A ship's "arrival" in this project is the moment it is moored at a berth in the Port of Hamburg, not when the
pilot boards at Elbe 1 and not when it first enters the port area. Every ETA (reported, calculated, ML), every
accuracy check and every "late" judgement refers to that moment, because berthing is when terminals, truckers
and forwarders can actually act on the cargo, and the calculated ETA already included the river trip and a
berthing buffer.

## Considered Options

- **Pilot boarding at Elbe 1**: the usual "arrival" in charter contracts (notice of readiness), so a shipping
  reader may expect it. Rejected: it is hours before the cargo is reachable.
- **Entering the port area (~15 nm)**: what the first version of the Arriving flag and the ML target used.
  Rejected: it is 1½–2½ hours before berthing, so it disagreed with the calculated ETA and biased the model.

## Consequences

The ML model learns from the first snapshot that shows a ship moored in Hamburg, which leaves fewer usable
examples than "first seen within 15 nm". Crews' reported ETAs may themselves mean the pilot station; that is a
data limit, not a change to this definition.
