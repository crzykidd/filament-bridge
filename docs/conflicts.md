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
| **New spool** | An unmapped spool appeared and the bridge couldn't auto-match its filament. Informational — creation happens via the Bulk Import Wizard. |

Open conflicts are deduplicated (the same field + records is queued once, not every cycle)
and survive restarts. Synced Records rows in conflict show a **See conflict** button that
deep-links to the exact row here.

## What resolving does, per type

### Cross-system (weight / property / multicolor) — record-only

Pick **Use spoolman**, **Use filamentdb**, or enter a **manual value**. This records your
choice and removes the conflict from the queue — **it does not write the value upstream.**
Make the actual edit in whichever system you chose against, and the next sync cycle
propagates it normally. (Bulk-resolve works the same way for many rows at once.)

### Master divergence — applies upstream on resolve

The expanded card shows the incoming Spoolman value, the master's current value, and the
full variant line (live from Filament DB, with inherited/overridden status per variant).
Three actions:

| Action | Filament DB | Spoolman |
|---|---|---|
| **Apply to all variants** | Writes the value to the master and to any variant that has its own override of this field (inherited variants follow the master automatically) | Writes the value to every mapped filament in the line |
| **Make variant's own setting** | Writes the value to this variant only — it becomes an explicit override; master and siblings untouched | Nothing (Spoolman already has the value) |
| **Ignore** | Nothing | Nothing — current values are stored as baselines so the same divergence isn't re-queued every cycle |

These writes are human-approved, never silent — choosing the action *is* the approval.
"Apply to all" also auto-resolves any sibling master-divergence conflicts for the same
field in the same line, since the write that satisfies them just happened. If an upstream
write fails, the conflict stays open and you can retry.

### Deleted record — removes the bridge mapping

**Remove mapping** deletes the bridge's own link and snapshots for the pair. The surviving
upstream record is untouched, and the deleted record is **not** recreated. (If you wanted
it back, restore it upstream — the next wizard run or sync cycle re-links it.)

Note the bridge only queues a deletion conflict when there is a live, still-linked record
to protect. If both sides are gone, or the survivor's cross-reference was already cleared,
the stale link is purged automatically (logged in the Sync Log as `auto_stale_purge`) —
no conflict appears.

### New spool — dismiss

**Dismiss** clears the notice. To actually create the record, run the Bulk Import Wizard,
which handles filament matching and creation properly. Once a spool gets mapped (by the
wizard or the engine), any stale new-spool notices for it auto-resolve.

## Avoiding conflicts in the first place

- Keep categories **one-way** unless you genuinely edit both systems. Under a one-way
  direction the locked side can't generate conflicts — its drift is ignored.
- Shorter sync intervals shrink the window in which both sides can change the same field.
- `newest_wins` (weight only) auto-resolves most weight races but compares timestamps from
  two different servers — clock skew can pick the wrong side. Conflicts it can't decide
  fall back to the manual queue.
