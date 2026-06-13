# Conflicts — types and resolution semantics

The bridge never auto-resolves a conflict. This page explains what each conflict type
means and — importantly — **what actually happens when you resolve it**, because the
answer differs by type.

## The conflict types

| Badge | When it fires |
|---|---|
| **Weight / Property / Multicolor** (cross-system) | The same field changed on *both* sides between sync cycles while the category is `two_way` with `manual` policy (or `newest_wins` couldn't determine a winner). |
| **Master divergence** | A Spoolman value would override a Filament DB variant's *inherited* setting (the variant currently gets the value from its parent). Writing it silently would detach the field from the parent, so the bridge asks first. |
| **Deleted record** | A previously-synced spool was deleted on one side, and the surviving side is still linked to it. The bridge protects the survivor and asks what you want. |
| **New filament** | An unmapped filament appeared on one side and `new_filament_policy` is `manual_review`. Actionable — use the "Add" button to create it on the other side and map it. Once a filament is mapped, any held spools belonging to it are released for normal new-spool handling. |
| **New spool** | An unmapped spool appeared whose filament is already mapped, and `new_spool_policy` is `manual_review`. Also appears when the filament is unmapped (the spool is held until the filament is imported). Actionable — use the "Add" button to create the spool once its filament is resolved. |

Open conflicts are deduplicated and survive restarts. Synced Records rows in conflict show
a **See conflict** button that deep-links to the exact row here.

For `new_filament` and `new_spool` conflicts the bridge uses an **upsert** strategy: each
sync cycle, the previous open conflict for that item is replaced with a fresh row. This
keeps exactly one open conflict per unmapped item at all times and ensures the stored
reason is always current. An unrelated conflict on a different field of the same item is
never affected. Existing duplicate rows from previous versions collapse to one on the next
sync cycle automatically.

## Conflict detail panels

Expanding a conflict row shows:

- **SPOOL / FILAMENT** entity label — clearly identifies which entity type the conflict is on.
- A **side-by-side Spoolman | Filament DB value grid** for conflicted fields (cross-system, weight, property, multicolor types).
- Deep links to the record in each upstream system.
- **Per-type action buttons** (see below) with a recommended default highlighted.

## What resolving does, per type

### Cross-system (weight / property / multicolor) — record-only

The expanded card shows the conflicting values side-by-side. Pick **Use Spoolman**,
**Use Filament DB**, or enter a **Manual value**. This records your choice and removes
the conflict from the queue — **it does not write the value upstream.** Make the actual
edit in whichever system you chose against, and the next sync cycle propagates it
normally. (Bulk-resolve works the same way for many rows at once.)

### Master divergence — applies upstream on resolve

The expanded card shows the incoming Spoolman value, the master's current value, and the
full variant line (live from Filament DB, with inherited/overridden status per variant).
Three actions with one-line explanations:

| Action | Filament DB | Spoolman | When to use |
|---|---|---|---|
| **Apply to all variants** | Writes the value to the master and to any variant that has its own override of this field (inherited variants follow the master automatically) | Writes the value to every mapped filament in the line | You want the whole line to use the Spoolman value |
| **Make variant's own setting** | Writes the value to this variant only — it becomes an explicit override; master and siblings untouched | Nothing (Spoolman already has the value) | This variant genuinely differs from the master |
| **Ignore** | Nothing | Nothing — current values are stored as baselines so the same divergence isn't re-queued every cycle | You want to dismiss the notice without any write |

"Apply to all" requires a confirmation step before writing. These writes are
human-approved, never silent — choosing the action *is* the approval. "Apply to all"
also auto-resolves any sibling master-divergence conflicts for the same field in the
same line, since the write that satisfies them just happened. If an upstream write fails,
the conflict stays open and you can retry.

### Deleted record — removes the bridge mapping

**Remove mapping** deletes the bridge's own link and snapshots for the pair. The surviving
upstream record is untouched, and the deleted record is **not** recreated. (If you wanted
it back, restore it upstream — the next wizard run or sync cycle re-links it.)

Note the bridge only queues a deletion conflict when there is a live, still-linked record
to protect. If both sides are gone, or the survivor's cross-reference was already cleared,
the stale link is purged automatically (logged in the Sync Log as `auto_stale_purge`) —
no conflict appears.

### New filament — "Add" or Dismiss

The expanded card shows the filament's **vendor · name** and a color swatch so you can
identify it without opening Spoolman or Filament DB. The id appears in parentheses
(e.g. *ELEGOO · PLA Wood filled (SM #136)*). Legacy rows without stored identity show
only the bare id — identity is stored from the cycle that queued the conflict, so rows
created before this feature shipped may lack it.

**Add** opens an inline import flow:
1. **Choose filament action** — "Create new filament" (default) or "Link to existing".
2. **Link to existing** — the UI fetches `GET /api/conflicts/{id}/filament-suggestions` and
   presents a ranked dropdown of Filament DB filaments that match the incoming Spoolman
   filament (exact cross-reference matches score 1.0; fuzzy matches on vendor + name + color
   fill the rest of the list, up to 8 results). You can also type a 24-character hex
   Filament DB id directly into the override field. If you select a variant's parent
   container, the import uses that parent as the explicit parent for single-record import
   — it does **not** detach or regroup any existing variants.
3. **Optional tare override** — overrides the spool_weight used for weight conversion.
4. **Preview** (`dry_run=true`) — shows what would be created/updated without writing.
5. **Confirm import** — executes the import (`POST /api/conflicts/{id}/import`), creates the
   filament in the target system, writes cross-reference IDs, and marks the conflict resolved.

**Dismiss** clears the notice without creating anything.

On a successful import any open `new_spool` conflicts that were held pending this filament
are not auto-resolved — they advance to normal new-spool handling on the next cycle.

#### Idempotent Add (find-or-attach on 409)

In `generic_container` mode, the bridge tries to create a colorless container parent and
the color variant before seeding the spool. If those records already exist in Filament DB
(from a prior Add or the wizard), the FDB API returns 409. The bridge **does not fail**
on a 409 — instead it performs *find-or-attach*:

1. **Container 409**: searches the live FDB filament list for a filament whose name
   matches the intended container name (case-insensitive, prefer null `parentId`).
   If found, attaches the cluster to that existing container and ensures the
   `FilamentMapping(is_synthetic_parent=True)` row exists. If no match, records a
   single failure (true collision — needs manual resolution).
2. **Variant/standalone 409**: searches the live FDB filament list by the intended
   variant name (case-insensitive, prefer `parentId == container_id`). If found,
   links to that existing filament; patches its `parentId` to the container if needed.
   If no match, records a single failure.

The result: re-running Add after a prior successful Add, or adding a sibling variant
under an existing master, produces **zero failures** and the conflict resolves. A
genuinely new filament still creates fresh as before.

### New spool — "Add" or Dismiss

The expanded card shows the spool's filament **vendor · name** and a color swatch,
same as new filament cards.

**Add** opens the same import flow (filament must already be mapped — if it isn't,
resolve its `new_filament` conflict first). On success the conflict is resolved and a
paired `new_filament` conflict for the same filament (if any) is also auto-resolved.

**Dismiss** clears the notice. Once a spool gets mapped (by the wizard, the engine, or
the import endpoint), any stale new-spool conflicts for it auto-resolve on the next cycle.

## Bulk Add

Select multiple `new_spool` or `new_filament` conflicts and click **Add selected** to
open the Bulk Add modal. Each record is imported sequentially using "create new filament"
as the default filament action. Records that require a specific FDB link or custom tare
override should be handled individually via the per-conflict Add flow instead.

## Synced Records — filament-only rows

Synced Records shows two kinds of rows:

- **Spool rows** (`kind: "spool"`) — a linked Spoolman spool + Filament DB spool pair.
  These show weight columns, relink/unlink actions, and the full detail grid when expanded.
- **Filament rows** (`kind: "filament"`) — a Spoolman filament that has a `FilamentMapping`
  but no spools yet. Common for filaments imported by the wizard before any spool is added
  in Spoolman. Displayed with a **(filament only)** hint, `—` for weight columns, and deep
  links to each system's filament page. Relink/unlink are hidden for these rows. Once a
  spool appears in Spoolman the engine maps it and the row becomes a spool row on the next
  cycle.

Synthetic parent container rows (created by the wizard in `generic_container` mode) do not
appear in Synced Records — they are internal bridge plumbing, not real cross-system pairs.

## Avoiding conflicts in the first place

- Keep categories **one-way** unless you genuinely edit both systems. Under a one-way
  direction the locked side can't generate conflicts — its drift is ignored.
- Shorter sync intervals shrink the window in which both sides can change the same field.
- `newest_wins` (weight only) auto-resolves most weight races but compares timestamps from
  two different servers — clock skew can pick the wrong side. Conflicts it can't decide
  fall back to the manual queue.
