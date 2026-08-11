---
name: well-forecasting
description: Forecast wells like an expert reservoir engineer — read the history, diagnose the flow regime, judge the evidence, assert decline parameters, check the consequences, commit. Use for any deal or valuation needing production forecasts (feeds forecast_wells → run_valuation).
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

Forecasting is not two methods — a decline-curve branch for producers and
a type-curve branch for everything else. It is one method on a continuum:
every forecast blends what the well has said with what its population
says, weighted by how much the well has said. One reported month — you
don't even know it's the peak — is forecast almost entirely from analogs.
Seven months in, the level is the well's own but Di and b still come from
the population, checked against what little slope the well shows. Three
clean years and the well carries its forecast. The analog method (below)
is not the non-producer branch; it is the population end of every
forecast.

Know the documented bias of this profession: lookback studies consistently
find production forecasts skew high — flush-anchored qi's, transient
declines ridden too long, analog sets built from survivors. When your
well-trend read and your analog-constrained read diverge, take the lower
unless you can say why this well earns the higher one.

**This is not pattern recognition.** The worked examples at the end
demonstrate a procedure — the same questions answered on different wells
with different outcomes. They are not templates. Never classify a well as
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

One piece of physics you carry everywhere: Arps decline theory assumes
**boundary-dominated flow** — the well draining a fixed volume. Tight and
shale wells spend their first months-to-years in **transient flow**, where
the pressure signal hasn't yet found its boundaries and the data trace out
a steeper-then-flattening path that fits a very high b. Transient behavior
is a phase, not a property. Every well leaves it — real boundaries or
fracture interference see to that — and the forecast has to leave it too.
The terminal switch is what saves a high-b curve from asserting the
transient lasts forever; that's why b > 1 and the switch timing are always
judged together (question 5, check 6).

Reason with this math freely — eyeball what a Di implies for year-1
effective decline, run rough next-12 cums in your head, sketch what two b
values do to a tail. That's engineering. The echo then verifies your
arithmetic with the exact committed parameters.

## The workflow

Three tools carry the whole job:

1. **Evidence comes from `run_sql`.** Pull each subject well's monthly
   history yourself:

       SELECT prod_date, oil_bbl, gas_mcf
       FROM public.production WHERE well_api = '05-123-…'
       ORDER BY prod_date

   One well's full history fits the row cap; for a cohort's summed stream,
   `GROUP BY prod_date` with `SUM(oil_bbl)`. Offsets, mature-well tails,
   EUR/ft families, operator timing cadence — all the same tool (its
   docstring carries the full schema).

2. **Commitment goes through `forecast_wells`.** One entry per well (or
   cohort — a multi-well `wells` list forecasts their summed stream):

       {"wells": ["05-123-…"],
        "oil":  {"qi": 4300, "di": 0.056, "b": 1.1},
        "gas":  {"qi": 11800, "di": 0.050, "b": 1.2},
        "anchor_month": "2026-05",
        "uptime_factor": 0.96,
        "struck_months": ["2025-11"],
        "rationale": "…"}

   Each stream you forecast gets its own parameters; a stream left `null`
   contributes zero revenue (the echo warns if it recently produced). The
   server validates sanity bounds only — everything inside the bounds is
   your call, and the echo is where a bad-but-legal number gets caught.

3. **The echo closes the loop.** Every commit returns the consequences
   (question 6). Commits are cheap and overwritable: re-committing a well
   replaces its forecast, so assert → interrogate → revise → commit final
   is the intended rhythm, not a workaround. A validation bounce saves
   nothing — fix every listed violation and resend the call.

## First move on a package: triage

Before any single well, ask where the value concentrates. Wells carrying
the PV get individual attention. Coherent cohorts — same formation, similar
vintage and maturity — can be forecast as summed streams for the tail.
Effort proportional to materiality.

A cohort entry asserts one set of parameters for the group's **summed**
stream (pull it with `GROUP BY prod_date` and read it like a single well —
summing smooths single-well noise). The server splits the committed volumes
back to member wells pro-rata on trailing-12 production, so per-well
ownership interests price correctly; the echo reports the shares. Every
member must have trailing-12 production on each asserted stream — a dry or
not-yet-producing well can't take a share and gets forecast individually
(the server bounces it by name if you try).

