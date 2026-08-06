# Handoff: Repositioning Well Forecasting in CrudeCode

**Date:** 2026-07-23
**Status:** Direction set at high level. Specifics deliberately deferred — do not treat anything below as a finished spec.

## The thesis

Well forecasting is not a good deterministic problem. The current engine (classification ladder, scipy curve_fit, type-curve construction) is judgment compiled too early into rules — every new well shape demands another branch, and it degrades into death by a thousand paper cuts. It also embeds the wrong objective: minimizing error against historical data. The objective is predicting **future** production; in-sample fit is never evidence for anything.

This aligns with the core CrudeCode design thesis: **Python does deterministic work; Claude does probabilistic work.** Parameter selection is judgment. It moves to Claude.

## The repositioning

1. **Claude generates the literal hyperbolic parameters.** Per well or cohort, Claude asserts `{qi, Di, b, anchor_month, struck_months, rationale}` and passes them into the MCP. There is no optimizer anywhere in the backend. curve_fit, the routing/classification ladder, and type-curve building get deleted — the deletion is bigger than the addition.

2. **qi is redefined.** qi means the rate the forecast starts from at the anchor date — never peak-anything. It comes from the last clean signal in the data, even if that's months back (recent months contaminated by downtime/spikes are worse evidence about current capacity than an older clean month).

3. **`forecast_wells` becomes accept-and-echo.** Server does bounds validation only, stores the forecast + rationale, and returns the *consequences* of the committed parameters: implied next-12/24 cum vs. trailing actuals, effective decline at year 1 and 5, EUR, terminal switch. This powers the sanity loop (assert → check consequences → revise → commit) without Claude doing arithmetic. Note the return speaks entirely in future volumes — never in fit quality. Commits are cheap and overwritable.

4. **Server keeps the calculator only.** Hyperbolic evaluation + terminal switch, consequence math, bounds checks, persistence, calendar placement, economics. Nothing server-side ever chooses a parameter.

## Teaching Claude to think like an engineer

The bigger idea: this isn't just per-well technique. An engineer's first move on a 50-well package is triage — where does the value concentrate, can we aggregate. Individual attention for the wells carrying the PV; coherent cohorts (same formation, similar vintage/maturity) forecast as summed streams for the tail; effort proportional to materiality. Aggregation is a first-class engineering call, with known breakers (mixed vintages, mixed formations, concentrated value). CrudeCode stops being a valuation calculator with an AI attached and becomes an engineer that uses a calculator.

## The skill

The decision layer moves into a skill — **prose only, no code shipped in the skill**. Contents, roughly:

- Objective and posture (predict the future; borrow from the population or carry a range rather than fake precision)
- Package triage doctrine
- Reading production (what to strike and why: downtime, spikes, partial last month)
- Parameter doctrine — qi definition, Di off the clean recent slope, b as a population quantity with basin/maturity guidance (b gets the most words; it's where the blindness is and where the economics swing)
- Sanity anchors and explicit revise triggers
- The loop + rationale spec
- **Worked examples** — real wells with the owner's numbers and narration. This is the highest-leverage content and only the owner can write it (Thunderhill and Jupiter are examples one and two). 5–10 wells covering recurring shapes.

## Open questions (do not assume answers)

- **Runtime code authorship.** "No code in the skill" is settled. Whether Claude composes SQL at runtime (vs. some other read path) was raised and **not resolved** — confirm before building the read side.
- Gas treatment: own (qi, Di, b) per stream vs. GOR off oil.
- Cohort→per-well allocation rule for economics (pro-rata trailing-12 was floated as a default).
- Guardrails/grading (blinding, hindcast as decision rule) discussed but explicitly deferred — this is not being used to book reserves yet.

## Deliberately not in scope

Bayesian/hierarchical machinery, probabilistic outputs, reserve-booking rigor. Take a shot at the simple version first.