# Validation record

- Base repository commit: `9166aa6449cfb2a0e4efe754bedf013e9bedaf08`.
- Python 3.12; dependencies pinned in `requirements.txt`.
- `pytest -q`: **38 passed**.
- `python -m compileall -q bot.py web.py portal scripts`: passed.
- `node --check static/app.js`: passed.
- `git diff --check`: passed.

Tests cover the actual bot adapter and website sharing one reward store, simultaneous daily claims, repeated quiz submissions, attempt limits, manual-review reservation and replay, budget rollback, expiry, authenticated administration, one-time login expiry/replay, CSRF/origin checks, privacy of leaderboard output, payment recording and wallet restrictions, and the opt-in rollout.

The test database is an isolated in-memory implementation. These results do not establish live connectivity or behavior with the user's MongoDB, Telegram, Railway, DNS, or payment transactions. Run `scripts/prepare_portal.py` and the deployment checks before enabling the real portal.

Visual browser verification was unavailable in the build environment. No live website URL has been deployed. GitHub branch creation was rejected with HTTP 403 (`Resource not accessible by integration`); the existing repository branch and running services were not updated.

## Fix package (security and performance)

- `python -m unittest tests.test_fixes`: **26 passed** (membership cache, campaign counter, leaderboard cache, batched campaign bonus with resume, mining expiry, one wallet per account, payment-file totals, on-chain search before payout cancel, canonical-domain redirect).
- `bot.py` exercised end to end with simulated Telegram and MongoDB: captcha lockout, registration and single referral credit, payment-file upload (button required, preview, confirm once, file totals), "unpaid" refused after on-chain payment, campaign bonus, duplicate wallets after backfill, compressed backup — 22/22 checks passed.
- `python -m compileall`, `node --check static/app.js`: passed.
- Not verified here: live MongoDB, Telegram, BNB Smart Chain RPC, Railway.
