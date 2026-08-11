---
description: Explain the model, or walk one recommendation's arithmetic backwards
argument-hint: "[SKU and store, or blank for the model]"
---

If `$ARGUMENTS` names a SKU/store: open the latest `.redpill/runs/*/report.json`, find that
row, and explain its decision trace in plain words — raw inputs → any corrections/overrides
(provenance) → pipeline/buffer/ROP → the ladder condition that matched (status_reason) → the
recommended action, with this store's numbers only. Quote only values present in report.json;
if the row isn't there, say so.

If no arguments: explain the model itself — the five formulas, the six-status ladder and its
strict order, transfers-before-orders, and the never-guess rule — using the definitions in the
skill's `references/formulas.md`. Keep it under a screen; offer depth on request.
