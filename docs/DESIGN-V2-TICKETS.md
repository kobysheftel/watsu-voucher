# V2 Design — Tickets: Vouchers + Multi-Session Passes (1st draft, 2026-09-13)

Status: DRAFT for Koby's review. No code written yet.

## 1. Goal
Generalise the gift voucher into a **Ticket** (כרטיס) that comes in two kinds:

| Kind | Hebrew | Who it is for | Entries | Gift semantics |
|---|---|---|---|---|
| VOUCHER | שובר מתנה | third party (recipient ≠ orderer) | N (default 1) | display_name, greeting, "איזה כיף קיבלת שובר מתנה" |
| PASS | כרטיסיה | the customer themself | N (default 5 / 10) | none — plain "כרטיסיה ל-N טיפולי וואטסו" |

Koby (2026-09-13): **both kinds are multi-entry.** The only difference is whether the ticket is a present (voucher) or for self use (pass). `kind` therefore drives only the wording and the PDF layout; the entries counter, payment and lifecycle are identical. "Mark used" on a 1-entry ticket = "consume the only entry". One rules engine, one table, one UI.

## 2. Ticket lifecycle (updated after Koby's answers, 2026-09-13)

Koby's decision: the customer first receives a **payment link** (what is included + terms), and the ticket itself (PDF + QR) is sent only **after payment**.

```
draft ──[send payment request]──► awaiting_payment ──[paid]──► paid ──[send ticket]──► active ──[last entry consumed]──► used
        (GI payment page created,                    (GI webhook or        (cement + QR + PDF,                            (frozen)
         link sent by WA / e-mail)                    manual "mark paid")   sendings row)
                                                                                └──[resend]──► active (new sendings row, same QR)
```

- `status` : draft / awaiting_payment / paid / active / used
  - `awaiting_payment` — payment link sent, ticket not yet produced
  - `paid` — money received, ticket not yet sent (the app shows "שולם — שלח כרטיסיה")
  - `active` — ticket sent; entries can be held / consumed
  - `used` — all entries consumed → fully frozen (view/print only), exactly like today
