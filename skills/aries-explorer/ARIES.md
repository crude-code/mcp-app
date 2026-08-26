# ARIES Database Reference

ARIES (by Halliburton/Landmark) is the industry-standard reserves and economics software for oil & gas. Databases are stored as Microsoft Access `.accdb` (or older `.mdb`) files — a binary format. Read them with the bundled `aries_triage.py`, which resolves a reader backend itself (mdb-tools binaries when present, else the pure-Python `access_parser` package); see the skill instructions.

## Database Structure

Three tiers: **Data Source** (ODBC connection to database) → **DBS** (database system) → **Project** (property list).

Three table types:
- **System tables** — Housekeeping (ARSYSTBL, ARLOCK, PROJECT, etc.). Data-source level.
- **Economic instruction tables** — Scenarios, settings, lookups. Mix of data-source and table-set level.
- **Data tables** — Raw data (wells, production, economics). Table-set level. All have aliases and reference the Master table (AC_PROPERTY) via `PROPNUM`.

`ARSYSTBL` is the system table that manages table sets — lists all tables, their aliases, and locations.

## Complete Table Reference

### Data Tables (Table-Set Level)
| Table | Alias | Description |
|-------|-------|-------------|
| AC_DAILY | DP | Daily production data |
| AC_DETAIL | DT | Computed annual cashflows (by time frame) |
| AC_ECONOMIC | EC | Economic assumptions by section |
| AC_ECOSUM | EZ | Economic summary results |
| AC_MONTHLY | EM | Computed monthly cashflows |
| AC_NOTE | NOTE | Property notes |
| AC_ONELINE | OL | Single-row run results summary |
| AC_OWNER | OW | Ownership records |
| AC_PRODUCT | MP | Monthly production history |
| AC_PROPERTY | M | Well/property master (parent table) |
| AC_PZFCST | PZ | P/Z analysis forecasts (gas material balance) |
| AC_RATIO | RATIO | Production ratios |
| AC_RESERVES | RESV | SEC reserves booking data |
| AC_TEST | WT | Well test data |
| AC_WELL | WD | Reservoir/wellbore engineering data |
| ARCOMMENTS | GRFCMT | Comments |
| ARI_BULKDATA | ARIBULK | Modeler bulk data |

### Economic Instruction Tables (Table-Set Level)
| Table | Alias | Description |
|-------|-------|-------------|
| AC_SCENARIO | SCENARIO | Scenario definitions (qualifier hierarchies) |
| AC_SETUP | SETUP | Project-level settings |
| AC_SETUPDATA | SETDATA | Settings data (report frames, capital templates, tax) |
| AR_SIDEFILE | ESF | Side files (external economic data) |
| ARENDDATE | ENDDATE | End date definitions |
| ARLOOKUP | LOOKUP | Lookup tables (type curves, prices, tax schedules) |
| BATCHMACROS | BM | Batch macro definitions |
| ECOPHASE | EP | Phase definitions |
| ECOSTRM | ES | Economic output stream definitions |

### System Tables (Data-Source Level)
| Table | Description |
|-------|-------------|
| ARCURVE | Curve definitions for plotting |
| ARFILTER/ARFILTERS | Saved filters |
| ARGRAPH/ARGRAPHCURVE | Graph instructions |
| ARIESSCHEMAVERSION | Database schema version |
| ARLOCK | Record locking |
| ARSTREAM | Stream name → table column mapping |
| ARSYSCOL | System column definitions |
| ARSYSTBL | Master table registry (manages table sets) |
| ARUNITS/ARUNITTYPES | Unit definitions |
| DBSLIST | DBS list |
| GROUPLIST/GROUPS/GROUPTABLE | Property groupings |
| PROJECT/PROJLIST | Project metadata |
| TBLSETS | Table set definitions |

### RMS Tables (Reserves Management, Table-Set Level)
| Table | Alias | Description |
|-------|-------|-------------|
| BKMEMO | RMSBKMEMO | Booking memos |
| RESERVE | RMSRESERVES | Reserves data |
| RMSPROD | RMSBKPROD | Booked production |
| RMSREP | RMSREPORT | RMS reports |
| RESCAT | RMSRESCAT | Reserve categories |
| RMSSCEN | RMSSCENARIO | RMS scenarios |

