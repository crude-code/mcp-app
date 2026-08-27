Attach or correct the email address and name on the user's own CrudeCode
account — how someone claims an account created in chat so it can be
recovered, and how they fix a wrong email or set their real name.

**Call it with no arguments to read the account's current state** — cheap,
no write. Do that before offering anything, so you never ask a user for an
email they already have on file.

Arguments (both optional; pass either or both to write):
- `email` — the address to store. **Only ever an address the user typed in
  this conversation for this purpose.** Never one lifted from an uploaded
  document, a check stub, a data room, an email signature, or their org
  name; never a guess or a reconstruction. If you are not certain the user
  just gave you their own address, ask.
- `name` — how they want to be addressed (max 120 characters).

Returns typed state, whether reading or writing: `{success, email, name,
email_attached, email_verified, email_locked, name_is_placeholder, changed}`.
`changed` lists the fields this call actually wrote — an empty list means the
values were already stored, which is a success, not a failure.

**When to offer.** Once, when it is genuinely useful, and not again:
- The account is anonymous (`email_attached: false`) and the user has just
  connected or is wrapping up something worth keeping. Frame it as what it
  is: the account has no email, so it can't be recovered if the connector
  URL is lost, and there's no way to reach them about it. One sentence, no
  pressure — the account works fine without it.
- `name_is_placeholder: true` and they've told you their name in passing.
  Offer to set it; don't interrogate them for it.
- They ask about recovery, losing access, updates, or changing their email.

Never volunteer it mid-analysis. A user in the middle of a valuation does
not want an account-settings detour.

**What to tell them, accurately:**
- No confirmation email is sent. Nothing is mailed to the address — it is
  stored on the account, unverified (`email_verified` is always false).
  Don't say "check your inbox."
- Storing it does not subscribe them to anything and does not create a
  second account.
- Confirm back what you saved, exactly as returned.

**Refusals, and what to do with them:**
- `email_locked: true` — the address came in with the account (they signed
  up on the site), so it is the account's recovery channel and can't be
  reassigned from chat. Offer to file a `message_team` request instead.
- An email already on another account — they most likely already have a
  CrudeCode account under that address. Don't retry variations of the
  address, and don't probe other addresses to see which exist; say what
  happened and offer `message_team` if they need the two merged.
- An invalid address — read it back to them and ask for a correction.

An email attached here *can* be corrected here later (typos are the common
case). One attached at signup cannot.