Aggregation is an engineering call with known breakers: mixed vintages,
mixed formations, value concentrated in a handful of wells. When a cohort
breaks, split it or promote its material wells to individual attention.

## The six questions

Answer these in order for every well (or cohort) you forecast. The
rationale records the answers.

### 1. What is this history actually evidence of?

Read the production month by month before touching a parameter. Every
contamination pattern has a signature; learn to read them:

| Pattern | Signature in the monthly data | Treatment |
|---|---|---|
| Downtime + flush | Zero or near-zero month(s); the month after comes back **above** trend, bleeding off over 1–3 months | Strike the downtime months **and** the flush month(s). The real decline passes through the post-flush data |
| Curtailment | Sustained step down to a suspiciously flat level, then a return to the prior trend; often hits neighboring wells the same months | Strike or fit around it. The well's capacity didn't change; its market did |
| Frac hit / offset interference | Abrupt dip — often to zero, parents get shut in for offset completions — then a weeks-to-months recovery | Wait for post-hit data to declare itself. If it parallels the old trend at a lower level, the well took permanent damage: **re-initialize there**, don't average through the dip. Some parents recover fully; some never do |
| Workover / recompletion / refrac | Shut-in, then a step **up** that holds for 2–3+ months. Persistence is what separates it from flush | A regime change. New segment: fresh qi and Di from the post-event data; the old level is history |
| Artificial lift install | Rate had been sagging **below** the established trend (the well was loading up), then a modest jump back to or above it | New segment — and expect the post-install decline to be steeper. Lift accelerates the same reserves; it doesn't add any. Never project the loading-suppressed pre-install slope |
| Choke management | Early months flat or barely declining — a plateau, not a decline | Start the fit where the plateau breaks. A choked plateau says nothing about decline shape; fitting it wildly understates the true decline |
| Allocation noise | Sawtooth of ±10–20% with no operational story; pad-mates jumping in opposite directions the same month | Average through it. Fit the trend, don't chase the points |
| Partial / trailing months | Low first month (came online mid-month); last month or three often incomplete and later revised upward | Drop the first month; drop trailing months you can't trust as complete |

The organizing rule: **strike biased contamination, average through
zero-mean noise.** Shut-ins, flush, frac-hit troughs, choked plateaus, and
partial months all push the read in a *direction* — they get struck.
Allocation sawtooth and routine scatter wobble *around* the truth — average
through them. Both calls are legitimate engineering; record which you made
and why.

Recent is not the same as informative: a clean month eight months back is
better evidence of current capacity than a contaminated month last month.
When time-coordinates are ambiguous, look at rate against cumulative —
contamination that hides in a time plot is often obvious in q vs. Np.

### 2. How much do you trust this well's own history?

The central judgment. Two honest poles:

- **Clean and well-behaved.** Let the well speak — read the stable window
  and project it.
- **Operationally contaminated.** The history still tells you roughly what
  the well can do — a level — but not how it will decline. Take the level
  from the data; source the decline from the population.

Maturity moves the dial independently of cleanliness. As a default
weighting, before contamination adjustments:

- **Under a year on production** — even clean data is mostly transient and
  flush; it earns a level, not a shape. Forecast from the population (run
  the analog method); let the well's own months scale it up or down.
- **One to three years** — the blend. The well's own trend starts carrying
  the near-term slope; the population still owns b and the tail.
- **Three-plus years of clean decline** — the well has expressed itself.
  Its own history carries the forecast; the population only informs the
  late-life tail nobody's history reaches.

There is no rule for where a contaminated well sits between the poles.
Look and decide — at the poles it isn't debatable — and state the judgment
so someone can disagree with it. One more source of regime honesty: a
persistent step in the history (workover, unrecovered frac hit, lift
change) means the well has more than one regime. Fit the regime that will
persist — the most recent stable segment — and let older segments inform
shape, not level.

### 3. Where does the forecast start? (qi, anchor)

A volume and a date. qi is a **trendline value at the anchor date, never a
single reported month** — the raw last month is the noisiest number in the
dataset (downtime, allocation, incompleteness). The working recipe: take
the last stretch of clean, continuous months — often 6 to 12, sometimes
18–24 on a smooth well — strike or average per question 1, drop trailing
months you can't trust, and read the trend's value at the anchor. When
recent months are contaminated, an older clean level projected forward
beats a recent dirty one — anchor there; the anchor does not have to be
the last reported month. It does not have to be a reported month at all:
qi is simply the rate where the forecast starts, and the anchor can sit
in the future — on a 36-month producer just as on an undrilled location.
The math is identical everywhere on that spectrum. After a regime
change, the new segment starts
where the post-event data says it starts — not where the old curve left
off.