## Core Tables (Detail)

### AC_PROPERTY — Well/Property Master
One row per property (well, lease, or location). **Column names are
shop-configurable** — real databases vary: `RSV_CAT` for `RESCAT` (with
prefixed values like `1PDP`), `LATERAL_LENGTH` for `LATERAL`, `LEASE` +
`WELLNUM` instead of `CASE_NAME`, a bare 14-digit `API` instead of `API_10`,
and often an explicit `WI` column beside `NRI`. The bundled scripts cover
these variants; when a field looks missing, check for a renamed column
before concluding it's absent. Key fields (canonical names):
- `PROPNUM` — Primary key (ARIES internal ID, e.g. `0O90QATR5O`)
- `DBSKEY` — DBS identifier (must be preserved during transport)
- `CASE_NAME` — Property display name (e.g. `HV LOC 12-01H`)
- `RESCAT` — Reserve category: `PDP`, `PDNP`, `PUD`, `4LOC`, etc.
- `LEASE`, `WELL_ID`, `FIELD`, `OPERATOR`, `RESERVOIR`, `STATE`, `COUNTY`
- `API_10`, `API` — Well API numbers
- `STATUS` — Well status
- `MAJOR` — Primary product: `OIL` or `GAS`
- `LATERAL` — Lateral length (ft)
- `NRI` — Net revenue interest (decimal)
- `PROD_START` — Production start date (MM/YYYY)
- `GEOZONE` — Geographic zone code (used for type curve lookup)
- `DATE_COMP`, `FIRST_PROD` — Completion and first production dates
- `PRIOR_OIL`, `PRIOR_GAS`, `PRIOR_WTR` — Cumulative production prior to forecast
- `LIQ_GRAV`, `GAS_GRAV`, `TEMP_BH`, `DEPTH`, `UPR_PERF`, `LWR_PERF` — Well data

### AC_ECONOMIC — Economics by Section
Per-property economic assumptions. Each row is one line item:
- `PROPNUM` — Links to AC_PROPERTY
- `SECTION` — Section number (see below)
- `SEQUENCE` — Line order within section
- `QUALIFIER` — Scenario name (usually `BASE`)
- `KEYWORD` — What this line defines
- `EXPRESSION` — The value/formula

**Section numbers:**
| Section | Name | Common Keywords |
|---------|------|-----------------|
| 1 | Miscellaneous | `TAXP` (tax plan), `FILEXL` (Excel link), `BOOK` (book economics), `RISK` |
| 2 | Input Settings | `SHRINK` (gas shrinkage), `OPNET` (operator net %), `ELOSS` (econ limit), `MAJOR`, `LIFE`, `BTU` |
| 3 | (Reserved) | |
| 4 | Production & Forecasts | `START`, `LOOKUP`, `OIL`, `GAS`, `WTR`, `CUMS`, `LOAD`, `LOADXL` |
| 5 | Prices | `PRI/OIL`, `PRI/GAS`, `PAJ/OIL`, `PAJ/GAS` (differentials), `LIST` (price series) |
| 6 | Expenses | `OPC/T` (fixed LOE $/mo), `OPC/OIL`, `OPC/GAS` (variable LOE), `STX/OIL`, `STX/GAS` (sev tax), `ATX` (ad valorem), `OH/T` (overhead), `GA/T` (G&A) |
| 7 | Ownership | `NET` (NRI), `WI` (working interest), `LSE/WI`, `ROY/OIL`, `ROY/GAS`, `ORR/OIL`, `ORR/GAS`, `OWN/WI`, `LSE/NPI` |
| 8 | Investments | `CAPITAL` (investment name), tangible/intangible amounts, timing |
| 9 | Overlays | `LOAD` (replace forecast with actuals), stream arithmetic (`S/n`), `LIST` overlays |

### AC_ECONOMIC Expression Format (8-Word Line)
Each non-shortcut economic line has 8 positional "words":
```
KEYWORD  InitialValue  EndingValue  Units  ForecastLimit  ForecastMethod  Method  MethodValue
```

