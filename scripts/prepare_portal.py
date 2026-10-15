"""Non-destructive production readiness check. Never prints connection strings."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal.service import build_service
from portal.settings import Settings


def main():
    settings = Settings.from_env()
    if settings.demo:
        raise RuntimeError("Readiness must run against the intended production database, not a demo")
    service = build_service(settings)
    if not service.store.ready():
        raise RuntimeError("MongoDB must support replica-set/sharded transactions. Do not enable the portal on a standalone server.")
    duplicate = next(service.store.database.users.aggregate([
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}, {"$limit": 1}
    ]), None)
    if duplicate:
        raise RuntimeError("Duplicate legacy user IDs detected. Resolve them before enabling the portal; no users were changed.")
    service.store.ensure_indexes()
    service.store.transaction(lambda tx: tx.put("portal_state", "readiness", {
        "checked_at": datetime.now(timezone.utc), "version": 1
    }))
    print("READY: transaction support and portal indexes checked. Existing users and balances were not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Safe errors above contain no connection string. Driver errors only expose class.
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"NOT READY: {message}", file=sys.stderr)
        sys.exit(1)
