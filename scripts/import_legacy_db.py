"""One-time copy of the old bot's MongoDB into this portal's database.

scripts/prepare_portal.py runs it on deploy while LEGACY_MONGO_URL is set:
  LEGACY_MONGO_URL  connection string of the old bot's database (read only)
  LEGACY_MONGO_DB   database name there (default: persepolis_db)
The target is this service's own MONGO_URL / MONGO_DB, which must be empty.

Safety:
  * The old database is only read; nothing is written or deleted there.
  * A target that already has users is refused (no mixing with test or live data).
  * Documents keep their _id (their creation time orders old referrals).
  * An interrupted copy resumes on the next deploy; a finished one is not repeated.
  * Old bot race duplicates (two documents with one user_id): the first document,
    the one the old bot read and updated, stays in users; the others are moved to
    legacy_duplicate_users in the target. Nothing is lost.
Never prints connection strings.
"""
from datetime import datetime, timezone

from pymongo import MongoClient
from pymongo.errors import BulkWriteError

BATCH = 500
STATUS = "portal_legacy_import"          # target collection holding the import status
DUPLICATES = "legacy_duplicate_users"
SKIP = {STATUS, DUPLICATES}


def _now():
    return datetime.now(timezone.utc)


def _insert(collection, docs):
    """Insert a batch; documents already copied by an interrupted run are skipped."""
    try:
        collection.insert_many(docs, ordered=False)
    except BulkWriteError as error:
        if any(item.get("code") != 11000 for item in error.details.get("writeErrors", [])):
            raise


def _copy(source, target, name, log):
    batch, total = [], 0
    for doc in source[name].find({}).sort("_id", 1).batch_size(BATCH):
        batch.append(doc)
        if len(batch) >= BATCH:
            _insert(target[name], batch)
            total += len(batch)
            batch = []
            if total % 10000 == 0:
                log(f"IMPORT: {name}: {total:,} copied so far")
    if batch:
        _insert(target[name], batch)
        total += len(batch)
    return total


def _move_duplicates(target, log):
    """Keep the first document of each user_id in users; move the rest aside."""
    groups = list(target.users.aggregate([
        {"$match": {"user_id": {"$type": "number"}}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ], allowDiskUse=True))
    moved = 0
    for group in groups:
        docs = list(target.users.find({"user_id": group["_id"]}).sort("_id", 1))
        for extra in docs[1:]:
            target[DUPLICATES].replace_one({"_id": extra["_id"]}, dict(extra, moved_at=_now()), upsert=True)
            target.users.delete_one({"_id": extra["_id"]})
            moved += 1
    if moved:
        log(f"IMPORT: {len(groups)} user ID(s) had duplicate documents; kept the first of each, "
            f"moved {moved} extra document(s) to {DUPLICATES}")
    return len(groups), moved


def import_legacy(target, source_url, source_name="persepolis_db", log=print, client_factory=MongoClient):
    """Copy every collection of the old database into target (a pymongo Database). Returns a summary."""
    status = target[STATUS].find_one({"_id": "status"})
    if status and status.get("status") == "done":
        log(f"IMPORT: already done on {status.get('finished_at')}; nothing copied again. "
            f"Remove LEGACY_MONGO_URL from the variables.")
        return status
    client = None
    try:
        client = client_factory(source_url, serverSelectionTimeoutMS=20000, appname="prs-legacy-import")
        source = client[source_name]
        names = sorted(n for n in source.list_collection_names() if not n.startswith("system.") and n not in SKIP)
        counts = {name: source[name].count_documents({}) for name in names}
    except Exception as error:
        if client is not None:
            client.close()
        raise RuntimeError(f"Could not read the old database ({type(error).__name__}). LEGACY_MONGO_URL must be its "
                           f"public connection string (on Railway: MONGO_PUBLIC_URL of the old MongoDB).") from None
    try:
        if not counts.get("users"):
            raise RuntimeError(f"The old database '{source_name}' has no users. Check LEGACY_MONGO_URL and LEGACY_MONGO_DB.")
        if not status:
            used = sorted(n for n in target.list_collection_names()
                          if not n.startswith("system.") and n not in SKIP and target[n].find_one({}, {"_id": 1}))
            if used:
                raise RuntimeError(f"The target database is not empty ({', '.join(used[:5])}). Set MONGO_DB to a new, "
                                   f"empty database name (for example prs_main) on this service, then deploy again.")
            target[STATUS].insert_one({"_id": "status", "status": "running", "started_at": _now(),
                                       "source_db": source_name, "source_counts": counts})
        else:
            log("IMPORT: resuming an interrupted copy")
        log("IMPORT: copying " + ", ".join(f"{name} ({count:,})" for name, count in counts.items()))
        for name in names:
            _copy(source, target, name, log)
        # Every source document must now be in the target (users before duplicates are moved).
        missing = {name: counts[name] - target[name].count_documents({})
                   - (target[DUPLICATES].count_documents({}) if name == "users" else 0) for name in names}
        missing = {name: n for name, n in missing.items() if n > 0}
        if missing:
            raise RuntimeError("Copy incomplete, deploy again to resume: " +
                               ", ".join(f"{name} missing {n}" for name, n in missing.items()))
        groups, moved = _move_duplicates(target, log)
        summary = {"status": "done", "finished_at": _now(), "copied": counts,
                   "duplicate_user_ids": groups, "duplicate_documents_moved": moved}
        target[STATUS].update_one({"_id": "status"}, {"$set": summary})
        log(f"IMPORT DONE: {counts['users']:,} user document(s) and {len(names)} collection(s) copied. "
            f"The old database was not changed. Remove LEGACY_MONGO_URL from the variables.")
        return summary
    finally:
        client.close()
