"""Small storage boundary. Production money-like writes require Mongo transactions."""
import copy
import threading


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
        # No destructive migration or unique-index assumption on legacy users.
        for name in ("portal_login_tokens", "portal_sessions", "portal_rate_limits", "portal_bot_states"):
            self.database[name].create_index("expires_at", expireAfterSeconds=0)
        self.database.portal_submissions.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_history.create_index([("user_id", 1), ("created_at", -1)])
        self.database.portal_payments.create_index([("status", 1), ("created_at", -1)])
        self.database.portal_payment_notifications.create_index([("status", 1), ("retry_at", 1), ("created_at", 1)])
        self.database.portal_mining.create_index([("status", 1), ("ends_at", 1)])
        self.database.portal_audit.create_index([("created_at", -1)])

    def ready(self):
        hello = self.database.client.admin.command("hello")
        return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
