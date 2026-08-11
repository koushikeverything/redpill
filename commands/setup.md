---
description: One-time Red Pill setup — profile, tracked fields, business rules (all skippable)
---

Set up (or revisit) the Red Pill profile for this project. Ask with bounded questions —
native selection cards where the surface supports them, otherwise numbered choices in chat.
Every question is skippable; defaults apply. Ask, in order:

1. Retail type (apparel/lifestyle is the tuned default; others work with generic vocabulary).
2. Currency symbol (default ₹).
3. Which optional fields their stock file tracks: reserved/online stock · damaged stock ·
   case-pack size · supplier · promotions calendar. (Multi-select.)
4. Business rules to never break — seed with: never drain a named flagship store · no
   transfers between named locations · no fresh orders for clearance items. Plus free text.
5. Weekly purchase budget, if any (free text, skippable).

Write answers to `.redpill/config.json` (and rules to `.redpill/policies.json`). Show the
saved profile back in one compact block. Do not invent defaults for anything the user skipped —
absence means "engine defaults + ask later if it matters". Never write anything the user
didn't confirm.
