# Mobile updates & labels

filament-bridge can print a QR-coded label for each spool and serve a phone-friendly
page to update that spool from a scale — read a gross weight, change its location, save.
The label is printed through [LabelForge](https://github.com/crzykidd/labelforge) (a
self-hosted Brother QL driver); the QR encodes a stable bridge URL that redirects to the
update page. This page covers the whole flow: enabling the feature, the scan→update page,
the `/r/` redirect indirection, label printing, weight-save modes, and the Settings.

> The whole feature is **off by default** and gated behind a single master switch
> (`mobile_labels_enabled`). While it is off, every mobile/label endpoint and the `/r/`
> redirect return **403**, and the "Mobile updates" nav item is hidden. Nothing about the
> feature is reachable until you turn it on.

## Enabling the feature

In **Settings → Mobile & Labels**:

1. Flip **Enable mobile updates & labels** on (`mobile_labels_enabled`).
2. Set **Bridge public URL** (`bridge_public_url`) — the externally reachable base URL of
   the bridge that the printed QR will point at (e.g. `https://bridge.example.com`). Leave
   it blank to derive the URL from the incoming request instead (works behind a reverse
   proxy that forwards `X-Forwarded-Proto` / `X-Forwarded-Host`), but a fixed public URL is
   recommended so the same printed label always resolves.
3. Pick the **QR redirect target** (`mobile_redirect_target`) and the **default weight mode**
   (`mobile_weight_default_mode`) — both explained below.
4. To print labels, fill in the **LabelForge** connection fields (below).

Once enabled, a **Mobile updates** item appears in the nav (the SPA reads the flag from the
public `GET /api/version`).

## The scan → update flow

Scanning a label's QR (or opening the in-nav **Mobile updates** page and searching for a
spool) lands you on the spool update card. It shows the spool's live detail — brand, color,
material, the human-facing **number** (the Spoolman spool id) — pulled fresh from both
upstream systems, plus two editable fields:

- **Scale weight (gross).** Enter the reading straight off your scale. The card shows a
  live **net preview** (`net = gross − tare`), where the tare is the Filament DB filament's
  `spoolWeight` (or the built-in default if that filament has none). You weigh the whole
  spool; the bridge does the subtraction.
- **Location.** A free-text field backed by a datalist of every location the bridge already
  knows about (Filament DB locations + Spoolman spool locations, from
  `GET /api/mobile/locations`).

### Scan-page search box

The `/scan/:filId/:spoolId` page includes a **search box** at the top. After updating one
spool, you can type a name, vendor, color, or spool number to jump directly to any other
mapped spool — without scanning a new label. The search queries
`GET /api/mobile/spools?q=…` (case-insensitive substring, filtered server-side across
name/vendor/color hex/spool number). Selecting a result reloads the same page for the
chosen spool. The endpoint carries the same auth context as the rest of the scan flow
(public when `mobile_session_days == 0`, normal session otherwise).

**Save** sends a single `PATCH /api/mobile/spool/{fil}/{spool}`. The bridge writes the new
weight and/or location to **both** Filament DB and Spoolman, then **refreshes both
snapshots** to the agreed values so the next auto-sync cycle doesn't re-detect your change
as a fresh edit (the same anti-ping-pong rule the sync engine follows). A location change
finds-or-creates the Filament DB location id and stores the free-text name on the Spoolman
spool.

The identity in the URL is the **Filament DB filament id + spool id** — the bridge resolves
the Spoolman spool through its own mapping. Keeping the QR on the durable Filament DB ids
means a physical label survives re-imports and re-mapping.

### Log a dry cycle

Below the Save block, the card has a **Log dry cycle** section. Tap it to record that you dried this spool:

- **Temperature (°C)** and **Duration (minutes)** are pre-filled from the Filament DB filament's recommended `dryingTemperature` and `dryingTime` values (if set). You can edit these before logging.
- **Notes** is an optional free-text field.
- Tapping **Log dry cycle** posts immediately (`POST /api/mobile/spool/{fil}/{spool}/dry-cycle`) — this is a **separate action from Save** and does not send any weight or location data.
- This is a **Filament DB-only, one-way write** — Spoolman has no dry-cycle concept and is never updated. There is no snapshot refresh (nothing for the sync engine to detect).
- After logging, the card refreshes to show the updated **Last dried** date and total cycle count from FDB.

## Weight-save modes

The weight you enter is **absolute** (a true-up to the current scale reading), but how the
bridge records the change is governed by the save mode — `mobile_weight_default_mode`,
overridable per save with the card's toggle:

- **`direct_correction`** (default) — true up both systems to the new weight directly. Use
  this for a straight correction or recalibration.
- **`usage`** — on a **decrease**, log a Filament DB *usage* entry (preserving the audit
  trail; Filament DB reduces `totalWeight` itself), which then mirrors to Spoolman. On an
  **increase** (a refill), it falls back to a direct correction — a refill is never recorded
  as negative usage.

## The `/r/` redirect — why the indirection

The printed QR does **not** encode the update page directly. It encodes
`{bridge_public_url}/r/{fil}/{spool}`, and `GET /r/{fil}/{spool}` issues a **302 redirect**
to whatever `mobile_redirect_target` currently points at:

- **`bridge`** (default) — the bridge's own scan page, `/scan/{fil}/{spool}`, i.e. the
  update card described above.
- **`filamentdb`** — Filament DB's filament page, `{FILAMENTDB_URL}/filaments/{fil}`.

The point of the extra hop is that you can **change where every existing label points
without reprinting a single one**. Print today against the bridge scan page; later, switch
the target (e.g. to a future Filament DB mobile page) and every label follows.

