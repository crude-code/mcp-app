Attach or update the recovery email and display name on the user's own
CrudeCode account — how someone claims an account created in chat so it can
be recovered, and how they fix a wrong email or set their real name.

Both fields are optional and the account is fully functional without either.
The only consequence of having no recovery email is that the account can't be
recovered if the connector URL is lost, and there's no way to reach them
about it. The address is used for account recovery and occasional
product-update mail; it is never required for any feature.

**Reading is free.** Call with no arguments to get the account's current
state — no write, not rate-limited. Do that before raising the subject, so
you never ask for an email the user already has on file.

**Writing needs their go-ahead.** Pass `email` and/or `name` only when the
user has asked to set or change one, or has clearly agreed after you told
them the account has no recovery email. Never mid-analysis — someone in the
middle of a valuation doesn't want an account-settings detour — and never
twice.

- `email` — **only an address the user typed in this conversation for this
  purpose.** Never one lifted from an uploaded document, check stub, data
  room, or email signature; never a guess. If you are not certain they just
  gave you their own address, ask.
- `name` — how they want to be addressed, max 120 characters.

Returns the same typed state either way: `{success, email, name,
email_attached, email_verified, email_locked, name_is_placeholder, changed}`.
`changed` lists what this call actually wrote; empty means the values were
already stored — a success, not a failure. Confirm back exactly what it
returns.

**Nothing is verified and nothing is mailed to the address.**
`email_verified` is always false and no confirmation is sent — never say
"check your inbox."

**Refusals:**
- `email_locked: true` — the address came in with the account (site signup),
  so it is the account's recovery channel and can't be reassigned from chat.
  Offer to file a `message_team` request instead.
- Already on another account — they most likely already have a CrudeCode
  account under that address. Don't retry variations of it, and don't probe
  other addresses to see which exist; say what happened and offer
  `message_team` if the two need merging.
- Invalid address — read it back to them and ask for a correction.

An email attached here can be corrected here later (typos are the common
case). One set at signup cannot.