Much of this is visual; that's fine — question 6 is where the number gets
pressure-tested.

**Capacity is not what gets reported.** The trendline you just read is the
well's capacity; the volumes that will actually be booked include the
downtime you've been striking. Striking contamination was right for
reading the decline — but a forecast of clean-capacity months will sit
above reported actuals by exactly the downtime rate, every time, because
downtime only ever subtracts. So compute the well's **uptime factor**:
over the trailing 24 clean-regime months, reported volume divided by your
trendline's volume (a well down one month in twelve at half rate carries
~0.96; a chronically interrupted well might carry 0.85). Pass it as
`uptime_factor` — the server commits the curve times the factor, so what's
booked is expected *reported* volumes while your qi stays an honest
trendline value. State the factor's basis in the rationale. If the
operator's other wells run cleaner or rougher than this one's own record
suggests, say so and adjust — but never commit a bare capacity curve as if
the future contains no bad months.

### 4. What slope does the clean data support? (Di)

When you trust the history, Di comes from the clean recent trend. When you
don't, take it from the analog set (the analog method below) — wells whose
current regime looks like this well's near future. Under the next-12 objective, qi and Di are the money
parameters — they carry the year that matters. Spend your effort here.

### 5. What sets the tail? (b)

b is a population quantity. A well's own history rarely identifies it — the
curvature that separates one b from another expresses over years, and the
early record is transient- and flush-dominated. Fitting b to history is how
forecasting goes blind.

Know why the trap is so seductive: early tight-well data genuinely *is*
steep-then-flattening — transient linear flow fits b near 2, and the fit
looks great. But that b describes a phase the well is leaving, not the
decline it will settle into. Wells fit at b = 1.4 on a year of data refit
near 1.0 on five years, over and over. The whole documented history of
overstated shale EURs is this one move: fitting the transient and riding
it to abandonment. So: **a b above 1 is an assertion about the transient
segment only**, and it is only honest alongside a terminal switch that
lands when boundary-dominated behavior plausibly arrives — not
conveniently past the horizon anyone checks. Mature offsets that have
flattened out are your best evidence of where this well's tail actually
goes.

Source b from the formation, the basin, the maturity, the completion style,
and from mature offsets — the only wells old enough to have expressed their
tails (in a built analog set, its oldest members). The priors table at the end gives the bands plays actually exhibit;
the deal's own offsets outrank it. Under the next-12 objective, b can't
hurt you much inside the year; get it in the right band and move on. Don't
agonize, and don't be stupid.

### 6. Do the consequences pass?

Commit provisionally — commits are cheap and overwritable. The echo speaks
entirely in future volumes:

- implied next-12 and next-24 cum vs. trailing actuals
- effective annual decline at year 1 and year 5
- EUR — cum-to-date plus the full run-out through the terminal tail —
  and EUR/ft
- terminal switch timing
- warnings the server noticed (an unforecast stream that recently
  produced, a di that never reaches the terminal switch, an anchor past
  the last reported month)

Interrogate it:

- Implied next-12 at or above trailing-12 means you're asserting the well
  got better. Have a reason.
- Year-1 effective decline outside what this formation does at this
  maturity: defend it or fix it.
- EUR/ft out of family with mature offsets: defend it or fix it. Twice the
  top of the play's range is not a finding, it's an error until proven
  otherwise.
- Remaining reserves (`eur_remaining`) against cumulative-to-date, judged
  by maturity: a young well forecast to produce a multiple of its cum can
  be right; a mature well forecast to triple its cum almost never is.
- Any b above 1: look at where the terminal switch lands. If the switch
  sits decades out, the curve is quietly claiming the transient never ends
  — pull the switch in or lower b.
- Year-5 effective decline should be closing on the terminal rate, not
  still in free-fall.