Examples:
- `PRI/OIL 58.50 X $/B TO LIFE PC 0` — Oil price $58.50/bbl, flat to life, 0% escalation
- `PRI/GAS 4.00 X $/M TO LIFE PC 0` — Gas price $4.00/MCF, flat to life
- `PAJ/GAS -0.50 X $/M TO LIFE PC 0` — Gas price differential -$0.50/MCF
- `OPC/T 5000 X $/M TO LIFE PC 0` — Fixed LOE $5,000/month
- `STX/OIL 7.5 X % TO LIFE PC 0` — Oil severance tax 7.5%
- `ROY/OIL 0.25 X FRAC TO LIFE` — Oil royalty 25%

Shortcut lines (fewer than 8 words): `NET`, `LSE`, `OWN`, `START`, `FILE` — cannot be used in Common Lines or Default Lines.

Continuation lines use `"` (ditto) as keyword to continue the previous keyword.

### AC_ECONOMIC Special Keywords
- **`@M.fieldname`** — Reference AC_PROPERTY field (e.g. `@M.NRI`, `@M.LATERAL`, `@M.PROD_START`)
- **`LOOKUP tablename @M.key`** — Lookup from ARLOOKUP keyed by property field
- **`LOAD source.field TARGET begdate enddate #`** — Replace forecast with table data (e.g. `LOAD MP.OIL OIL 1/2014 06/2014 #`)
- **`LOADXL range KEYWORD date units`** — Load from Excel (requires `FILEXL` in Misc section)
- **`FILE filename`** — Include external economic data file
- **`LIST date val1 val2 val3 ... #`** — Series of values starting at date
- **Common Lines** — Global defaults used IF the case doesn't contain that keyword (appear blue in editor)
- **Default Lines** — Fill missing words at end of a line (appear red in editor)

### AC_PRODUCT — Historical Production
Monthly production history per property:
- `PROPNUM`, `P_DATE`, `OIL`, `GAS`, `WATER`, `DAYSON`
- Empty for undeveloped locations

### AC_DAILY — Daily Production
- `PROPNUM`, `P_DATE`, `OIL`, `GAS`, `WATER`

### AC_FCST — Decline Forecast Segments
Explicit Arps decline segments (when not using LOOKUP):
- `PROPNUM`, `PHASE`, `QUALIFIER`, `SEGMENT`, `STARTDATE`, `ENDDATE`
- `PRODRATE`, `UOM`, `DECLINERATE` (effective annual %), `DECLINETYPE`
  (`HyperRT`/`ExpRT`/`LogRT`), `BFACTOR`, `NOMINALRATE` (nominal per month)
- `STARTCUM`, `ENDRATE`, `REMRESV`, `DURATION` (months), `ULTIMATE`, `SEGRESV`
- Empty when forecasts come from type curve lookups
- **Qualifier matters**: AC_FCST rows can be stale fits from old scenarios
  (e.g. 2022 qualifiers in a 2026 database) while the current forecast lives
  only in section-4 rate lines. Match `QUALIFIER` before treating segments
  as the active forecast. `PHASE` includes ratio phases (`GAS/OIL`).

### ARLOOKUP — Lookup Tables (Type Curves, Prices, Tax)
Global lookup tables referenced by `LOOKUP` keyword in AC_ECONOMIC:
- `Name` — Table name (e.g. `TC_PROD`, `GASPRICE`, `OILPRICE`, `SEV`)
- `LineType` — 0=template (forecast shape), 1=header (column defs), 3=data rows
- `Var0..Var30` — Column values

**Type curve example (TC_PROD):**
```
LineType=0 (template):  GAS, @M.LATERAL*1.0, X, M/D, 1, MO, FLAT, 0
                        ", ?, X, M/D, 6.0, EXP, ?, ?
                        ", X, X, M/D, 50, IYR, EXP, 6.0
LineType=1 (header):    GEOZONE, Q1, B, DI
LineType=3 (data):      HV, @M.LATERAL*3.6, B/0.50, 46.0
                        MB, @M.LATERAL*3.0, B/0.50, 39.0
```
Meaning: for Haynesville (HV) wells, initial gas rate = LATERAL × 3.6 MCF/day, b-factor = 0.50, initial decline = 46% annual.

