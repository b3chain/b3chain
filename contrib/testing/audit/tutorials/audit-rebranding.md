# Tutorial — Rebranding regression: catch the strings AND the behaviour

## The problem in one sentence
A B3Chain release that says "Bitcoin" anywhere a user can see is a
trust-destroying bug; a B3Chain release where a "Bitcoin"-named test
quietly stops running is the much bigger silent bug.

## The theory

Rebranding a Bitcoin Core fork involves two distinct kinds of change:

1. **String changes** — every user-facing mention of "Bitcoin" /
   `bitcoind` / `bitcoin-cli` / `bc1` / etc. that should now read
   "B3Chain" / `b3chaind` / `b3chain-cli` / `b3`.
2. **Behaviour changes** — the underlying logic must keep working.
   Renaming a class member or a config flag often means a test that
   referenced the old name now silently doesn't exercise the new one.

Both classes of bug have bitten previous Bitcoin forks. The audit
covers both.

## Hands-on demo

```bash
bash contrib/testing/audit/audit-rebranding.sh
```

The script does:

1. **Forbidden-pattern grep** over `src/` and `contrib/`:
   - `"Bitcoin Signed Message"` outside `src/test/`
   - `bitcoin:` URI scheme outside protocol constants
   - `bitcoind` / `bitcoin-cli` in non-historical `.md` files
   - `tr("...Bitcoin...")` in Qt source
   - allowlist for legitimate references (copyright lines, contrast tables, etc.)
2. **Behavioural regression**: rebuilds the project and re-runs the
   full unit + functional + regtest simulation suites. Any change in
   pass/fail counts vs the pre-rebrand baseline is reported.

## Hands-on: see the catch

The first time we ran this audit it caught **9 real string regressions**
that the rebranding pass had missed:

- 5 Qt `tr()` strings still saying "Bitcoin" (address book, intro
  dialog, GUI utilities, send-coins dialog).
- 1 RPC error message ("Invalid Bitcoin address" in
  `rawtransaction_util.cpp`).
- 1 Doxygen project name still set to "Bitcoin Core".
- 9 contrib README files referring to `bitcoind` / `bitcoin-cli` in
  command examples.

All fixed in the same commit set as the audit framework. See
`doc/SECURITY-AUDIT.md` "Findings and remediation" section for the
full table.

## Exercise

Add a string regression: in `src/qt/utilitydialog.cpp`, change a
visible label to mention "Bitcoin":

```cpp
ui->aboutMessage->setHtml("Welcome to <b>Bitcoin</b> wallet"); // was B3Chain
```

Re-run:

```bash
bash contrib/testing/audit/audit-rebranding.sh
```

Expected output:

```
  FAIL  [B-2] forbidden pattern 'Bitcoin' in user-visible Qt string
        src/qt/utilitydialog.cpp:127: setHtml("Welcome to <b>Bitcoin</b>...")
AUDIT RESULT: FAIL  [B-2]
```

## Why allowlists are dangerous, and how we manage them

Some references to "Bitcoin" are deliberately preserved:

- Copyright lines: `// Copyright (c) 2009-2024 The Bitcoin Core developers`
- Contrast tables: README files that explain B3Chain by reference to
  Bitcoin
- External URLs: e.g. `org.bitcoincore.flathub`

These are explicitly allowlisted in `audit-rebranding.sh`. The risk is
that the allowlist grows quietly until it hides real bugs. We mitigate
by:

- Keeping each allowlist entry on its own line with a comment justifying
  it.
- Forbidding allowlist additions in the same commit as the change being
  allowed (must be a separate, reviewed PR).
- Periodically auditing the allowlist itself.

## Further reading

- Litecoin's rebranding history (one of the earliest forks, with a
  long-tail of "litecoind" -> "Litecoin Core" string updates):
  github.com/litecoin-project/litecoin
- Bitcoin Cash's rebrand from Bitcoin ABC (similar churn).
- The "BIP / book" review pattern: every string change is reviewed by
  someone other than the author.
