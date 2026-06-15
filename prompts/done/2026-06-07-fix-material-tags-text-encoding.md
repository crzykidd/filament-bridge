---
name: 2026-06-07-fix-material-tags-text-encoding
status: completed          # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Fixed filamentdb_material_tags encoding — now stores as CSV string so Spoolman text field accepts it (was 400ing with JSON array)
---

# Task: Fix filamentdb_material_tags encoding — Spoolman text field rejects a JSON array (400)

Confirmed via Spoolman + bridge logs: writing `filamentdb_material_tags` 400s every time
(e.g. `PATCH /api/v1/filament/86 → 400`). Cause: `encode_extra_value(value) = json.dumps(value)`
(`backend/app/schemas/spoolman.py:24`), and the bridge passes the ID **list** (`[17]`, or
`[]`), so it sends `"[17]"` — a JSON **array** — into the Spoolman **text** extra field
`filamentdb_material_tags`. Spoolman's text fields accept a JSON **string** (e.g.
`openprinttag_slug → "amolen-…"` works), not an array → 400 Bad Request. So material_tags has
NEVER persisted (the field exists but has no values), and it breaks both the OpenTag apply
AND the ongoing finish-sync (FDB→SM).

## Fix — store material_tags as a STRING value (comma-separated IDs)

The engine already uses a comma-separated signature for finish IDs
(`",".join(str(i) for i in sorted(ids))`). Use that same string form as the stored value so
Spoolman's text field accepts it and it round-trips.

1. **Helpers** (in `backend/app/core/material_tags.py`):
   - `serialize_material_tags(ids: Iterable[int]) -> str` → e.g. `"17"`, `"17,28"`, or `""`.
   - `parse_material_tags(raw) -> list[int]` → tolerant: accepts the new CSV string ("17,28"),
     an empty string (→ []), AND the legacy JSON-array form ("[17]" / a real list) for
     backward-compat; returns sorted unique ints.

2. **Write sites** — the value written must be the CSV STRING, then `encode_extra_value` (which
   `json.dumps` the string → `'"17,28"'`, a valid text value):
   - `backend/app/core/opentag_match.py` `opt_to_spoolman_fields` (~164): set
     `result["extra.filamentdb_material_tags"] = serialize_material_tags(sorted(finish_ids))`
     (a STRING, not a list). This also makes the confirm page show "17" instead of "[17]".
   - `backend/app/core/engine.py` finish-sync FDB→SM (~1324):
     `encoded = encode_extra_value(serialize_material_tags(sorted(fdb_ids_now)))`.

3. **Read site** — `backend/app/core/engine.py` `_sm_finish_ids_from_filament` (~1122): after
   `decode_extra_value(raw)`, use `parse_material_tags(...)` so both the new CSV and any legacy
   array value decode to `list[int]`.

4. **Apply payload** — `backend/app/api/opentag.py` `_build_sm_patch`: since
   opt_to_spoolman_fields now yields a string for material_tags, the existing
   `encode_extra_value(fd.value)` produces `'"17,28"'` correctly — no special-case needed.
   Verify the value flowing from the frontend decision is the string (it comes from the match
   field row's opentag_value, now a string).

5. **Diagnostics** — in the apply error handler (`opentag.py` ~error log) and in
   `update_filament`/the apply, include the Spoolman **response body** in the logged error
   (e.g. `exc.response.text`) so a future 4xx shows Spoolman's detail, not just the status.

## Verification

- `cd backend && pytest` — tests:
  - `serialize_material_tags([17,28]) == "17,28"`, `serialize_material_tags([]) == ""`;
    `parse_material_tags("17,28") == [17,28]`, `parse_material_tags("") == []`,
    `parse_material_tags("[17]") == [17]` (legacy), `parse_material_tags([17]) == [17]`.
  - `opt_to_spoolman_fields` returns `extra.filamentdb_material_tags` as a STRING ("17"),
    not a list; empty finish → "".
  - the apply builds a patch whose `extra.filamentdb_material_tags` encodes to `'"17"'`
    (a JSON string), NOT `"[17]"`.
  - engine finish-sync round-trip: write serialized → read parses back to the same id set;
    snapshot/sig unchanged (no flapping).
- `cd frontend && npx tsc --noEmit && npm run build` (the field row value is now a string;
  ensure the confirm display still renders fine).
- Reason through SM #86: material_tags now sent as `'"17"'` → Spoolman accepts → no 400.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: filamentdb_material_tags is stored as a comma-separated STRING in the
   Spoolman text extra field (a JSON array 400s); read is backward-compatible.
3. Non-interactive subagent run: when pytest (+ build) pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