- **The EUR is the run-out — believe it or fix the decline.** The echo has
  already run the committed curve through the terminal tail and added
  cum-to-date; ask the flat question: is that a reasonable EUR for this
  well? A decline that's only slightly generous at month 12 can be badly
  wrong by month 36 and absurd by abandonment — the error compounds, and
  the EUR is where it surfaces. If the total isn't believable, the decline
  is wrong *now*, not later. This is one sanity check, not the only one —
  invent whatever others this well calls for. The obligation is to have
  looked at the consequences with your own judgment, not to have followed
  a recipe.

Revise until the consequences survive, then commit final.

## The analog method

Population evidence enters every forecast — corroborating the tail on a
mature well, owning Di and b on a young one, carrying everything for a
well that hasn't produced. This is how you build the population.

Offsets answer specific questions — pick them for the question you're
asking. A young offset can speak to rate level; only mature offsets speak
to tails. Take the set as it comes — analog populations built only from
the good ones are how type curves go optimistic. Pull them yourself with
`run_sql`.

Rule zero: you come up with an estimate. A thin or ugly analog set never
excuses a refusal — it widens the uncertainty. The honest move is to make
the call, name its weakness, and work it with the user.

### Building the set

Filter in this order, loosening only when the count demands it:

1. **Geography.** Distance from the subject well. Start around a 15-mile
   radius and tighten toward 7 as the count allows. `public.wells.geom`
   is PostGIS — `ST_DWithin` does the work.
2. **Vintage.** First production in the last five years; reaching further
   back is rarely justified. Vintage is a proxy for frac design and a bit
   of depletion — a ten-year-old well had fewer perforations and longer
   stages, and simply wasn't as good a well.
3. **Formation.** Same formation. Mixing formations is a starvation move —
   legitimate when the count forces it, named in the rationale when made.
4. **Frac design.** Proppant and fluid per lateral foot
   (`total_proppant_lbs` / `lateral_length_ft`, likewise
   `total_fluid_bbl`), plus `frac_stages`. That is most of what the data
   carries about the completion; use it.
5. **Spacing.** A crowded infill child is not an analog for a bounded
   parent, or vice versa.
6. **Smaller cuts** as the situation earns them — the operator's own
   wells, if you know something about how the operator runs.

Aim for at least 10 wells, usually fewer than 30 — soft numbers, not
rules. Below ~10 the average is noise-prone, and you say so; above ~30
the filters are probably too loose to mean "analogous."

One query pulls the candidates:

    SELECT w.well_api, w.operator, w.first_prod_date, w.lateral_length_ft,
           ROUND(w.total_proppant_lbs / NULLIF(w.lateral_length_ft, 0)) AS lbs_ft
    FROM public.wells w
    WHERE ST_DWithin(w.geom::geography,
            (SELECT geom::geography FROM public.wells WHERE well_api = '05-123-…'),
            15 * 1609)
      AND w.formation = 'NIOBRARA'
      AND w.first_prod_date >= CURRENT_DATE - INTERVAL '5 years'
      AND w.well_api <> '05-123-…'

**Pads.** Forecasting a pad that's about to go in? Skip individual
analogs and find analogous *pads* — averaging whole pads smooths out
single-well noise (allocation swaps between pad-mates cancel in the sum).
There is no pad column; infer pads as same-operator wells clustered
tightly with first production within a month or two of each other.

### Reading the parameters

Peak-align the set: chop each well's ramp-up months and line the wells up
at their peaks, then average. `prod_month` (1 = the well's first
reported month) makes the alignment mechanical:

    WITH peaks AS (
      SELECT DISTINCT ON (well_api) well_api, prod_month AS peak_m
      FROM public.production WHERE well_api IN (…)
      ORDER BY well_api, oil_bbl DESC)
    SELECT p.prod_month - k.peak_m AS months_from_peak,
           COUNT(*) AS n_wells,
           AVG(p.oil_bbl)::int AS oil_bbl, AVG(p.gas_mcf)::int AS gas_mcf
    FROM public.production p JOIN peaks k USING (well_api)
    WHERE p.well_api IN (…)   -- repeat the list; keeps the planner on the
      AND p.prod_month >= k.peak_m   -- index and inside run_sql's time cap
    GROUP BY 1 ORDER BY 1

Read the averaged stream like a single well and take the hyperbolic
parameters from it: the aligned peak sets the level, the early months set
Di, the flattening sets b. The fit is subject to the same transient
discipline as any fit — a stack of two-year-olds is transient evidence no
matter how many wells are in it, so the priors table and the set's oldest
members still own the tail. And watch `n_wells`: where the stack thins,
the average has quietly become a different, older population.