- Cement + QR + PDF happen at **send ticket** (the old "first send"), not at the payment request. Holder details stay editable until then.
- Sending the ticket is a manual step (WA needs a human tap). E-mail auto-send on payment can come later.
- `sendings.kind` : PAYMENT_LINK / TICKET — so the history shows both kinds of sends.
- `valid_until` : no new holds after expiry; already-held entries can still be consumed (Avigal's call, configurable later).
- Legacy rows: existing `sent` vouchers map to `active`, existing `used` stay `used`.

## 3. Entries (the pass counter)

New table `entries` — one row per treatment slot, created lazily (not N rows up-front):

| Column | Meaning |
|---|---|
| id | PK |
| ticket_id | FK → vouchers.voucher_id |
| seq | 1..N running number inside the ticket |
| status | held / consumed / cancelled |
| scheduled_for | planned treatment date-time (hold) |
| held_at / consumed_at / cancelled_at | audit timestamps |
| note | free text |
| performed_by | Koby / Avigal |

Counters are derived, never stored:

```
consumed  = count(status = consumed)
held      = count(status = held)
available = entries_total - consumed - held
```

Actions (rules.py):

| Action | Pre-condition | Effect |
|---|---|---|
| hold(ticket, when) | active, available > 0, not expired | new entry `held` (שריון) |
| consume(entry) | entry is held | held → consumed; if consumed == total → ticket `used` |
| cancel_hold(entry) | entry is held | held → cancelled (row kept for audit, counter released) |
| consume_direct(ticket) | active, available > 0 | new entry created directly as consumed (walk-in, no prior hold) |
| mark_used(voucher) | legacy API | = consume_direct on a 1-entry ticket |

Cancelled rows are kept so the history reads "שריון ל-3.10 בוטל". They do not count toward exhaustion.

## 4. Payments — Green Invoice (morning) digital payments

Koby's decisions: **all** tickets (vouchers too) go through GI; GI itself creates the accounting documents (which document type — to be seen later, not our concern in code beyond passing the configured type).

### 4a. Pricing
- A **price list** in `config/settings.json` (editable from a settings page): list price per product = (kind, יחיד/זוגי, entries). Examples: voucher יחיד, voucher זוגי, pass 5 יחיד, pass 10 יחיד …
- Per ticket: `list_price` (copied from the price list at creation), `discount` (amount or %), `price` = final agreed price. The customer sees only the final price.
- `terms` : a default terms text (what is included, validity, cancellation rules) kept in settings; copied onto the ticket at creation so later edits to the default do not change tickets already sent. Printed in the GI payment description and on the ticket PDF.

### 4b. Flow (the orderer pays)

1. **Send payment request** (draft → awaiting_payment), if `price > 0`:
   - `POST /account/token` (api key id + secret) → JWT
   - `POST /payments/form` → returns a hosted payment page URL
     - description "כרטיסיה 10 טיפולים / שובר מתנה", amount, currency ILS, lang he
     - client {name, phone, email} from holder
     - income [{description, quantity 1, price}]
     - document type = receipt (320) — to confirm against Avigal's business type
     - successUrl → `/pay/thanks` (public page), failureUrl → `/pay/failed`
     - notifyUrl → `/api/payments/greeninvoice/notify`
     - custom = ticket_id (our correlation key)
   - store `payment_url`, set `status = awaiting_payment`, log a sendings row (kind PAYMENT_LINK, via WA / EMAIL)
2. **Message to customer** (WA / email) = short text: what is included, price, terms, and the payment link. No ticket yet.
3. **Webhook** — GI posts to notifyUrl on payment. Handler:
   - public route (auth middleware exempt list), POST only
   - verify: `custom` matches a ticket, amount matches, then confirm by fetching the document from GI with our own JWT (never trust the callback body alone)
   - set `status = paid`, `paid_at`, `gi_document_id`, `receipt_number` = GI document number (closes the March question "voucher ID = receipt number" — the receipt number now comes from GI), e-mail notification to Koby ("שולם — יש לשלוח כרטיסיה")
4. **Manual "סמן כשולם"** button — for cash / Bit / bank transfer: sets paid with `payment_method` + note, no GI call (Avigal issues the receipt in GI by hand).
5. **Send ticket** (paid → active): cement + QR + PDF + sendings row (kind TICKET) — the existing first_send logic, gated on status = paid.
6. Sandbox first (GI sandbox environment + api keys in `config/greeninvoice.json`, git-ignored, same pattern as `secret.key`).

⚠️ Endpoint names / field names above are from memory of the GI API and must be verified against the official docs (greeninvoice.docs.apiary.io) before coding — the docs site redirected / 404'd during this session.

## 5. Schema changes (SQLite, ALTER TABLE on server before restart)

`vouchers` table (kept — renaming the table buys nothing):

| New column | Type | Default for existing rows |
|---|---|---|
| kind | TEXT | 'VOUCHER' |
| entries_total | INTEGER | 1 |
| list_price / discount / price | REAL NULL | NULL |
| terms | TEXT NULL | NULL |
| payment_method | TEXT NULL | 'manual' (legacy vouchers were paid by hand) |
| payment_url | TEXT NULL | NULL |
| gi_document_id | TEXT NULL | NULL |
| paid_at | DATETIME NULL | NULL |

`status` values: existing `sent` → `active` (one UPDATE), `draft` and `used` unchanged.
`sendings` gets `kind` TEXT default 'TICKET'.

New table `entries` (section 3). Backfill: every existing `used` voucher gets one `consumed` entry.

Ticket ID format unchanged: `{mobile}-{seq:03d}`. QR payload unchanged (`{"id", "ts"}`) — the QR identifies the ticket, the server knows the remaining count.

## 6. UI changes

- **List** (all_vouchers.html → "כרטיסים"): kind column (שובר / כרטיסיה), entries badge `3/10` (consumed/total, held shown as `+1`), payment badge (ממתין לתשלום / שולם).
- **New ticket**: kind toggle; entries count (default 1 for voucher, 5/10 presets for pass, any number for both); product from price list → list price, discount, final price; recipient/greeting fields only for voucher.
- **Ticket view**: entries panel (table of entries + buttons שריון / מימוש / ביטול שריון, date picker for hold), payment box (status, link copy button, "סמן כשולם").
- **Holder page**: totals per holder (available entries across passes).
- **Report / CSV**: add kind, entries, payment status, paid_at.
- Public pages (no login): `/pay/thanks`, `/pay/failed`.

## 7. PDF / image

- Voucher: current design; when entries > 1 the title becomes "שובר מתנה ל-N טיפולי וואטסו" and the punch-card circles row is added.
- Pass: same watercolor frame; title "כרטיסיה ל-N טיפולי וואטסו (יחיד/זוגי)"; holder name; no greeting; row of N small circles (punch-card look, decorative only — the real counter is in the app); validity; QR + ticket ID.

## 8. Later (not in the first implementation)

- QR scan page `/redeem/{token}`: opens ticket, shows remaining, hold/consume buttons on the phone.
- Auto-expire job for held entries whose scheduled_for passed without consumption (currently manual).
- Real e-mail sending to the customer (today: mailto).

## 9. Phasing

| Phase | Scope | Deploy risk |
|---|---|---|
| A | schema + entries + rules + UI, no payments (payment_status manual only) | ALTER TABLE + backfill, vouchers behave as today |
| B | Green Invoice sandbox → production: payment link on send, webhook, manual mark paid | new public routes in nginx/auth, GI credentials |
| C | pass PDF design, QR redeem page | none |

## 10. Decisions (Koby, 2026-09-13)

| # | Question | Decision |
|---|---|---|
| 1 | Terminology | pass = **כרטיסיה** (single yod), generic = כרטיס |
| 2 | Send order | payment link first (with what is included + terms), ticket PDF only after payment |
| 3 | Vouchers through GI too? | **yes** |
| 4 | Pricing | general price list + discount option; customer sees the agreed final price |
| 5 | GI documents | GI creates the documents; which type — decided later |
| 6 | Holder edit lock | **(a)** — orderer locked once the first entry of any of their tickets is consumed |
| 7 | Entries per kind | both voucher and pass are multi-entry; voucher defaults to 1, pass to 5 / 10, any number allowed |

`can_edit_holder()` becomes: no `consumed` entry exists on any ticket of this mobile. Cemented holder fields on the ticket never change either way.
