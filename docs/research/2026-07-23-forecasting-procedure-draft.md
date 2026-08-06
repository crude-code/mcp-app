# Well Forecasting — The Procedure (draft for correction)

**Date:** 2026-07-23
**Status:** Draft. This is the decision-layer prose destined for the skill —
companion to `forecasting-ideas.md` (which holds the architecture direction).
`[OWNER: ...]` marks content only Bill can supply. Everything else is fair
game to cut, rewrite, or contradict; corrections here transfer straight into
the skill.

---

## Objective

You are forecasting future production. That is the entire objective. Fit
against historical data is never the objective and never evidence that a
forecast is good — a curve can ride every historical point and still be a bad
prediction, and a curve that ignores most of the history can be a good one.
Historical data is evidence to be weighed, not a target to be matched.

You are doing the job of a reservoir engineer, not a curve-fitting routine.
An engineer looks at the well, decides what the data is actually saying,
decides what the future looks like, and writes down parameters that express
that judgment: `{qi, Di, b, anchor_month, struck_months, rationale}`. The
parameters are the output of thinking, not of optimization.

Where the evidence is thin, borrow from the population or carry a range.
Never fake precision.

### This is not pattern recognition

The procedure below is a way of interrogating evidence. The worked examples
at the end are demonstrations of the procedure — the same questions answered
on different wells with different outcomes. They are not templates. Never
classify a well as "like" an example and import its treatment or its numbers.
If a rationale argues by analogy to an example instead of from this well's
own months, the forecast is wrong even if the numbers happen to be fine.

---

## First move on a package: triage

Before any single well, ask where the value concentrates. Wells carrying the
PV get individual attention. Coherent cohorts — same formation, similar
vintage and maturity — can be forecast as summed streams for the tail.
Effort proportional to materiality.

Aggregation is an engineering call with known breakers: mixed vintages,
mixed formations, value concentrated in a handful of wells.

`[OWNER: this section hasn't been narrated yet — needs your pass, ideally
against a real package.]`

---

## The per-well procedure

Six questions, in order. Every forecast answers all six, and the rationale
records the answers.

### 1. What is this history actually evidence of?

Read the production month by month before touching a parameter. Separate
signal from contamination:

- downtime — zero or near-zero months, and the flush recovery right after
- spikes that don't represent sustained capacity
- partial first and last months
- regime changes — workover, refrac, offset-frac interference, curtailment

Decide what you're striking and why. Striking is normal, not exceptional.
And recent is not the same as informative: a clean month eight months back is
better evidence of current capacity than a contaminated month last month.

Whether to strike a messy stretch entirely or average through it is a
look-and-decide call — both are legitimate; record which you did.

### 2. How much do you trust this well's own history?

The central judgment. Two honest poles:

- **The history is clean and well-behaved.** Let the well speak — fit the
  stable window and project it.
- **The history is operationally contaminated.** It can still tell you the
  rough level of current capacity, but not the decline path. Take the level
  from the data; source the decline from the population.

There is no rule for where a well sits between the poles. You look and you
decide — at the poles it isn't even debatable — and you state the judgment
in the rationale so someone can disagree with it.

### 3. Where does the forecast start? (qi and anchor)

qi is the rate the forecast starts from at the anchor date. It has nothing
to do with peak production — never peak-anything. You need a volume and a
date; that pair is the starting point.

It comes from the last clean signal. Sometimes that's an average of the last
several clean months. Sometimes recent months are contaminated and an older
clean level is the better start, even if it's months back. Much of this is
visual; that's fine — the consequence check (question 6) is where the number
gets pressure-tested.

### 4. What slope does the clean data support? (Di)

When you trust the history (question 2), Di comes out of the fit over the
stable window. When you don't, take it from offsets — wells whose current
regime resembles what this well's future should look like.

`[OWNER: how you sanity-check a Di before it goes in — what makes one
obviously too steep or too shallow.]`

### 5. What population sets the tail? (b)

The most important parameter and the one the well is least able to tell you.
b controls tail curvature, and the tail is where the volume and the money
are. The curvature that distinguishes one b from another expresses over
years — a well's own history, especially the early transient- and
flush-dominated part, rarely identifies it. Fitting b to history is how the
old engine went blind.

So b is a population quantity. Source it from what you know about the
formation, the basin, the maturity, the completion style — and from mature
offsets, the only wells old enough to have expressed their tails.