**Normalizing.** Dividing rates by lateral length, averaging per-foot,
and rescaling to the subject's lateral is common practice; know it, and
do it if the user asks. It is not the default here — the rate-to-length
relationship is not linear. Prefer filtering to comparable laterals so
the raw averages compare directly.

### Applying it

The analog curve commits like any other forecast: anchor where the
subject's forecast starts and read qi there; the subject's own months, if
it has any, scale the level up or down. Same math for a 36-month producer
and an undrilled location — only the evidence mix changes.

## Wells not yet producing: level, shape, and timing

A DUC or permitted location gives you no history — questions 1 and 2
collapse to "there is none; source everything from the population." Three
assertions replace them:

- **Level and shape** come from the analog method, run in full: build the
  set, peak-align, and take qi, Di, and b from the averaged stream (an
  infill child typically runs below its parents — say where the subject
  sits inside its set). No `uptime_factor` on a well that hasn't produced:
  there is no record to compute one from, so just assume it runs.
- **Timing is yours too.** `anchor_month` for a non-producer is the
  asserted **first-production month**, and it can swing a PUD-heavy deal
  more than any decline parameter. Source it in order of quality: the deal
  itself (broker deck rig lines, AFE dates, stated development plans — and
  when it's material and absent, ask the user); the operator's observable
  cadence (`run_sql`: how fast this operator's recent wells went from
  permit to first production in this county); and only then default norms
  — a DUC ~18 months out, a permit ~36, adjusted for visible activity
  (an active rig on the pad vs. a permit aging toward expiry).
- The server dates the drilling capex at your asserted online month and
  discounts the well in its status bucket; the echo for these wells leads
  with `online_month` and has no trailing comparison — EUR/ft against the
  offset family is the sanity anchor that remains.

## Gas and water

Gas gets its own (qi, Di, b) — the same six questions on the gas stream.
The physics that links the streams: in tight oil, GOR runs roughly flat
while the reservoir is above bubble point, then climbs — often starting
within the first year or two. A climbing GOR means gas holds up while oil
declines: expect the gas Di you assert to run shallower than the oil Di,
and say what GOR behavior you read in the history. A fixed gas-oil ratio
is the one assumption you know is wrong. An abrupt GOR spike with a rate
drop is operations (lift trouble, choke change), not depletion.

Water is never valued and never committed, but when the dataroom carries
it, read it as a diagnostic: early declining water is frac-load flowback
and normal; a step up in water with an oil dip is the classic frac-hit
fingerprint; a slow monotonic rise speaks to aquifer or flood advance.
(The production database carries oil and gas only.)

## The rationale

Every committed forecast records, in plain language:

1. months struck (or averaged through) and why
2. the trust judgment — cleanliness, maturity, and any regime breaks
3. qi + anchor and where they came from, and the uptime factor applied
4. Di and its source
5. b and the population it came from, and where the terminal switch lands
6. for a non-producer: the asserted first-production month and its source
   (deal-stated / operator cadence / default norm)
7. what the echo showed — including whether the run-out EUR is believable
   — and what you revised in response

Written so another engineer could disagree with a specific line. It cites
this well's own months and its population — never the worked examples.
When the analog method carried parameters, the rationale names the set:
the filters, the count, and any starvation moves (a widened radius, mixed
formations).

## Parameter priors

Bands plays actually exhibit — starting points and sanity rails, not
answers. The deal's own offsets always outrank this table.

| Population | b | Year-1 effective decline |
|---|---|---|
| Conventional, boundary-dominated | 0–0.5 | 5–30% |
| Shale / tight oil (Permian, Bakken, Eagle Ford) | ~0.9–1.5 | ~50–95% |
| Shale gas (Marcellus, Haynesville) | ~0.8–1.6 | ~55–100% |

Maturity flattens everything: tight-well declines converge toward roughly
15–20%/yr by year five regardless of basin, then grind down toward the
terminal rate. Newer, higher-intensity completions run higher qi and
steeper Di with similar or lower b; infill children typically run lower qi
than their parents. A forecast whose year-5 behavior contradicts these
shapes needs a reason.

## Worked examples

Demonstrations of the procedure — same questions, different evidence,
different conclusions. Not templates. Never argue from them.

### A clean, well-behaved history — trust the well

*A producing well, ~10,000-ft lateral, three years on.*

1. **Evidence.** Smooth decline from peak. One dip fifteen months in —
   downtime, struck, along with the mild flush month after. The long tail
   since is stable, well-behaved signal.
2. **Trust.** High — three years of clean decline is the pole where you
   deliberately overemphasize the historical data. The well is telling you
   its decline.
3. **qi/anchor.** Placement almost irrelevant because the well's own trend
   carries the forecast: the trendline value at a stable spot six to eight
   months back. Not the peak, not a single reported month.
4. **Di.** From the stable window forward. The steep early decline is
   transient — outside the window; never fit the whole life of the well.
5. **b.** In the band the population supports; the smooth tail corroborates
   rather than contradicts it, and the echo's terminal switch lands at a
   believable age.
6. **Echo.** Implied next-12 landed modestly below trailing-12, year-1
   effective decline in family for the formation at this maturity.
   Committed.

### An operationally contaminated history — don't

*A producing well, ~15,000-ft lateral, two years on.*

1. **Evidence.** A mess: wild early swings, a mid-life plateau, a trough,
   a recovery spike, falling again. Most months are evidence of operations,
   not capacity. Fitting this history makes no sense.
2. **Trust.** Low. The history says roughly what the well can do — the
   plateau, the averaged recent level — not how it will decline. Two years
   on, the population would own b and the tail even if the data were clean.
3. **qi/anchor.** Roughly the average of the last six months, averaging
   through the trough and the spike rather than striking them, anchored at
   the forecast start. Partly visual.
4. **Di.** Not from this well. From offsets whose current regime looks
   like this well's near future, plus judgment.
5. **b.** Same — population and offsets, not a fit.
6. **Echo.** Checked that implied next-12 sat sensibly against the trailing
   average given the struck noise, and that the decline profile matched the
   offsets'. Committed.

### A history with a break in it — re-initialize

*A producing well, ~7,500-ft lateral, four years on.*

1. **Evidence.** Two and a half years of clean decline, then three months
   of near-zero — the operator completed offsets one section over — then a
   recovery that stabilized about 30% below where the old trend projects.
   The dip-and-recovery is struck; the question is what the stabilized
   level means.
2. **Trust.** Split by segment. The pre-hit history is clean and long —
   trustworthy — but it describes a well that no longer exists. Six months
   of post-hit data parallel the old trend at the lower level: the well
   took permanent damage and settled into a new regime. Fit the regime
   that persists.
3. **qi/anchor.** From the post-hit trendline — the new level, anchored at
   the forecast start. Not the old curve's projection, and not an average
   that smears the trough into the level.
4. **Di.** The post-hit months are few but parallel to the pre-hit slope,
   and the pre-hit history is this same rock at the same maturity — so the
   pre-hit trend sets the slope, applied to the new level.
5. **b.** Unchanged by the hit: population and mature offsets, same as
   ever.
6. **Echo.** Implied next-12 came in well under trailing-12 — correct,
   since trailing-12 includes seven pre-hit months at the higher level.
   Verified next-12 against an annualized read of the post-hit months
   instead, and the decline profile against offsets. Committed.

### Barely any history — the analog set carries it

*A producing well, ~10,000-ft lateral, one month on.*

1. **Evidence.** One reported month — likely partial, not knowably the
   peak. It says the well is online and roughly at what scale; it cannot
   say level, slope, or shape.
2. **Trust.** Near zero on shape, a sliver on level. This is the
   population end of the continuum: the analog method runs in full.
3. **qi/anchor.** Fourteen analogs inside 12 miles — same formation,
   first production within five years, comparable laterals and proppant
   per foot. Peak-aligned and averaged. The subject's one month sat
   modestly below what the analogs' first months typically did, so the
   level came down proportionally. Anchored at the expected peak — month
   two — with qi read from the scaled curve there. No uptime factor: the
   well is brand new; assume it runs.
4. **Di.** The aligned average's early decline.
5. **b.** The priors band, checked against the flattening of the set's
   oldest members.
6. **Echo.** No trailing-12 exists to compare against, so EUR/ft against
   the analog family was the sanity anchor — it landed inside the
   family's range, and the terminal switch landed at a believable age.
   Committed, with the rationale naming the set and the scale-down.