**Price lookup example (GASPRICE):**
- Keyed by AREA code (e.g. ETXTYL = East TX Tyler, STXHSTN = South TX Houston)
- Year-by-year prices with escalation schedule

### AC_ONELINE — Run Results Summary
One row per property with computed economics results. Column names map to stream codes:
- `C370` = cum oil, `C371` = cum gas, `M1` = life (years), `E1` = economic limit rate
- `P1`/`B1` = PV values at various discount rates

### AC_MONTHLY / AC_DETAIL — Computed Cashflows
Monthly (AC_MONTHLY) and annual (AC_DETAIL) cashflow output. Columns are S-codes mapping to stream numbers (see Stream Reference below).

### AC_SCENARIO — Scenario Definitions
Defines named scenarios and qualifier hierarchies. A scenario specifies which QUALIFIER to use for each section. Hierarchy means ARIES tries qualifiers in order — first match wins.

### AC_OWNER — Ownership Records
Per-property ownership interests by phase and date.

### AC_WELL — Reservoir/Wellbore Data
Engineering data: area, net pay, porosity, water saturation, pressures, depths, flow data, AOF.

## Production Units Reference

### Rate Units (Major Phase)
| Oil | Gas | Other | Meaning |
|-----|-----|-------|---------|
| B/D | M/D | U/D | per day |
| B/M | M/M | U/M | per month |
| B/Y | M/Y | U/Y | per year |
| MB/D | MM/D | | thousands per day |
| MB/M | MM/M | | thousands per month |
| MB/Y | MM/Y | | thousands per year |

### Ratio Units (Subordinate Phase)
| Oil Sub | Gas Sub | Meaning |
|---------|---------|---------|
| B/M (bbl/MCF) | M/B (MCF/bbl) | per unit of other phase |
| B/MM | MM/B | per M units |
| B/B | M/M | same unit |

### Forecast Limit Units
| Unit | Meaning |
|------|---------|
| YR/YRS | Cumulative years after start date |
| MO/MOS | Cumulative months after start date |
| IYR | Incremental years after previous line |
| IMO | Incremental months after previous line |
| AD | Absolute date (e.g. `7/85` or `1985.5`) |
| LINE | Project line number |
| LIFE | Life of project |
| EXP | Stop at specified decline % |
| BBL/MB/MMB | Oil volume limit |
| MCF/MMF/BCF | Gas volume limit |
| BPD | Tie to oil forecast rate |
| MPD | Tie to gas forecast rate |
| UCR/UGR | Tie to ultimate volumetrics |
| IMU | Incremental thousands of units |

### Forecast Methods
| Method | Meaning |
|--------|---------|
| FLAT | Constant rate (no decline) |
| EXP | Exponential decline |
| HYP | Hyperbolic decline (requires b-factor) |
| HARM | Harmonic decline (b=1) |
| B/x | Hyperbolic with b-factor x (e.g. `B/0.9000`); the method value is the decline |

### Decline conventions (empirically pinned — do not guess these)

Verified against a real database's own numbers (AC_FCST stores both the
quoted and the nominal rate: 78/78 segments exact to 1e-9; per-well EURs
reproduced against the shop's oneliner to ≤0.022% on both streams, 20 wells):

- **A quoted decline `D` is the EFFECTIVE ANNUAL decline** — the secant
  `1 − q(t+1yr)/q(t)` evaluated on the curve itself.
- **Nominal monthly rate**: `a = ((1−D)^(−b) − 1) / (12·b)`, or
  `a = −ln(1−D)/12` when b=0. (AC_FCST's `NOMINALRATE` column is exactly
  this per-month value; `DECLINERATE` is D in percent.)
- **Rate propagation**: `q(t) = qi·(1 + b·a·t)^(−1/b)` with **t in months**
  and rates in units/month (`B/M`, `M/M`). Exponential when b=0.
- **A rate-line limit `N EXP`** (e.g. `7.000000 EXP`) means: run this
  segment until the local effective annual decline shallows to N%, then the
  next (ditto) segment takes over — typically `X <floor> <units> X YRS EXP N`,
  an exponential at N% effective annual down to the ending-rate floor.
