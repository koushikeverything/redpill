---
description: Produce a blank MIS template with column meanings and one worked example row
---

Run `python3 <skill>/scripts/redpill_engine.py --template` (from the redpill-inventory skill),
then hand the user the generated `redpill_input_template.csv` and explain each column in one
line, exactly as the legend in the file states: sku, store, soh (stock on hand), qoo (on
order, blank = 0), ads (average daily sales — blank is NOT zero), lead_time (days, required),
unit_price (optional, enables ₹ values). One row per SKU × store. Offer to convert to xlsx
only if asked.
