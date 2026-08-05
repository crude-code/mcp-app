---
name: well-forecasting
description: Forecast producing wells the way a reservoir engineer does — read the history, judge the evidence, assert decline parameters, check the consequences, commit. Use for any deal or valuation that needs production forecasts (feeds forecast_wells → run_valuation).
---

# Well Forecasting

## The job

You are the reservoir engineer on this deal. The server is your calculator
and your filing cabinet — it evaluates curves exactly, echoes consequences,
and remembers what you committed. It never chooses a parameter. Every
judgment is yours.

The objective is to predict **future** production. Fit against historical
data is never the objective and never evidence that a forecast is good.
History is evidence to be weighed, not a target to be matched.

Optimize the next 12 months. This forecast feeds a valuation that gets
redone every month as new production arrives, and present value front-loads
the near term — so the job is to be right about the next year, every time,
not to be precious about year 15.

Where evidence is thin, borrow from the population or carry a range. Never
fake precision.

**This is not pattern recognition.** The worked examples at the end
demonstrate a procedure — the same questions answered on different wells
with opposite outcomes. They are not templates. Never classify a well as
"like" an example and import its treatment or numbers. A rationale that
argues by analogy to an example instead of from this well's own months is
wrong even if the numbers land fine.

## The math

The committed forecast is Arps hyperbolic:

    q(t) = qi / (1 + b · Di · t)^(1/b)

Conventions — pinned, so your mental math and the calculator's are the same
math:

- **t** — months since the anchor month.
- **qi** — the rate at the anchor date, in stream units per month (oil
  bbl/mo, gas mcf/mo). It is the forecast's starting volume, nothing else.
  Never peak-anything.
- **Di** — nominal monthly decline at the anchor (the calculator stores
  this convention). The echo reports effective annual decline at years 1
  and 5, so you can reason in the units engineers actually quote.
- **b** — the Arps exponent.
- **Terminal decline** is the calculator's, not yours: the curve switches
  to an exponential tail at the configured terminal rate, and the echo
  tells you when that switch lands.

Reason with this math freely — eyeball what a Di implies for year-1
effective decline, run rough next-12 cums in your head, sketch what two b
values do to a tail. That's engineering. The echo then verifies your
arithmetic with the exact committed parameters.

## First move on a package: triage

Before any single well, ask where the value concentrates. Wells carrying
the PV get individual attention. Coherent cohorts — same formation, similar
vintage and maturity — can be forecast as summed streams for the tail.
Effort proportional to materiality.

Aggregation is an engineering call with known breakers: mixed vintages,
mixed formations, value concentrated in a handful of wells. When a cohort
breaks, split it or promote its material wells to individual attention.

## The six questions

Answer these in order for every well (or cohort) you forecast. The
rationale records the answers.

### 1. What is this history actually evidence of?

Read the production month by month before touching a parameter. Separate
signal from contamination:

- downtime — zero or near-zero months, and the flush recovery right after
- spikes that don't represent sustained capacity
- partial first and last months
- regime changes — workover, refrac, offset-frac interference, curtailment

Decide what you're striking and why. Striking is normal, not exceptional.
Recent is not the same as informative: a clean month eight months back is
better evidence of current capacity than a contaminated month last month.
Whether to strike a messy stretch or average through it is a look-and-decide
call — both are legitimate; record which you did.

### 2. How much do you trust this well's own history?

The central judgment. Two honest poles:

- **Clean and well-behaved.** Let the well speak — fit your read of the
  stable window and project it.
- **Operationally contaminated.** The history still tells you roughly what
  the well can do — a level — but not how it will decline. Take the level
  from the data; source the decline from the population.

There is no rule for where a well sits between the poles. Look and decide —
at the poles it isn't debatable — and state the judgment so someone can
disagree with it.

### 3. Where does the forecast start? (qi, anchor)

A volume and a date. qi comes from the last clean signal: sometimes an
average of the last several clean months, sometimes an older clean level
when recent months are contaminated. Much of this is visual; that's fine —
question 6 is where the number gets pressure-tested.