- **Segment volumes** integrate the continuous curve (ARIES's internal daily
  granularity differs by well under 1% on segment volumes and nets to ~0.01%
  at EUR level).
- **`CUMS` words are thousands**: oil MB, gas MMCF (order: oil gas cnd? ngl?
  ? water), cumulative through the forecast `START`.
- **What a §4 integral does NOT reproduce**: the economic-limit cutoff.
  `ELOSS OPINC` (a Common Line) ends each well's life where operating income
  dies — on the verified database that truncation removes ~3–6% of oil EUR
  and far more of late-life gas tails versus integrating to the rate floor.
  Reproducing life requires the full economics (prices, costs, ownership);
  treat life as the economics engine's own policy, never the curve's.

### Price/Cost Units
| Unit | Meaning |
|------|---------|
| $/B | Dollars per barrel (oil) |
| $/M | Dollars per MCF (gas) OR dollars per month (expenses) |
| % | Percentage (tax rates) |
| FRAC | Fraction (interests) |

## Escalation Units

### Compounded (PC family)
| Unit | Meaning |
|------|---------|
| PC | Monthly compounding (~1/12 annual rate per month) |
| PC/M | Same as PC |
| PC/Q | Quarterly compounding (~1/4 annual rate per quarter) |
| PC/S | Semi-annual compounding |
| PC/Y | Annual step — holds flat for 1 year, then full annual amount |
| PC/B | Biannual compounding |

### Dollar Escalation ($E family)
| Unit | Meaning |
|------|---------|
| $E | Monthly — adds 1/12 of $/unit annual value each month |
| $E/Q | Quarterly — adds 1/4 each quarter |
| $E/Y | Annual step — adds full amount yearly |

### Simple Escalation (PE family)
| Unit | Meaning |
|------|---------|
| PE | Monthly simple escalation (1/12 annual, not compounded) |
| PE/Y | Annual step — holds flat, then full escalation |

## Reversion Units (Interest Reversions)
| Unit | Meaning |
|------|---------|
| M$G | When stream 892 (appraised revenue after sev) cumulates to specified M$ |
| M$N | When stream 1069 (BTAX net) cumulates to specified M$ |
| M$(i) | When stream i cumulates to specified M$ |
| IM$(i) | Incremental — since last line scheduling this stream |
| S(i) | When stream i cumulates to specified number |

Common reversion streams: 746 (gross rev less royalties/sev/adval/opex/NPI), 747 (same but before NPI), 1069 (net rev less sev/adval/opex).

## Depreciation Methods (Capital Recovery)
| Method | Description |
|--------|-------------|
| ACR | Original MACRS (1981-1986, obsolete) |
| ACR2 | Modified MACRS (1987+, standard) |
| ACR3 | 30% first-year bonus (9/2001-12/2004) |
| ACR4 | 50% bonus (various date windows) |
| ACR5 | 100% first-year write-off (9/2010-12/2011) |
| ACR6 | 50% extended bonus (2013) |
| SL | Straight Line (based on guideline life years) |
| UOP | Units of Production (based on production volumes) |
| DB | Declining Balance (fraction per year) |
| MDB | Multiple Declining Balance |
| SYD | Sum of Year's Digits |
| BOE | Barrels of Oil Equivalent |
| OPT | Greater of DB or SL |
| OPT2 | Greater of MDB or SYD |
| OPTY | OPT2 with specified life |
| MANL | Manual (user-defined write-off fractions) |

Investment Recovery line columns: Investment Name, Depreciation Method, Start Code (`0`=when invested, `X`=when production begins, `MM/YYYY`=absolute), Depreciation Factor (years or fraction), % Intangible to Capitalize (0=expense all; negative=major company treatment).

## Stream Arithmetic
Used in economics sections to define custom calculations between streams.

**Format:** `S/answer constant_or_stream X units TO LIFE operation second_stream`

**Operations:** `PLUS`, `MINUS`, `MUL`, `DIV`, `MAX`, `MIN`

**Example:** `S/195 20.00 X FRAC TO LIFE PLUS 195` — adds $20 to oil price stream 195.