The redirect carries the conditional `mobile_auth` dependency (see below) and the same
`mobile_labels_enabled` gate as the rest of the mobile flow (403 when the feature is off).

## Authentication

The scan flow's auth is controlled by **`mobile_session_days`** (integer, default **30**).
It governs three surfaces only — the `GET /r/{fil}/{spool}` redirect, the `/api/mobile/*`
and `/api/labels/*` endpoints, and the frontend `/scan/:filId/:spoolId` route — and is
**independent of** the `mobile_labels_enabled` master gate (that 403 still fires regardless).

- **`mobile_session_days = 0` → the scan flow is public.** Those three surfaces bypass the
  app password; a cold phone with no session can scan a label and update a spool. The rest
  of the app stays password-protected — every other route still requires login.
- **`mobile_session_days >= 1` → the scan flow requires the normal login** (session cookie
  or API token, exactly like the rest of the app), AND the login session cookie's lifetime
  is set to that many days. The default `30` is unchanged from before this setting existed:
  the scan page sits behind the normal session and scanning on a fresh phone prompts for
  login first.

Mechanically, the `mobile`/`labels` routers and the `/r/` redirect carry a dedicated
`mobile_auth` dependency instead of the global `require_auth`: it returns early (public)
only when `mobile_session_days == 0`, and otherwise runs the *exact same* check as
`require_auth`. No other router is affected. The cookie max-age (set on login and the
`TimestampSigner` verify) reads `mobile_session_days` days when `>= 1`, else falls back to
30 days. The public flag is surfaced to the SPA as `mobile_public` on `GET /api/version`,
which the frontend uses to render the `/scan/...` route without a login.

Set `mobile_session_days` in **Settings → Mobile & Labels** ("Scan login (days)") or via
the `MOBILE_SESSION_DAYS` env var (start-up fallback).

## Label printing (LabelForge)

Printing is handled by an external **LabelForge** instance you point the bridge at. The
bridge does **not** design the label — *you* create a named template in LabelForge with
`{placeholder}` text elements and (optionally) a `{qr_url}` QR element. The bridge only
supplies the *values* for the fields you list.

### Connecting LabelForge

In **Settings → Mobile & Labels**:

- **LabelForge URL** (`labelforge_url`) — base URL of your LabelForge instance.
- **LabelForge token** (`labelforge_token`) — the shared bearer token (masked input; leave
  blank if LabelForge needs no auth).
- **Template name** (`labelforge_template`) — the name of the template you created in
  LabelForge.
- **Fields** (`labelforge_fields`) — a CSV of which catalog fields to send (see below).
- **Label media** (`labelforge_label_media`) — optional per-print media/size hint; blank
  uses the template's stored media.
- **Test printer** — calls `GET /api/labels/printer-status` and reports the printer's
  readiness and loaded media, so you can confirm the connection before printing.

### The field catalog

The bridge can compute a fixed catalog of label fields and sends **only** the ones named in
`labelforge_fields` (an unknown name is skipped with a warning, never a hard error — the
template author owns the label):

| Field | Value |
|---|---|
| `brand` | Spoolman vendor name |
| `color` | Color name |
| `color_hex` | Color hex |
| `number` | Spoolman spool id (the human-facing label number) |
| `material` | Material / type |
| `qr_url` | The absolute `{base}/r/{fil}/{spool}` redirect URL |

`base` for `qr_url` is `bridge_public_url` when set, otherwise derived from the request.

A typical CSV is `brand,color,number,qr_url`.

### Printing

Two **Print label** buttons trigger `POST /api/labels/print`:

- a button below **Save** on the spool update card, and
- a compact action on each spool row in **Synced records** (shown only when the feature is
  on).

On success the UI shows the LabelForge job number. If LabelForge reports a **media
mismatch** (the loaded label roll doesn't match the template), the bridge surfaces a 409
with a **Print anyway** option that retries with `override=true`. If LabelForge isn't
configured (no URL or template), you get a clear "not configured" message rather than a
confusing upstream error.

## LabelForge `dev` build needed for QR

**QR *rendering* in LabelForge exists only on its `dev` branch (newer than v0.1.3).** The
HTTP API is identical across LabelForge's `main` and `dev`, so the bridge always sends the
`qr_url` value — but for the QR *element* to actually render on the label you must run a
LabelForge build that includes that work. **Text fields print on any LabelForge version;**
only the scannable QR needs the `dev` build.

## Settings reference

All of these live in **Settings → Mobile & Labels** and are runtime-editable (no restart);
env vars are the start-up fallback. Full table in
[configuration.md](configuration.md#runtime-editable-settings-settings-ui).

| Setting | Default | Meaning |
|---|---|---|
| `mobile_labels_enabled` | `false` | Master switch for the whole feature (403 on every endpoint when off) |
| `mobile_session_days` | `30` | Scan-flow auth + login-session lifetime (days). `0` = public scan flow (no app password on the scan page/endpoints; rest of app still gated); `>= 1` = require login, cookie lives this many days. Independent of `mobile_labels_enabled`. |
| `bridge_public_url` | `""` (derive from request) | External base URL baked into the printed QR |
| `mobile_redirect_target` | `bridge` | `/r/` 302 target: `bridge` (scan page) or `filamentdb` |
| `mobile_weight_default_mode` | `direct_correction` | Default weight-save mode: `direct_correction` or `usage` (overridable per save) |
| `labelforge_url` | `""` | LabelForge base URL |
| `labelforge_token` | `""` | LabelForge bearer token (secret) |
| `labelforge_template` | `""` | LabelForge template name to print |
| `labelforge_fields` | `""` | CSV of catalog fields to send (e.g. `brand,color,number,qr_url`) |
| `labelforge_label_media` | `""` | Optional per-print media hint (blank = template default) |
