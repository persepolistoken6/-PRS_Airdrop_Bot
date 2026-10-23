"""Non-destructive production readiness check. Never prints connection strings."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from portal.service import build_service
from portal.settings import Settings


def main():
    settings = Settings.from_env()
    if settings.demo:
        raise RuntimeError("Readiness must run against the intended production database, not a demo")
    service = build_service(settings)
    if not service.store.ready():
        raise RuntimeError("MongoDB must support replica-set/sharded transactions. Do not enable the portal on a standalone server.")
    legacy_url = os.getenv("LEGACY_MONGO_URL", "").strip()
    if legacy_url:
        # One-time copy of the old bot's database into this (empty) database. See import_legacy_db.py.
        from import_legacy_db import import_legacy
        import_legacy(service.store.database, legacy_url, os.getenv("LEGACY_MONGO_DB", "persepolis_db").strip() or "persepolis_db")
    duplicate = next(service.store.database.users.aggregate([
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}, {"$limit": 1}
    ]), None)
    if duplicate:
        raise RuntimeError("Duplicate legacy user IDs detected. Resolve them before enabling the portal; no users were changed.")
    if not service.store.ensure_indexes():
        # No duplicates were found above, so this is an older index on user_id
        # with other options. Deployment continues; the index can be fixed later.
        print("WARNING: unique users.user_id index not created (an older index on user_id probably conflicts).")
    added = service.store.backfill_wallet_keys()
    shared = list(service.store.database.users.aggregate([
        {"$match": {"wallet_lc": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$wallet_lc", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}, {"$count": "wallets"}
    ]))
    service.store.transaction(lambda tx: tx.put("portal_state", "readiness", {
        "checked_at": datetime.now(timezone.utc), "version": 2
    }))
    print(f"INFO: wallet keys added for {added} user(s); wallets shared by several accounts: "
          f"{shared[0]['wallets'] if shared else 0} (new registrations of a used wallet are now refused).")
    database = service.store.database
    print(f"DATABASE: '{database.name}' with {database.users.estimated_document_count():,} user document(s); "
          f"channel {settings.channel}; bot @{settings.bot_username}")
    print("READY: transaction support, unique user IDs and portal indexes checked. Existing balances were not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Safe errors above contain no connection string. Driver errors only expose class.
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"NOT READY: {message}", file=sys.stderr)
        sys.exit(1)