Rules:
- Calculations are monthly — only use monthly streams
- Source stream numbers should be ≤ answer stream number (ARIES calculates in numerical order)
- Upper/lower limits: positive = upper limit, negative absolute value = lower limit, X = no limit
- Can be placed in Prices, Expenses, or Overlay section
- Overlay section stream arithmetic causes recalculation

## Stream Number Reference (1500 Streams)

### Stream Ranges
| Range | Category |
|-------|----------|
| 1–30 | Special streams (S/1 through S/30) — user-defined |
| 31–344 | Monthly rate streams (input rates, interests, taxes) |
| 345–749 | Monthly gross values (volumes, revenue, expenses, investments) |
| 750–789 | Working interest values |
| 790–1099 | Appraised (net) values |
| 1100–1349 | After-tax, present worth, book values |
| 1350–1500 | Reserves, depreciation detail, reserved |

### Key Rate Streams (31–344)
| Stream | Keyword | Description |
|--------|---------|-------------|
| 40 | STX/OIL | Oil severance tax rate |
| 41 | STX/GAS | Gas severance tax rate |
| 42 | STX/CND | Condensate severance tax rate |
| 55 | ATX | Ad valorem tax rate (% revenue) |
| 95 | LSE/WI | Lease working interest |
| 100 | ROY/OIL | Lease oil royalty |
| 101 | ROY/GAS | Lease gas royalty |
| 115 | ORR/OIL | Overriding interest oil |
| 123 | LSE/NPI | Net profits interest |
| 124 | OWN/WI | Owned working interest |
| 125 | OWN/OIL | Owned royalty interest oil |
| 195 | PRI/OIL | Oil price ($/BBL) |
| 196 | PRI/GAS | Gas price ($/MCF) |
| 197 | PRI/CND | Condensate price |
| 225 | OH/OPC | Overhead rate (% opex) |
| 226 | OH/CAP | Overhead rate (% capital) |
| 227 | OH/W | Overhead rate ($/well/mo) |
| 265 | OPC/T | Fixed operating cost ($/mo) |
| 269 | OPC/OIL | Variable opex oil ($/BBL) |
| 270 | OPC/GAS | Variable opex gas ($/MCF) |
| 344 | MONTHS | Time frame size (months) |

### Key Gross Monthly Streams (345–749)
| Stream | Keyword | Description |
|--------|---------|-------------|
| 349 | DAYS | Number of days produced |
| 350 | PMOS | Number of months produced |
| 351 | GCAP | Gross tangible investment |
| 352 | | Gross intangible investment |
| 355 | | Gross total investment w/o risk |
| 370 | OIL | Gross input schedule for oil |
| 371 | GAS | Gross input schedule for gas |
| 372 | CND | Gross condensate |
| 374 | NGL | Gross NGL |
| 376 | WTR | Gross water |
| 391–405 | | Gross sold volumes (by phase) |
| 427–441 | | Gross revenue by phase |
| 442 | | Gross total revenue from products |
| 458–472 | | Gross severance tax by phase |
| 473 | | Total gross severance tax |
| 746 | | Gross rev less royalties/sev/adval/opex/NPI |
| 747 | | Same as 746 but before NPI |

### Key Working Interest Streams (750–789)
| Stream | Description |
|--------|-------------|
| 768 | W.I. total revenue (resource) |
| 770 | W.I. total revenue after severance |
| 771 | W.I. total operating & ad valorem |

### Key Appraised (Net) Streams (790–1099)
| Stream | Keyword | Description |
|--------|---------|-------------|
| 815 | | Appraised sold volume for oil (net oil) |
| 816 | | Appraised sold volume for gas (net gas) |
| 846 | | Appraised revenue for oil |
| 847 | | Appraised revenue for gas |
| 861 | | Appraised total revenue from products |
| 887 | | Appraised total severance |
| 892 | | Appraised total revenue after severance |
| 912 | | Total appraised effective crown royalty |
| 930 | | Total appraised mineral tax |
| 947 | | Total appraised Indian royalty |
| 1001 | | Appraised operating cost (fixed) |
| 1005 | | Appraised operating cost (variable oil) |
| 1006 | | Appraised operating cost (variable gas) |
| 1055 | | Appraised total operating cost |
| 1069 | | Appraised BTAX cash flow (net revenue less sev/adval/opex) |