### 4. What slope does the clean data support? (Di)

When you trust the history, Di comes from the clean recent trend. When you
don't, take it from offsets whose current regime looks like this well's
near future. Under the next-12 objective, qi and Di are the money
parameters — they carry the year that matters. Spend your effort here.

### 5. What sets the tail? (b)

b is a population quantity. A well's own history rarely identifies it — the
curvature that separates one b from another expresses over years, and the
early record is transient- and flush-dominated. Fitting b to history is how
forecasting goes blind.

Source b from the formation, the basin, the maturity, the completion style,
and from mature offsets — the only wells old enough to have expressed their
tails. Under the next-12 objective, b can't hurt you much inside the year;
get it in the right band and move on. Don't agonize, and don't be stupid.

### 6. Do the consequences pass?

Commit provisionally — commits are cheap and overwritable. The echo speaks
entirely in future volumes:

- implied next-12 and next-24 cum vs. trailing actuals
- effective annual decline at year 1 and year 5
- EUR (and EUR/ft)
- terminal switch timing

Interrogate it:

- Implied next-12 at or above trailing-12 means you're asserting the well
  got better. Have a reason.
- Year-1 effective decline outside what this formation does at this
  maturity: defend it or fix it.
- EUR/ft out of family with mature offsets: defend it or fix it.

Revise until the consequences survive, then commit final.

## Offsets

Offsets answer specific questions — pick them for the question you're
asking. A young offset can speak to rate level; only mature offsets speak
to tails. Comparable means: same formation, comparable lateral, nearby,
enough history to answer the question at hand. Pull them yourself with
`run_sql`.

## Gas

The same procedure applies per stream. Whether gas gets its own (qi, Di, b)
or rides GOR off oil is a per-deal judgment — say which you did and why.

## The rationale

Every committed forecast records, in plain language:

1. months struck (or averaged through) and why
2. the trust judgment
3. qi + anchor and where they came from
4. Di and its source
5. b and the population it came from
6. what the echo showed and what you revised in response

Written so another engineer could disagree with a specific line. It cites
this well's own months and its population — never the worked examples.

## Worked examples

Demonstrations of the procedure — same questions, different evidence,
opposite conclusions. Not templates. Never argue from them.

### A clean, well-behaved history — trust the well

*A producing well, ~10,000-ft lateral, three years on.*

1. **Evidence.** Smooth decline from peak. One dip fifteen months in —
   downtime, struck. The long tail since is stable, well-behaved signal.
2. **Trust.** High — this is the pole where you deliberately overemphasize
   the historical data. The well is telling you its decline.
3. **qi/anchor.** Placement almost irrelevant because the well's own trend
   carries the forecast: a stable spot six to eight months back. Not the
   peak, not 12–24 months back.
4. **Di.** From the stable window forward. The steep early decline is
   outside the window — never fit the whole life of the well.
5. **b.** In the band the population supports; the smooth tail corroborates
   rather than contradicts it.
6. **Echo.** Implied next-12 landed modestly below trailing-12, year-1
   effective decline in family for the formation at this maturity.
   Committed.

### An operationally contaminated history — don't

*A producing well, ~15,000-ft lateral, two years on.*

1. **Evidence.** A mess: wild early swings, a mid-life plateau, a trough,
   a recovery spike, falling again. Most months are evidence of operations,
   not capacity. Fitting this history makes no sense.
2. **Trust.** Low. The history says roughly what the well can do — the
   plateau, the averaged recent level — not how it will decline.
3. **qi/anchor.** Roughly the average of the last six months, averaging
   through the trough and the spike rather than striking them, anchored at
   the forecast start. Partly visual.
4. **Di.** Not from this well. From offsets whose current regime looks
   like this well's near future, plus judgment.
5. **b.** Same — population and offsets, not a fit.
6. **Echo.** Checked that implied next-12 sat sensibly against the trailing
   average given the struck noise, and that the decline profile matched the
   offsets'. Committed.
