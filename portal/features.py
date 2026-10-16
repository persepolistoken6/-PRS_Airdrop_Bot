"""Phase two: timed rewards, balance tiers and audited website management."""
import csv
import io
import re
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from .settings import CAMPAIGN_TIMEZONE, MAX_TOTAL_TOKENS_LIMIT, MINING_DEFAULT_BUDGET, MINING_SECONDS, REQUIRED_REFERRALS, TIERS


def level_for(user):
    from .service import earned
    balance = max(0, earned(user) - max(0, int(user.get("paid_amount", 0))))
    refs = max(0, int(user.get("ref_count", 0)))
    index = max(i for i, tier in enumerate(TIERS) if refs >= tier["referrals"] and balance >= tier["balance"])
    return {**TIERS[index], "stored_balance": balance, "next": dict(TIERS[index + 1]) if index + 1 < len(TIERS) else None}


class PhaseTwoMixin:
    def admin_bot_bonus(self, admin_id, operation_id, amount, user_id=None):
        """Legacy Telegram controls use the same transactional reward budget."""
        from .service import PortalError
        self.require_admin(admin_id)
        if type(amount) is not int or not 1 <= amount <= MAX_TOTAL_TOKENS_LIMIT or not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{12,64}", operation_id):
            raise PortalError("invalid_request")
        receipt = f"bot-bonus:{admin_id}:{operation_id}"
        def operation(tx):
            previous = tx.get("portal_admin_operations", receipt)
            if previous:
                if previous["amount"] != amount or previous["user_id"] != user_id:
                    raise PortalError("operation_conflict", 409)
                return {**previous, "already_completed": True}
            if user_id is not None:
                user = tx.get("users", user_id)
                if not user:
                    raise PortalError("user_not_found", 404)
                if user.get("portal_suspended"):
                    raise PortalError("account_suspended", 403)
                users = [user]
            else:
                users = [u for u in tx.all("users") if int(u.get("ref_count", 0)) >= REQUIRED_REFERRALS and
                         int(u.get("submitted", 0)) > 0 and not u.get("portal_suspended") and
                         re.fullmatch(r"0x[a-fA-F0-9]{40}", u.get("wallet") or "")]
            field = "manual_bonus_tokens" if user_id is not None else "bonus_tokens"
            ids_field = "manual_bonus_operation_ids" if user_id is not None else "bonus_operation_ids"
            history_field = "manual_bonus_history" if user_id is not None else "bonus_history"
            users = [u for u in users if operation_id not in u.get(ids_field, [])]
            self._credit_lock(tx, amount * len(users))
            for user in users:
                user[field] = int(user.get(field, 0)) + amount
                user["paid"] = 0
                user.setdefault(ids_field, []).append(operation_id)
                user.setdefault(history_field, []).append({"operation_id": operation_id, "amount": amount,
                    "created_at": self.now(), "created_by": admin_id})
                tx.put("users", user["user_id"], user)
                self._history(tx, f"{receipt}:{user['user_id']}", user["user_id"], "admin_bonus", amount,
                              "پاداش مدیریت · Management reward")
            result = {"user_id": user_id, "amount": amount, "count": len(users), "total": amount * len(users)}
            tx.put("portal_admin_operations", receipt, result)
            self._audit(tx, admin_id, "bonus", user_id if user_id is not None else "campaign",
                        {"amount": amount, "count": len(users), "source": "telegram"})
            return {**result, "already_completed": user_id is not None and not users}
        return self.store.transaction(operation)

    def admin_bot_payment(self, admin_id, user_id, action):
        """Record the trusted admin's legacy payment status without write skew.

        This records an external payment/status correction, never sends tokens.
        A pending portal request must be reviewed through its existing workflow.
        """
        from .service import PortalError, earned
        self.require_admin(admin_id)
        if action not in ("yes", "no", "unpaid"):
            raise PortalError("invalid_request")
        receipt = f"bot-payment:{uuid4().hex}"
        def operation(tx):
            user = tx.get("users", user_id)
            if not user:
                raise PortalError("user_not_found", 404)
            if tx.get("portal_open_payments", user_id):
                raise PortalError("payment_pending", 409)
            before = max(0, int(user.get("paid_amount", 0)))
            if action == "yes":
                user.update(paid=1, paid_amount=earned(user))
            elif action == "no":
                user["paid"] = 0
            else:
                user.update(paid=0, paid_amount=0)
            after = max(0, int(user.get("paid_amount", 0)))
            tx.put("users", user_id, user)
            if before != after:
                self._history(tx, receipt, user_id, "payment", before-after,
                              "ثبت وضعیت پرداخت توسط مدیر · Admin payment status")
            self._audit(tx, admin_id, "review_payment", user_id, {"source": "telegram", "action": action,
                        "paid_before": before, "paid_after": after})
            return {"paid": after}
        return self.store.transaction(operation)

    def register_gateway_user(self, user_id, referrer_id):
        """Complete a solved captcha + membership flow without bot notifications.

        The user document and inviter count commit together. Concurrent replies
        or old join buttons cannot credit the same invitation twice.
        """
        from .service import PortalError, earned
        def operation(tx):
            # Legacy users do not necessarily have a unique user_id index.
            # Serialize registration upserts even when there is no inviter.
            lock = tx.get("portal_state", "registration_lock") or {"sequence": 0}
            lock["sequence"] += 1
            tx.put("portal_state", "registration_lock", lock)
            user = tx.get("users", user_id) or {"user_id": user_id, "ref_count": 0, "lang": "fa"}
            if user.get("portal_suspended"):
                raise PortalError("account_suspended", 403)
            candidate = user.get("registration_referrer") or referrer_id
            if type(candidate) is int and candidate > 0 and candidate != user_id and not user.get("referred_by"):
                inviter = tx.get("users", candidate) or {"user_id": candidate, "verified": 0, "ref_count": 0}
                old_total = earned(inviter)
                inviter["ref_count"] = int(inviter.get("ref_count", 0)) + 1
                delta = earned(inviter) - old_total
                self._credit_lock(tx, delta)
                tx.put("users", candidate, inviter)
                user["referred_by"] = candidate
                self._history(tx, f"referral:{user_id}:{candidate}", candidate, "referral", delta,
                              "دعوت تأییدشده · Verified referral")
            user["verified"] = max(1, int(user.get("verified", 0)))
            user.setdefault("registered_at", self.now())
            tx.put("users", user_id, user)
        self.store.transaction(operation)

    def check_access(self, user_id):
        from .service import PortalError
        if (self.store.get("users", user_id) or {}).get("portal_suspended"):
            raise PortalError("account_suspended", 403)

    def mining_config(self, tx=None):
        tx = tx or self.store
        return {"enabled": True, "budget": MINING_DEFAULT_BUDGET, "spent": 0, "reserved": 0,
                **(tx.get("portal_state", "mining") or {})}

    def mining_status(self, user_id, user=None):
        user = user or self.store.get("users", user_id) or {"user_id": user_id}
        config = self.mining_config()
        cycle = self.store.get("portal_mining", user_id)
        active = cycle if cycle and cycle.get("status") == "active" else None
        return {"enabled": config["enabled"], "duration": MINING_SECONDS, "level": level_for(user),
                "tiers": [dict(tier) for tier in TIERS], "total_claimed": int(user.get("mining_total", 0)),
                "budget_remaining": max(0, config["budget"] - config["spent"] - config["reserved"]),
                "cycle": {k: active[k] for k in ("id", "started_at", "ends_at", "reward", "tier")} if active else None}

    def start_mining(self, user_id):
        from .service import PortalError
        self._member(user_id)
        cycle_id = uuid4().hex
        def operation(tx):
            self._enabled(tx)
            user = self._user(tx, user_id)
            current = tx.get("portal_mining", user_id)
            if current and current.get("status") == "active":
                raise PortalError("mining_active", 409)
            config = self.mining_config(tx)
            if not config["enabled"]:
                raise PortalError("mining_paused", 409)
            tier = level_for(user)
            amount = tier["reward"]
            if config["spent"] + config["reserved"] + amount > config["budget"]:
                raise PortalError("mining_budget_exhausted", 409)
            # Reserve the reward before the timer starts. Daily and mission
            # awards also account for these reservations under the credit lock.
            self._credit_lock(tx, amount)
            config["reserved"] += amount
            tx.put("portal_state", "mining", config)
            cycle = {"id": cycle_id, "user_id": user_id, "status": "active", "started_at": self.now(),
                     "ends_at": self.now() + MINING_SECONDS, "reward": amount, "tier": tier["id"]}
            # Conflict with a concurrent completed payment or suspension so the
            # stored reward snapshots a consistent level and access state.
            user["portal_mining_version"] = int(user.get("portal_mining_version", 0)) + 1
            tx.put("users", user_id, user)
            tx.put("portal_mining", user_id, cycle)
            return {"cycle": cycle}
        return self.store.transaction(operation)

    def claim_mining(self, user_id, cycle_id):
        from .service import PortalError
        if not isinstance(cycle_id, str) or not re.fullmatch(r"[a-f0-9]{32}", cycle_id):
            raise PortalError("invalid_mining_cycle")
        self._member(user_id)
        def operation(tx):
            self._enabled(tx)
            user = self._user(tx, user_id)
            cycle = tx.get("portal_mining", user_id)
            receipt = f"mining:{user_id}:{cycle_id}"
            previous = tx.get("portal_history", receipt)
            if previous:
                return {"amount": previous["amount"], "already_claimed": True}
            if not cycle or cycle["id"] != cycle_id or cycle["status"] != "active":
                raise PortalError("mining_not_started", 409)
            if self.now() < cycle["ends_at"]:
                raise PortalError("mining_not_ready", 409, remaining=cycle["ends_at"] - self.now())
            amount = cycle["reward"]
            config = self.mining_config(tx)
            config["reserved"] -= amount
            config["spent"] += amount
            tx.put("portal_state", "mining", config)
            self._credit_lock(tx, amount)
            user["manual_bonus_tokens"] = int(user.get("manual_bonus_tokens", 0)) + amount
            user["mining_total"] = int(user.get("mining_total", 0)) + amount
            user["paid"] = 0
            tx.put("users", user_id, user)
            cycle.update(status="claimed", claimed_at=self.now())
            tx.put("portal_mining", user_id, cycle)
            self._history(tx, receipt, user_id, "mining", amount, "پاداش ماین · Mining reward")
            return {"amount": amount, "already_claimed": False}
        return self.store.transaction(operation)

    def _audit(self, tx, admin_id, action, target, details=None):
        key = uuid4().hex
        tx.put("portal_audit", key, {"id": key, "admin_id": admin_id, "action": action,
               "target": str(target), "details": details or {}, "created_at": self.now()})

    def campaign_controls(self):
        return {"paused": (self.store.get("bot_settings", "bot_status") or {}).get("status") == "off",
                "announcement": (self.store.get("portal_state", "announcement") or {}).get("text", ""),
                "mining": self.mining_config(), "timezone": CAMPAIGN_TIMEZONE}

    def admin_controls(self, admin_id, payload):
        from .service import PortalError
        self.require_admin(admin_id)
        allowed = {"paused", "mining_enabled", "mining_budget", "announcement"}
        if not payload or not set(payload) <= allowed:
            raise PortalError("invalid_controls")
        for name in ("paused", "mining_enabled"):
            if name in payload and type(payload[name]) is not bool:
                raise PortalError("invalid_controls")
        if "mining_budget" in payload and (type(payload["mining_budget"]) is not int or not 0 <= payload["mining_budget"] <= MAX_TOTAL_TOKENS_LIMIT):
            raise PortalError("invalid_controls")
        if "announcement" in payload and (not isinstance(payload["announcement"], str) or len(payload["announcement"]) > 1500):
            raise PortalError("invalid_controls")
        def operation(tx):
            if "paused" in payload:
                tx.put("bot_settings", "bot_status", {"key": "bot_status", "status": "off" if payload["paused"] else "on"})
            if "mining_enabled" in payload or "mining_budget" in payload:
                config = self.mining_config(tx)
                if "mining_enabled" in payload:
                    config["enabled"] = payload["mining_enabled"]
                if "mining_budget" in payload:
                    if payload["mining_budget"] < config["spent"] + config["reserved"]:
                        raise PortalError("budget_below_committed", 409)
                    config["budget"] = payload["mining_budget"]
                tx.put("portal_state", "mining", config)
            if "announcement" in payload:
                tx.put("portal_state", "announcement", {"text": payload["announcement"].strip(), "updated_at": self.now()})
            self._audit(tx, admin_id, "campaign_controls", "campaign", payload)
        self.store.transaction(operation)
        return self.campaign_controls()

    @staticmethod
    def _admin_user(user):
        from .service import earned
        return {"user_id": user["user_id"], "registered": int(user.get("verified", 0)) >= 1,
                "referrals": int(user.get("ref_count", 0)), "referred_by": user.get("referred_by"),
                "earned": earned(user), "paid": int(user.get("paid_amount", 0)),
                "unpaid": level_for(user)["stored_balance"], "level": level_for(user),
                "wallet": user.get("wallet") or "", "suspended": bool(user.get("portal_suspended")),
                "mining_total": int(user.get("mining_total", 0))}

    def admin_users(self, admin_id, query="", page=1):
        from .service import PortalError
        self.require_admin(admin_id)
        if not isinstance(query, str) or len(query) > 100 or type(page) is not int or not 1 <= page <= 100000:
            raise PortalError("invalid_request")
        query = query.strip().lower()
        users = [self._admin_user(u) for u in self.store.all("users")
                 if not query or query in str(u["user_id"]) or query in str(u.get("wallet", "")).lower()]
        users.sort(key=lambda u: u["user_id"], reverse=True)
        return {"users": users[(page - 1) * 50:page * 50], "total": len(users), "page": page, "page_size": 50}

    def admin_user_detail(self, admin_id, user_id):
        from .service import PortalError
        self.require_admin(admin_id)
        user = self.store.get("users", user_id)
        if not user:
            raise PortalError("user_not_found", 404)
        recent = lambda name: sorted([item for item in self.store.all(name) if item.get("user_id") == user_id],
                                    key=lambda item: item.get("created_at", 0), reverse=True)[:30]
        return {"user": self._admin_user(user), "history": recent("portal_history"),
                "payments": recent("portal_payments"), "mining": self.mining_status(user_id, user),
                "referrals": [{"user_id": u["user_id"], "registered": int(u.get("verified", 0)) >= 1}
                              for u in self.store.all("users") if u.get("referred_by") == user_id]}

    def admin_user_action(self, admin_id, user_id, payload):
        from .service import PortalError
        self.require_admin(admin_id)
        action, reason = payload.get("action"), payload.get("reason", "")
        if action not in ("suspend", "resume", "unlock_wallet", "bonus"):
            raise PortalError("invalid_request")
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 400:
            raise PortalError("reason_required")
        amount, request_id = payload.get("amount"), payload.get("request_id")
        if action == "bonus" and (type(amount) is not int or not 1 <= amount <= MAX_TOTAL_TOKENS_LIMIT or
                                   not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{20,64}", request_id)):
            raise PortalError("invalid_request")
        def operation(tx):
            user = tx.get("users", user_id)
            if not user:
                raise PortalError("user_not_found", 404)
            details = {"reason": reason.strip()}
            if action == "suspend":
                if user_id in self.settings.admins:
                    raise PortalError("admin_protected", 409)
                user["portal_suspended"] = True
            elif action == "resume":
                user["portal_suspended"] = False
            elif action == "unlock_wallet":
                if tx.get("portal_open_payments", user_id):
                    raise PortalError("wallet_locked", 409)
                user["submitted"] = 1 if user.get("wallet") else 0
            else:
                user = self._user(tx, user_id)
                receipt = f"admin-bonus:{admin_id}:{request_id}"
                existing = tx.get("portal_history", receipt)
                if existing:
                    if existing["user_id"] != user_id or existing["amount"] != amount:
                        raise PortalError("operation_conflict", 409)
                    return {"ok": True, "already_completed": True}
                self._credit_lock(tx, amount)
                user["manual_bonus_tokens"] = int(user.get("manual_bonus_tokens", 0)) + amount
                user["paid"] = 0
                self._history(tx, receipt, user_id, "admin_bonus", amount, reason.strip())
                details["amount"] = amount
            tx.put("users", user_id, user)
            self._audit(tx, admin_id, action, user_id, details)
            return {"ok": True}
        return self.store.transaction(operation)

    def export_report(self, admin_id, kind):
        from .service import PortalError
        self.require_admin(admin_id)
        if kind == "users":
            rows = [self._admin_user(u) for u in self.store.all("users")]
            fields = ["user_id", "registered", "referrals", "referred_by", "earned", "paid", "unpaid", "wallet", "suspended", "mining_total"]
        elif kind == "payments":
            rows = self.store.all("portal_payments")
            fields = ["id", "user_id", "amount", "wallet", "status", "tx_hash", "reason", "created_at", "reviewed_at", "reviewed_by"]
        elif kind == "audit":
            rows = [{**row, "details": str(row.get("details", {}))} for row in self.store.all("portal_audit")]
            fields = ["id", "admin_id", "action", "target", "details", "created_at"]
        else:
            raise PortalError("not_found", 404)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(fields)
        for row in rows:
            values = []
            for field in fields:
                value = row.get(field, "")
                if field.endswith("_at") and value:
                    value = datetime.fromtimestamp(value, ZoneInfo(CAMPAIGN_TIMEZONE)).isoformat()
                value = str(value if value is not None else "")
                if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                    value = "'" + value
                values.append(value)
            writer.writerow(values)
        return "\ufeff" + output.getvalue()