`[OWNER: the b doctrine — the actual ranges you carry, by basin/formation
and maturity, and what moves you inside a range. This is the section the
ideas doc says gets the most words, and only you can write it. Structure to
fill:`
- `by basin/formation: ...`
- `by maturity (what changes as a well ages): ...`
- `when mature offsets disagree with the book: ...]`

Terminal decline is not yours to choose — the calculator applies the
terminal switch. You assert qi, Di, b, anchor, and struck months; nothing
else.

### 6. Do the consequences pass?

Commit provisionally — commits are cheap and overwritable. The echo speaks
entirely in future volumes, never fit quality:

- implied next-12 and next-24 cum vs. trailing actuals
- effective annual decline at year 1 and year 5
- EUR (and EUR/ft)
- terminal switch timing

Interrogate it:

- If implied next-12 cum is at or above trailing-12, you are asserting the
  well got better. Have a reason.
- If year-1 effective decline is outside what this formation does at this
  maturity, defend it or fix it.
- If EUR/ft is out of family with mature offsets, defend it or fix it.

`[OWNER: correct/extend these revise triggers — which checks you actually
run and what thresholds, if any, you carry in your head.]`

Revise until the consequences survive interrogation, then commit final.

---

## Offsets

Offsets answer specific questions; pick them for the question you're asking.
A young offset can speak to rate level. Only mature offsets speak to the
tail. Comparable means: same formation, comparable lateral, nearby, enough
history to answer the question at hand.

(Open per `forecasting-ideas.md`: how the model reads offset data at runtime
— composed SQL vs. another read path. Confirm before the build; doesn't
change the doctrine above.)

---

## The rationale

A committed forecast records, in plain language:

1. months struck (or averaged through) and why
2. the trust judgment from question 2
3. qi + anchor date and where they came from
4. Di and its source
5. b and the population it came from
6. the consequence echo and what, if anything, was revised in response

Written so another engineer could disagree with a specific line. It cites
this well's own months and its population — never the worked examples.

---

## Worked examples

> Demonstrations of the procedure, not templates. Same questions, different
> evidence, opposite conclusions. Never argue from them; never reuse their
> numbers.

### Example: the clean, well-behaved history — trust the well

*(A producing well, 10,359-ft lateral.)*

1. **Evidence.** Clean, smooth decline from the May 23 peak. One dip at
   Aug 24 — downtime, struck. The long tail from late 24 onward is stable,
   well-behaved signal.
2. **Trust.** High — this is the pole where you deliberately overemphasize
   the historical data. The well is telling you its decline.
3. **qi/anchor.** Placement almost irrelevant because the fit carries the
   forecast: a nice stable spot 6–8 months back. Not the peak, not 12–24
   months back.
4. **Di.** From the fit over the stable window forward. The steep early
   decline is outside the window — we are absolutely not fitting the whole
   life of the well.
5. **b.** `[OWNER: did b come out of the tail fit here, or from the
   book/offsets? The doctrine above says own history rarely identifies b —
   is a 3-year smooth tail the exception, or did you still source b
   externally?]`
6. **Consequences.** `[OWNER: the committed numbers and what the echo showed
   — reconstructable from the chart/run if not from memory.]`

### Example: the operationally contaminated history — don't

*(A producing well, 15,612-ft lateral.)*

1. **Evidence.** A mess: wild early swings, a mid-25 plateau, a trough
   around Dec 25, a recovery spike at Mar 26, falling again after. Fitting
   this history doesn't make sense — most months are evidence of operations,
   not of capacity.
2. **Trust.** Low. The history still says roughly what the well can do
   (the plateau, the averaged recent level); it does not say how it will
   decline.
3. **qi/anchor.** Roughly an average of the last six months — averaging
   through the trough and the spike rather than striking them — anchored at
   the forecast start (Jun 26). Partly visual.
4. **Di.** Not from this well's fit. Looked at offsets and formed a best
   estimate. `[OWNER: reconstruct or re-derive — which offsets, what
   number.]`
5. **b.** Same — offsets plus judgment, not a fit. `[OWNER: the number and
   the reasoning.]`
6. **Consequences.** `[OWNER: the committed numbers and what the echo
   showed.]`

---

## Deliberately unresolved (tracked in `forecasting-ideas.md`)

- Runtime read path for offsets (SQL at runtime vs. other) — confirm before
  building.
- Gas: own (qi, Di, b) per stream vs. GOR off oil.
- Cohort→per-well allocation for economics.
- Grading/hindcast as a decision rule — deferred; not booking reserves yet.
