# OpenTag matcher internals (v2.1)

This document describes the scoring algorithm used by the OpenTag Cleanup tool to
match Spoolman filaments against the OpenPrintTag dataset. It is intended for users
who want to understand why a match scored as it did, and for developers maintaining
or extending the scorer.

For the UI flow and apply semantics see [opentag-cleanup.md](opentag-cleanup.md).

## Overview

The v2 scorer (`backend/app/core/opentag_match.py`) uses **structured token
decomposition** on both sides before scoring. Names are broken into four bags
(material family, finish ids, modifiers, color tokens), and each bag scores
independently. The final score is a weighted sum capped at 1.0.

```
score = material×0.15 + brand×0.15 + color-multiset×0.40 + modifier-jaccard×0.15
      + finish×(±0.10) + hex×0.05 + string-similarity×(0–0.05)
```

## Mined lexicons

At dataset load time the bridge mines the full OpenPrintTag dataset
(`backend/app/core/opentag_lexicon.py`) to build two vocabulary sets:

- **Modifiers** — product-line and texture words found across many brands:
  `silk`, `matte`, `glossy`, `gradient`, `dual`, `shiny`, `rapid`, `twin`,
  `marble`, `wood`, …
  Also includes `COMPOSITE_DESCRIPTOR_SEED` tokens unconditionally (see below).
- **Colors** — color name tokens found across many materials plus an
  explicit seed (`BASE_COLORS`): `red`, `blue`, `green`, `silver`, `gold`,
  `turquoise`, `fuchsia`, `emerald`, `graphite`, `rosa`, `midnight`, …

Both sets are computed from **n-grams** (uni/bi/tri) of the residual tokens that
remain after vendor, material-family, and finish-tag words are removed. A bigram
phrase is promoted when its Pointwise Mutual Information (lift) exceeds a threshold —
this is how phrases like "dual color" or "silk shiny" enter the modifier list.

### N-gram separator rule

N-grams **do not cross** `&` or `/` in a filament name. "Silver & Shiny Blue"
produces tokens `["silver", "shiny", "blue"]` — "silver shiny" is not a bigram
candidate because the `&` acts as a hard boundary. This correctly handles
multi-color names where each segment describes one distinct color.

### Stop-list

Technical material codes are excluded from both lexicons to avoid polluting the
modifier vocabulary: `gf10`, `gf15`, `gf25`, `gfN` (glass-fiber percentages),
`rfid`, `esd`, `htpla`, `rpla`, `rpetg`, `paht`.

### Color-leak prevention

Some real color names appear in too few brands to reach the color mining threshold
(e.g. turquoise, fuchsia, emerald). These are added to a hard-coded `BASE_COLORS`
seed and are **always** classified as colors — never as modifiers. The seed is
subtracted from the mined modifier set on every rebuild.

### Fill-composite descriptors (v2.1)

OpenPrintTag has many "fill" composite materials (woodfill, steelfill, copperfill,
bronzefill, …) that are distinctive product-line identifiers but do not appear in
enough brands to be promoted by the frequency-based miner alone. A hand-curated
`COMPOSITE_DESCRIPTOR_SEED` is **unconditionally** unioned into the modifier lexicon
so these tokens always score correctly:

> `woodfill`, `steelfill`, `stonefill`, `copperfill`, `bronzefill`, `corkfill`,
> `glowfill`, `metalfill`, `marblefill`, `brassfill`, `bamboofill`, `granitfill`

Additionally, `decompose_name` has a `len >= 6 and endswith("fill")` fallback that
captures novel tokens not yet in the seed (e.g. "rockfill", "glassfill").

**Effect.** "PLA Woodfill" decomposes to `modifiers={"woodfill"}`. The `colorfabb-woodfill`
OPT entry also decomposes to `modifiers={"woodfill"}` → modifier Jaccard = 1.0 (+0.15).
`colorfabb-steelfill` → `modifiers={"steelfill"}` → Jaccard = 0.0. Woodfill ranks #1.

### Cache persistence