### Key After-Tax / PW Streams (1100–1349)
| Stream | Description |
|--------|-------------|
| 1183 | Appraised equity capital investments |
| 1184 | Appraised borrowed investments |
| 1185 | Appraised risk investment |
| 1186 | Appraised total investment w/o risk |
| 1208 | Appraised total tangible depreciation |
| 1235 | Appraised total intangible depreciation |
| 1236 | Appraised expensed investment |
| 1257 | Appraised cost depletion |
| 1263 | Depletion taken |
| 1264 | Taxable income |
| 1265 | Federal tax |
| 1268 | State/province tax |
| 1269 | Total tax paid |
| 1270 | AFIT net before financing |
| 1301 | Principal payments |
| 1302 | Interest paid |
| 1305 | Salvage |
| 1306 | Abandonment |
| 1307 | AFIT after financing payments |
| 1314 | P.W. of BFIT after financing |
| 1315 | P.W. of AFIT after financing |
| 1316 | P.W. of investments |
| 1317 | P.W. of BFIT net |
| 1318 | P.W. of AFIT net |

## Time Frame Syntax
Time frames control report periods and are defined with repeater notation:
- `12*1` — 12 monthly frames (1 month each)
- `4*3` — 4 quarterly frames (3 months each)
- `99*12` — 99 annual frames (12 months each)
- Combined: `12*1,4*3,98*12` — monthly first year, quarterly second year, then annual
- Leading comma in Simple mode: `,12,99*12`
- Max 128 time frames, max 100 years total from Base Date
- ARIES uses 30.4 as average days per month

## Variable Rate Streams
30 available (S/1 through S/30). Defined in AC_SETUPDATA with:
- Stream number (1–30)
- Start date (MM/YYYY)
- Monthly values with repeater: `12*.34 24*.4 1164*.45` (34% for 12 months, 40% for 24, then 45%)

## Reading the database

`aries_triage.py` (bundled) is the one entry point — it inventories every
table and dumps the load-bearing ones to CSV under `_aries/tables/`, so you
read structured text and never open the binary by hand. If you do need an
ad-hoc pull beyond the dumps, use whichever backend triage reported:

```bash
# mdb-tools backend
mdb-tables -1 file.accdb                       # list all tables
mdb-export file.accdb AC_PROPERTY > property.csv

# access_parser backend (pure Python)
python3 -c "
from access_parser import AccessParser
db = AccessParser('file.accdb')
t = db.parse_table('AC_PROPERTY')              # dict of column -> values
print(list(t))"
```

## Common Parsing Patterns

- **`@M.fieldname`** — Reference to AC_PROPERTY field (e.g. `@M.NRI`, `@M.LATERAL`, `@M.PROD_START`, `@M.GEOZONE`)
- **`LOOKUP tablename @M.key`** — Type curve or price lookup keyed by property field
- **`X $/M TO LIFE PC 0`** — Price/cost expression: value × $/MCF, to end of life, 0% price change
- **`X % TO LIFE PC 0`** — Tax/deduction: value as %, to end of life
- **`FRAC TO LIFE`** — Interest as fraction
- **`"`** — Continuation/ditto line (continues previous keyword)
- **Reserve categories:** PDP (producing), PDNP (non-producing), PUD (proved undeveloped), 2P/3P (probable/possible), 4LOC/5LOC (locations)
- **Phase codes:** OIL=370, GAS=371, CND(condensate)=372, OWG(casinghead gas)=373, NGL=374, WTR=376
- **NET shortcut line** — `NET <WI> <NRI oil> [<NRI gas> <NRI other>] <units> <tail>`: word 0 is the **working interest**, word 1 the NRI; a `%` unit means every value is a percentage (÷100), `FRAC` means fractions as-is. A tail beyond a plain escalation pair (`PC 0`) is an interest **schedule or reversion trigger** (e.g. `3652.8 M$/747` — revert when stream 747 cumulates to 3,652.8 M$; see Reversion Units above)
- **`DBSKEY` and `PROPNUM`** — Must always be preserved when transporting data between databases
- **Sliding scale royalties** — Use FEDO/A/B/R lines in AC_SETUPDATA with volume breakpoints and royalty rates
