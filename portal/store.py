"""Small storage boundary. Production money-like writes require Mongo transactions."""
import copy
import logging
import threading


def _matches(document, query):
    """Tiny equality/$in/$lt matcher used only by the in-memory demo/test store."""
    for field, expected in (query or {}).items():
        value = document.get(field)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$in" and value not in operand:
                    return False
                if op == "$lt" and not (value is not None and value < operand):
                    return False
                if op == "$ne" and value == operand:
                    return False
        elif value != expected:
            return False
    return True


class MemoryStore:
    """Isolated demo/test store; never selected automatically in production."""
    def __init__(self):
        self.data = {}
        self.lock = threading.RLock()

    def get(self, collection, key):
        with self.lock:
            return copy.deepcopy(self.data.get(collection, {}).get(str(key)))

    def all(self, collection):
        with self.lock:
            return copy.deepcopy(list(self.data.get(collection, {}).values()))

    def scan(self, collection, fields=None):
        return self.all(collection)

    def find(self, collection, query=None, sort=None, limit=0):
        with self.lock:
            rows = [copy.deepcopy(d) for d in self.data.get(collection, {}).values() if _matches(d, query)]
        for field, direction in reversed(sort or []):
            rows.sort(key=lambda d: (d.get(field) is None, d.get(field, 0)), reverse=direction < 0)
        return rows[:limit] if limit else rows

    def put(self, collection, key, document):
        with self.lock:
            self.data.setdefault(collection, {})[str(key)] = copy.deepcopy(document)

    def delete(self, collection, key):
        with self.lock:
            self.data.get(collection, {}).pop(str(key), None)

    def transaction(self, callback):
        with self.lock:
            snapshot = copy.deepcopy(self.data)
            try:
                return callback(self)
            except Exception:
                self.data = snapshot
                raise

    def ready(self):
        return True


class MongoStore:
    def __init__(self, database, session=None):
        self.database = database
        self.session = session

    @staticmethod
    def _query(collection, key):
        if collection == "users":
            return {"user_id": int(key)}
        if collection == "bot_settings":
            return {"key": key}
        return {"_id": str(key)}

    def get(self, collection, key):
        return self.database[collection].find_one(self._query(collection, key), session=self.session)

    def all(self, collection):
        return list(self.database[collection].find({}, session=self.session))

    def scan(self, collection, fields=None):
        """Read a whole collection with only the fields a computation needs."""
        projection = {name: 1 for name in fields} if fields else None
        return list(self.database[collection].find({}, projection, session=self.session))

    def find(self, collection, query=None, sort=None, limit=0):
        cursor = self.database[collection].find(query or {}, session=self.session)
        if sort:
            cursor = cursor.sort(list(sort))
        if limit:
            cursor = cursor.limit(int(limit))
        return list(cursor)

    def put(self, collection, key, document):
        document = copy.deepcopy(document)
        if collection not in ("users", "bot_settings"):
            document["_id"] = str(key)
        self.database[collection].replace_one(self._query(collection, key), document, upsert=True, session=self.session)

    def delete(self, collection, key):
        self.database[collection].delete_one(self._query(collection, key), session=self.session)

    def transaction(self, callback):
        from pymongo.read_concern import ReadConcern
        from pymongo.write_concern import WriteConcern
        with self.database.client.start_session() as session:
            return session.with_transaction(
                lambda active: callback(MongoStore(self.database, active)),
                read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"),
            )

    def ensure_indexes(self):
        """Create portal indexes. Never deletes or rewrites user balances."""
        for name in ("portal_login_tokens", "portal_sessions", "portal_rate_limits", "portal_bot_states",
                     "portal_member_cache"):
            self.database[name].create_index("expires_at", expireAfterSeconds=0)
        self.database.portal_submissions.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_history.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_payments.create_index([("status", 1), ("created_at", -1)])
        self.database.portal_payments.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_tickets.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_tickets.create_index([("status", 1)])
        self.database.portal_payment_notifications.create_index([("status", 1), ("retry_at", 1), ("created_at", 1)])
        self.database.portal_messages.create_index([("status", 1), ("retry_at", 1), ("created_at", 1)])
        self.database.portal_mining.create_index([("status", 1), ("ends_at", 1)])
        self.database.portal_audit.create_index([("created_at", -1)])
        self.database.users.create_index("referred_by")
        self.database.users.create_index("wallet_lc")
        self.database.users.create_index("instagram_id_normalized")
        self.database.users.create_index("twitter_id_normalized")
        return self.ensure_unique_users()

    def ensure_unique_users(self):
        """One document per Telegram user. Fails safely (warning only) on legacy duplicates."""
        try:
            self.database.users.create_index(
                "user_id", unique=True, name="user_id_unique",
                partialFilterExpression={"user_id": {"$type": "number"}})
            return True
        except Exception as error:  # duplicates or an older conflicting index
            logging.getLogger(__name__).warning(
                "users.user_id unique index not created (%s); run scripts/prepare_portal.py", type(error).__name__)
            return False

    def backfill_wallet_keys(self):
        """Add a lowercase copy of each wallet for duplicate detection. Adds a field only."""
        result = self.database.users.update_many(
            {"wallet": {"$type": "string"}, "wallet_lc": {"$exists": False}},
            [{"$set": {"wallet_lc": {"$toLower": "$wallet"}}}])
        return result.modified_count

    def ready(self):
        hello = self.database.client.admin.command("hello")
        return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