The mined lexicons are saved alongside the materials in `DATA_DIR/opentag_cache.json`
under a `"lexicon"` key and a `"lexicon_version"` integer. On warm startup the bridge
reads from the cache file without any network call. If `lexicon_version` in the file
does not match the current `LEXICON_VERSION` constant in `opentag_lexicon.py` (e.g.
after a bridge upgrade with a scoring change), the lexicons are re-mined in-process
from the cached materials — again without any network call — and the file is updated.

The current version is **`LEXICON_VERSION = 3`** (v2.1: COMPOSITE_DESCRIPTOR_SEED added).

## Decomposition (`decompose_name`)

Both the Spoolman filament name and the OpenTag material name are decomposed into the
same structure:

```python
class ParsedName(NamedTuple):
    material_family: str            # "pla", "petg", "tpu", "" …
    finish_ids: frozenset[int]      # OpenPrintTag finish tag IDs
    modifiers: frozenset[str]       # product-line / texture tokens
    colors: Counter                 # color token → count (order-independent)
```

Decomposition steps (using the mined n-gram index, longest match first):

1. Normalize to lowercase, unicode-collapse, strip punctuation except `&` and `/`
2. Insert `__SEP__` at `&` and `/` (prevents n-gram crossing)
3. Remove vendor tokens and material-family tokens
4. Slide a tri→bi→uni window over residual tokens; claim tokens into the
   modifier or color bags based on the mined lexicon and `BASE_COLORS`; unclaimed
   tokens fall through
5. Apply `COLOR_SYNONYMS` (true synonym map) to every color token

## Scoring components

### Material match (×0.15)

Normalised polymer families must match exactly (`"pla" == "pla"`). PLA and PLA+ are
the same family by spec; grades live in the modifier bag. A mismatch zeroes this
component; a match scores 0.15. If either side has no material, the component is
neutral (0.075).

### Brand/vendor match (×0.15)

After `normalize_vendor` (lowercase, strip hyphens/suffixes), exact match = 0.15,
partial containment (e.g. "prusa" in "prusament") = 0.075, no match = 0.0.
Vendor aliases from the `opentag_vendor_aliases` setting are applied before scoring.

### Color multiset (×0.40)

Order-independent, count-aware Jaccard over the two `Counter` color bags:

```
matched = sum(min(a[c], b[c]) for c in union)
score   = matched / (matched + extra_a + extra_b)
```

When either side has no color tokens (vendor has no color in name) the component
returns a neutral 0.5 so a zero-color-token OpenTag entry does not unfairly
dominate other matches.

**Why 0.40?** Color is the dominant discriminator among same-brand same-material
candidates. A silk PLA in "Silver" must outscore one in "Blue" even when both match
on every other axis.

**AMOLEN worked example.** Spoolman name: "Silk Shiny Gradient Silver & Shiny Blue":

- colors: `Counter({"silver": 1, "blue": 1})`
- modifiers: `{"silk", "shiny", "gradient"}`

OpenTag target "Silk Shiny Gradient Silver & Shiny Blue":

- colors: `Counter({"silver": 1, "blue": 1})` → multiset score 1.0
- modifiers: `{"silk", "shiny", "gradient"}` → Jaccard 1.0

Wrong candidate "Dual Color Blue & Fuchsia":

- colors: `Counter({"blue": 1, "fuchsia": 1})` → multiset score 0.5 (only "blue" matches)
- modifiers: `{"dual"}` → Jaccard 0 (no modifier overlap with silk/shiny/gradient)

The correct entry scores ≥ 0.10 above the wrong one in every tested case.

### Modifier Jaccard (×0.15)

Standard Jaccard of the frozenset modifier bags. Neutral 0.5 when both sides are
empty (no modifier tokens on either side is not a signal for or against).

### Finish tag overlap (±0.10)

Finish IDs are the numeric OpenPrintTag tag IDs for surface-texture terms
(`silk`, `matte`, `glossy`, `glitter`, …). The component uses a signed scale:

| Condition | Score |
|---|---|
| Both sides empty | +0.05 (weak agreement) |
| Perfect match | +0.10 |
| Partial overlap | Jaccard × 0.10 |
| One side has finishes, other is empty | 0.0 |
| Completely disjoint non-empty sets | −0.07 |
| Strong mismatch (e.g. silk vs matte) | −0.10 |

### Hex color proximity (×0.05)

When the Spoolman filament carries a `color_hex` and the OpenTag material has a hex,
RGB distance is computed. Identical hex → 0.05; maximum distance → 0.0.

### Full-string similarity tie-breaker (+0–0.05)

`SequenceMatcher(Spoolman_name, OpenTag_name).ratio() × 0.05` is added as a
tiebreaker for candidates that score identically on all other components.

## COLOR_SYNONYMS (v2 change from v1)

In v1, `DEFAULT_COLOR_KEYWORDS` mapped marketing color names to base colors
(`"galaxy" → "black"`, `"silver" → "grey"`, `"cool" → "grey"`, …). This collapsed
real color distinctions — "Silver" and "Blue" both mapped to different bases but the
multiset couldn't distinguish them after the collapse.

In v2 the map is **synonyms-only** — genuine linguistic equivalences only:

| Input | Mapped to |
|---|---|
| `gray` | `grey` |
| `violet` | `purple` |
| `magenta` | `pink` |
| `transparent` | `clear` |
| `navy` | `blue` |

Marketing names (`galaxy`, `cool`, `jet`, `ocean`, …) return `""` (unmapped) and
are therefore excluded from the color bag. The `opentag_color_keywords` env var /
runtime setting feeds **additional synonyms** into this map — it no longer serves
as a primary color-recognition mechanism.

## Pre-filter gates (v2.1)

Before scoring, two gates narrow the candidate list to compatible entries. Both gates
run after the brand pre-filter (which already bounds candidates to one brand's materials).

### Polymer-family gate (`families_gate_compatible`)

Keeps candidates whose polymer family is gate-compatible with the SM filament's family.
An empty/unknown OPT family always passes (don't gate on missing data).

**PLA-biopolymer bucket** — the following families are mutually compatible:

> `pla`, `pha`, `pla/pha`, `lw-pla`, `htpla`, `rpla`

This bucket exists because ColorFabb and similar brands sell PLA/PHA blends but
OpenPrintTag inconsistently types them as `PHA`. Without the bucket, `colorfabb-woodfill`
(type=PHA) would be gate-dropped for a Spoolman "PLA Woodfill" filament.

All other families stay strictly separate: ASA ≠ PETG, PC ≠ PETG, ABS ≠ ASA, etc.

### Color-profile gate (`color_profile_compatible_soft`)

Keeps candidates whose color arrangement is compatible with the SM filament's profile.

**Strict path** — when BOTH sides carry explicit arrangement tags (coextruded/gradient)
AND the OPT entry has complete hex data (`hex_count >= 2`): applies `profiles_compatible`
logic unchanged (don't relax where data is complete).

**Soft path** — otherwise, uses **effective color arity** = `max(hex_count, name_color_count)`.
`name_color_count` is the sum of the color Counter from `decompose_name`. For a multicolor
SM side (arity ≥ 2), keeps OPT entries whose arity is also ≥ 2.

This fixes "Temperature Color Change Purple to Red" (OPT: `color=None`,
`secondaryColors=["#963877"]` → `hex_count=1`, but name → colors=`{purple:1, red:1}` →
`name_color_count=2` → arity=2 → passes). Previously the entry was dropped as "single"
and the identical name-match was never scored.

**`ngram_index` and `effective_synonyms` are built once** before the filament loop and
passed to both gates and `find_best_match` for consistency.

## Manual search

The **Search OpenTag manually…** control on each FilamentCard lets users type a
search query and see scored results from the full dataset for that card's brand and
material. The backend endpoint (`GET /api/openprinttag/search?brand=&material=&q=`)
constructs a synthetic `SpoolmanFilament(name=q, vendor=brand, material=material)`
and runs it through the same `score_candidate` function — no separate scoring path.
Results are returned sorted by confidence descending. Selecting a result injects it
as the active candidate for that card; the field table updates immediately.
