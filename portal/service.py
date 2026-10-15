import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from .settings import (BASE_REWARD, DAILY_REWARD, EXTRA_REWARD, MAX_TOTAL_TOKENS_LIMIT,
                       REQUIRED_REFERRALS, Settings)
from .store import MemoryStore, MongoStore


class PortalError(Exception):
    def __init__(self, code, status=400, **details):
        self.code, self.status, self.details = code, status, details
        super().__init__(code)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def earned(user):
    refs = int(user.get("ref_count", 0))
    base = BASE_REWARD + (refs - REQUIRED_REFERRALS) * EXTRA_REWARD if refs >= REQUIRED_REFERRALS else 0
    return base + int(user.get("daily_count", 0)) * DAILY_REWARD + int(user.get("bonus_tokens", 0)) + int(user.get("manual_bonus_tokens", 0))


def telegram_membership(settings, user_id):
    query = urlencode({"chat_id": settings.channel, "user_id": user_id})
    try:
        with urlopen(f"https://api.telegram.org/bot{settings.bot_token}/getChatMember?{query}", timeout=5) as response:
            result = json.load(response)
        member = result.get("result", {})
        return result.get("ok") and (member.get("status") in ("member", "administrator", "creator") or (member.get("status") == "restricted" and member.get("is_member")))
    except Exception:
        # Never include the request URL (which contains the token) in an error.
        raise PortalError("telegram_unavailable", 503) from None


class PortalService:
    def __init__(self, store, settings, member_check=None, clock=time.time):
        self.store, self.settings, self.clock = store, settings, clock
        self.member_check = member_check or (lambda uid: telegram_membership(settings, uid))

    def now(self):
        return int(self.clock())

    def limit(self, key, maximum=60, seconds=60):
        def operation(tx):
            now = self.now()
            item = tx.get("portal_rate_limits", key)
            if not item or item["until"] <= now:
                item = {"count": 0, "until": now + seconds, "expires_at": datetime.fromtimestamp(now + seconds, timezone.utc)}
            if item["count"] >= maximum:
                raise PortalError("rate_limited", 429)
            item["count"] += 1
            tx.put("portal_rate_limits", key, item)
        self.store.transaction(operation)

    def _user(self, tx, user_id):
        user = tx.get("users", user_id)
        if not user or int(user.get("verified", 0)) < 2:
            raise PortalError("registration_required", 403)
        return user

    def _enabled(self, tx):
        setting = tx.get("bot_settings", "bot_status")
        if setting and setting.get("status") == "off":
            raise PortalError("campaign_paused", 403)

    def _member(self, user_id):
        if not self.member_check(user_id):
            raise PortalError("membership_required", 403)

    def _credit_lock(self, tx, amount):
        # Serializes new daily/mission awards across both bot and web workers.
        lock = tx.get("portal_state", "credit_lock") or {"sequence": 0}
        lock["sequence"] += 1
        tx.put("portal_state", "credit_lock", lock)
        if sum(earned(u) for u in tx.all("users")) + amount > MAX_TOTAL_TOKENS_LIMIT:
            raise PortalError("campaign_budget_exhausted", 409)

    def _history(self, tx, receipt, user_id, kind, amount, title):
        if tx.get("portal_history", receipt):
            raise PortalError("already_completed", 409)
        tx.put("portal_history", receipt, {"id": receipt, "user_id": user_id, "kind": kind,
            "amount": amount, "title": title, "created_at": self.now()})

    def issue_login(self, user_id):
        if not self.settings.base_url:
            raise PortalError("portal_not_configured", 503)
        token = self.new_login_token(user_id)
        return f"{self.settings.base_url}/login#token={token}"

    def new_login_token(self, user_id):
        if user_id not in self.settings.admins:
            self._user(self.store, user_id)
        self.limit(f"login:{user_id}", 10, 300)
        token = secrets.token_urlsafe(32)
        expires = self.now() + self.settings.login_ttl
        self.store.put("portal_login_tokens", digest(token), {"user_id": user_id, "until": expires,
            "expires_at": datetime.fromtimestamp(expires, timezone.utc)})
        return token

    def exchange_login(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 150:
            raise PortalError("invalid_login", 401)
        session_token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        def operation(tx):
            login = tx.get("portal_login_tokens", digest(token))
            if not login or login["until"] <= self.now():
                raise PortalError("invalid_login", 401)
            tx.delete("portal_login_tokens", digest(token))
            until = self.now() + self.settings.session_ttl
            tx.put("portal_sessions", digest(session_token), {"user_id": login["user_id"], "csrf": csrf,
                "until": until, "expires_at": datetime.fromtimestamp(until, timezone.utc)})
            return {"token": session_token, "csrf": csrf}
        return self.store.transaction(operation)

    def session(self, token):
        item = self.store.get("portal_sessions", digest(token)) if token else None
        if not item or item["until"] <= self.now():
            raise PortalError("login_required", 401)
        return item

    def logout(self, token):
        if token:
            self.store.delete("portal_sessions", digest(token))

    def leaderboard(self):
        users = sorted(self.store.all("users"), key=lambda u: (-earned(u), -int(u.get("ref_count", 0)), int(u["user_id"])))
        return [{"rank": i + 1, "label": f"PRS · {digest(str(u['user_id']))[:6].upper()}",
                 "earned": earned(u), "referrals": int(u.get("ref_count", 0)), "user_id": u["user_id"]} for i, u in enumerate(users)]

    def profile(self, user_id):
        user = self.store.get("users", user_id)
        admin = user_id in self.settings.admins
        if not user and not admin:
            raise PortalError("registration_required", 403)
        user = user or {"user_id": user_id}
        total = earned(user)
        paid = min(total, max(0, int(user.get("paid_amount", 0))))
        ranking = self.leaderboard()
        pool = sum(row["earned"] for row in ranking)
        history = sorted([h for h in self.store.all("portal_history") if h["user_id"] == user_id], key=lambda h: h["created_at"], reverse=True)[:30]
        payments = sorted([p for p in self.store.all("portal_payments") if p["user_id"] == user_id], key=lambda p: p["created_at"], reverse=True)[:20]
        return {"user_id": user_id, "is_admin": admin, "language": user.get("lang", "fa"),
            "registered": int(user.get("verified", 0)) >= 2,
            "earned": total, "paid": paid, "unpaid": max(0, total - paid),
            "referrals": int(user.get("ref_count", 0)), "required_referrals": REQUIRED_REFERRALS,
            "daily_count": int(user.get("daily_count", 0)), "daily_reward": DAILY_REWARD,
            "daily_available_at": max(0, int(user.get("last_daily", 0)) + 86400) if user.get("last_daily") else 0,
            "wallet": user.get("wallet") or "", "rank": next((r["rank"] for r in ranking if r["user_id"] == user_id), None),
            "wallet_edits_remaining": max(0, 2 - int(user.get("submitted", 0))),
            "referral_link": f"https://t.me/{self.settings.bot_username}?start={user_id}",
            "channel_link": f"https://t.me/{self.settings.channel.lstrip('@')}",
            "campaign_total": pool, "campaign_limit": MAX_TOTAL_TOKENS_LIMIT,
            "paused": (self.store.get("bot_settings", "bot_status") or {}).get("status") == "off",
            "history": history, "payments": payments, "server_time": self.now(),
            "tickets": [self._public_ticket(t) for t in self.store.all("portal_tickets") if t["user_id"] == user_id]}

    def public_leaderboard(self, user_id):
        return [{k: v for k, v in row.items() if k != "user_id"} | {"is_me": row["user_id"] == user_id} for row in self.leaderboard()[:20]]

    def claim_daily(self, user_id):
        self._member(user_id)
        def operation(tx):
            self._enabled(tx)
            user = self._user(tx, user_id)
            if int(user.get("ref_count", 0)) < REQUIRED_REFERRALS:
                raise PortalError("referrals_required", 403, required=REQUIRED_REFERRALS)
            now = self.now()
            remaining = int(user.get("last_daily", 0)) + 86400 - now
            if remaining > 0:
                raise PortalError("daily_cooldown", 409, remaining=remaining)
            self._credit_lock(tx, DAILY_REWARD)
            user["last_daily"] = now
            user["daily_count"] = int(user.get("daily_count", 0)) + 1
            tx.put("users", user_id, user)
            self._history(tx, f"daily:{user_id}:{now}", user_id, "daily", DAILY_REWARD, "پاداش روزانه · Daily reward")
            return {"amount": DAILY_REWARD, "available_at": now + 86400}
        return self.store.transaction(operation)

    def _period(self, mission):
        now = datetime.fromtimestamp(self.now(), ZoneInfo(self.settings.timezone))
        if mission["recurrence"] == "daily":
            return now.strftime("%Y-%m-%d")
        if mission["recurrence"] == "weekly":
            year, week, _ = now.isocalendar()
            return f"{year}-W{week}"
        return "once"

    def _submission_id(self, mission, user_id):
        return digest(f"{mission['id']}:{user_id}:{self._period(mission)}")[:32]

    def missions(self, user_id):
        output = []
        for mission in sorted(self.store.all("portal_missions"), key=lambda m: m["created_at"], reverse=True):
            submission = self.store.get("portal_submissions", self._submission_id(mission, user_id)) or {}
            if not mission["active"] and not submission:
                continue
            item = {k: mission.get(k) for k in ("id", "title", "title_en", "description", "description_en", "kind", "reward", "recurrence", "ends_at", "url", "question", "question_en", "options", "options_en", "max_attempts")}
            item["status"] = submission.get("status", "available")
            if not mission["active"] and item["status"] not in ("pending", "completed"):
                item["status"] = "paused"
            item["reason"] = submission.get("reason", "")
            item["attempts_left"] = max(0, mission["max_attempts"] - submission.get("attempts", 0))
            item["remaining_places"] = max(0, min(mission["max_claims"] - mission["completed"] - mission.get("pending", 0),
                (mission["budget"] - mission["spent"] - mission.get("reserved", 0)) // mission["reward"]))
            if not submission.get("status") and mission["ends_at"] and mission["ends_at"] <= self.now():
                item["status"] = "expired"
            if item["status"] in ("available", "attempted", "rejected") and (item["attempts_left"] == 0 or item["remaining_places"] == 0):
                item["status"] = "exhausted"
            output.append(item)
        return output

    def create_mission(self, admin_id, payload):
        self.require_admin(admin_id)
        def text(name, maximum, required=False):
            value = payload.get(name, "")
            if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
                raise PortalError("invalid_mission", field=name)
            return value.strip()
        def number(name, minimum, maximum):
            value = payload.get(name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise PortalError("invalid_mission", field=name)
            return value
        kind, recurrence = payload.get("kind"), payload.get("recurrence", "once")
        if kind not in ("quiz", "manual") or recurrence not in ("once", "daily", "weekly"):
            raise PortalError("invalid_mission")
        reward = number("reward", 1, MAX_TOTAL_TOKENS_LIMIT)
        budget = number("budget", reward, MAX_TOTAL_TOKENS_LIMIT)
        claims = number("max_claims", 1, 1_000_000)
        url = text("url", 500)
        if url and (urlsplit(url).scheme != "https" or not urlsplit(url).hostname or urlsplit(url).username):
            raise PortalError("invalid_mission", field="url")
        ends = payload.get("ends_at") or 0
        if type(ends) is not int or (ends and ends <= self.now()):
            raise PortalError("invalid_mission", field="ends_at")
        mission = {"id": uuid4().hex[:20], "title": text("title", 100, True), "title_en": text("title_en", 100),
            "description": text("description", 1000, True), "description_en": text("description_en", 1000),
            "kind": kind, "recurrence": recurrence, "reward": reward, "budget": budget,
            "spent": 0, "reserved": 0, "completed": 0, "pending": 0, "max_claims": claims,
            "active": False, "ends_at": ends, "url": url, "created_at": self.now(), "created_by": admin_id,
            "question": "", "question_en": "", "options": [], "options_en": [], "answer": None, "max_attempts": 2}
        if kind == "quiz":
            options = payload.get("options", [])
            options_en = payload.get("options_en", [])
            if not isinstance(options, list) or not 2 <= len(options) <= 4 or any(not isinstance(x, str) or not x.strip() or len(x) > 160 for x in options):
                raise PortalError("invalid_mission", field="options")
            if options_en and (not isinstance(options_en, list) or len(options_en) != len(options) or any(not isinstance(x, str) or len(x) > 160 for x in options_en)):
                raise PortalError("invalid_mission", field="options_en")
            answer = payload.get("answer")
            if type(answer) is not int or not 0 <= answer < len(options):
                raise PortalError("invalid_mission", field="answer")
            mission.update(question=text("question", 500, True), question_en=text("question_en", 500),
                           options=[x.strip() for x in options], options_en=options_en, answer=answer)
        self.store.put("portal_missions", mission["id"], mission)
        return mission

    def set_mission_active(self, admin_id, mission_id, active):
        self.require_admin(admin_id)
        if type(active) is not bool:
            raise PortalError("invalid_mission")
        def operation(tx):
            mission = tx.get("portal_missions", mission_id)
            if not mission:
                raise PortalError("mission_not_found", 404)
            mission["active"] = active
            tx.put("portal_missions", mission_id, mission)
        self.store.transaction(operation)

    def _capacity(self, mission):
        if mission["spent"] + mission.get("reserved", 0) + mission["reward"] > mission["budget"] or mission["completed"] + mission.get("pending", 0) >= mission["max_claims"]:
            raise PortalError("mission_budget_exhausted", 409)

    def _award(self, tx, mission, submission, user):
        amount = submission["reward"]
        self._credit_lock(tx, amount)
        # Reuse the legacy bonus field so every existing bot report includes awards.
        user["manual_bonus_tokens"] = int(user.get("manual_bonus_tokens", 0)) + amount
        tx.put("users", user["user_id"], user)
        mission["spent"] += amount
        mission["completed"] += 1
        submission["status"] = "completed"
        submission["reviewed_at"] = self.now()
        self._history(tx, f"mission:{submission['id']}", user["user_id"], "mission", amount, mission["title"])

    def submit_mission(self, user_id, mission_id, payload):
        self._member(user_id)
        def operation(tx):
            self._enabled(tx)
            user = self._user(tx, user_id)
            mission = tx.get("portal_missions", mission_id)
            if not mission or not mission["active"]:
                raise PortalError("mission_not_found", 404)
            if mission["ends_at"] and mission["ends_at"] <= self.now():
                raise PortalError("mission_expired", 409)
            sid = self._submission_id(mission, user_id)
            submission = tx.get("portal_submissions", sid) or {"id": sid, "mission_id": mission_id, "user_id": user_id,
                "period": self._period(mission), "attempts": 0, "reward": mission["reward"], "created_at": self.now()}
            if submission.get("status") in ("completed", "pending"):
                raise PortalError("already_completed", 409)
            if submission["attempts"] >= mission["max_attempts"]:
                raise PortalError("attempts_exhausted", 409)
            self._capacity(mission)
            if mission["kind"] == "quiz":
                answer = payload.get("answer")
                if type(answer) is not int or not 0 <= answer < len(mission["options"]):
                    raise PortalError("answer_required")
                submission["attempts"] += 1
                if answer == mission["answer"]:
                    self._award(tx, mission, submission, user)
                else:
                    submission["status"] = "attempted"
            else:
                evidence = payload.get("evidence", "")
                if not isinstance(evidence, str) or not 10 <= len(evidence.strip()) <= 1500:
                    raise PortalError("evidence_required")
                submission.update(status="pending", evidence=evidence.strip(), attempts=submission["attempts"] + 1, reason="")
                mission["pending"] += 1
                mission["reserved"] += mission["reward"]
            tx.put("portal_missions", mission_id, mission)
            tx.put("portal_submissions", sid, submission)
            return {"status": submission["status"], "amount": mission["reward"] if submission["status"] == "completed" else 0,
                    "attempts_left": max(0, mission["max_attempts"] - submission["attempts"])}
        return self.store.transaction(operation)

    def review_submission(self, admin_id, submission_id, approve, reason=""):
        self.require_admin(admin_id)
        if type(approve) is not bool or not isinstance(reason, str) or len(reason) > 400:
            raise PortalError("invalid_review")
        if not approve and len(reason.strip()) < 3:
            raise PortalError("reason_required")
        def operation(tx):
            submission = tx.get("portal_submissions", submission_id)
            if not submission or submission["status"] != "pending":
                raise PortalError("already_reviewed", 409)
            mission = tx.get("portal_missions", submission["mission_id"])
            mission["pending"] -= 1
            mission["reserved"] -= submission["reward"]
            if approve:
                self._award(tx, mission, submission, self._user(tx, submission["user_id"]))
            else:
                submission.update(status="rejected", reason=reason.strip(), reviewed_at=self.now())
            submission["reviewed_by"] = admin_id
            tx.put("portal_missions", mission["id"], mission)
            tx.put("portal_submissions", submission_id, submission)
        self.store.transaction(operation)

    def update_wallet(self, user_id, wallet):
        if not isinstance(wallet, str) or not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet.strip()) or int(wallet.strip(), 16) == 0:
            raise PortalError("invalid_wallet")
        self._member(user_id)
        def operation(tx):
            user = self._user(tx, user_id)
            if int(user.get("ref_count", 0)) < REQUIRED_REFERRALS:
                raise PortalError("referrals_required", 403, required=REQUIRED_REFERRALS)
            if tx.get("portal_open_payments", user_id):
                raise PortalError("wallet_locked", 409)
            submitted = int(user.get("submitted", 0))
            if submitted >= 2:
                raise PortalError("wallet_edit_limit", 409)
            user.update(wallet=wallet.strip(), submitted=1 if submitted == 0 else 2)
            tx.put("users", user_id, user)
        self.store.transaction(operation)

    def request_payment(self, user_id):
        self._member(user_id)
        def operation(tx):
            self._enabled(tx)
            user = self._user(tx, user_id)
            if user.get("ref_count", 0) < REQUIRED_REFERRALS:
                raise PortalError("referrals_required", 403, required=REQUIRED_REFERRALS)
            if not user.get("wallet"):
                raise PortalError("wallet_required")
            if tx.get("portal_open_payments", user_id):
                raise PortalError("payment_pending", 409)
            amount = earned(user) - int(user.get("paid_amount", 0))
            if amount <= 0:
                raise PortalError("nothing_to_pay", 409)
            pid = uuid4().hex
            payment = {"id": pid, "user_id": user_id, "amount": amount, "wallet": user["wallet"],
                       "status": "pending", "created_at": self.now(), "tx_hash": "", "reason": ""}
            # A real write to the same user document makes a simultaneous wallet
            # edit conflict/retry, avoiding snapshot-isolation write skew.
            user["portal_payment_version"] = int(user.get("portal_payment_version", 0)) + 1
            tx.put("users", user_id, user)
            tx.put("portal_payments", pid, payment)
            tx.put("portal_open_payments", user_id, {"payment_id": pid})
            return payment
        return self.store.transaction(operation)

    def admin_update_wallet(self, admin_id, user_id, wallet):
        self.require_admin(admin_id)
        if not isinstance(wallet, str) or not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet.strip()) or int(wallet.strip(), 16) == 0:
            raise PortalError("invalid_wallet")
        def operation(tx):
            user = tx.get("users", user_id)
            if not user:
                raise PortalError("registration_required", 404)
            if tx.get("portal_open_payments", user_id):
                raise PortalError("wallet_locked", 409)
            user.update(wallet=wallet.strip(), submitted=1)
            tx.put("users", user_id, user)
        self.store.transaction(operation)

    def review_payment(self, admin_id, payment_id, approve, tx_hash="", reason=""):
        self.require_admin(admin_id)
        if type(approve) is not bool or not isinstance(reason, str) or len(reason) > 400:
            raise PortalError("invalid_review")
        if approve and (not isinstance(tx_hash, str) or not re.fullmatch(r"0x[a-fA-F0-9]{64}", tx_hash.strip())):
            raise PortalError("transaction_required")
        if not approve and len(reason.strip()) < 3:
            raise PortalError("reason_required")
        def operation(tx):
            payment = tx.get("portal_payments", payment_id)
            if not payment or payment["status"] != "pending":
                raise PortalError("already_reviewed", 409)
            if approve:
                user = self._user(tx, payment["user_id"])
                if payment["amount"] > earned(user) - int(user.get("paid_amount", 0)):
                    raise PortalError("payment_balance_changed", 409)
                receipt = tx_hash.strip().lower()
                if tx.get("portal_payment_receipts", receipt):
                    raise PortalError("transaction_used", 409)
                tx.put("portal_payment_receipts", receipt, {"payment_id": payment_id})
                user["paid_amount"] = int(user.get("paid_amount", 0)) + payment["amount"]
                user["paid"] = int(user["paid_amount"] >= earned(user))
                tx.put("users", user["user_id"], user)
                payment.update(status="recorded", tx_hash=tx_hash.strip())
                self._history(tx, f"payment:{payment_id}", user["user_id"], "payment", -payment["amount"], "ثبت پرداخت · Payment recorded")
            else:
                payment.update(status="rejected", reason=reason.strip())
            payment.update(reviewed_at=self.now(), reviewed_by=admin_id)
            tx.put("portal_payments", payment_id, payment)
            tx.delete("portal_open_payments", payment["user_id"])
        self.store.transaction(operation)

    def ticket(self, user_id, message):
        if not isinstance(message, str) or not 10 <= len(message.strip()) <= 1500:
            raise PortalError("message_required")
        self.limit(f"ticket:{user_id}", 5, 3600)
        tid = uuid4().hex
        item = {"id": tid, "user_id": user_id, "message": message.strip(), "reply": "", "status": "open", "created_at": self.now()}
        self.store.put("portal_tickets", tid, item)
        return item

    @staticmethod
    def _public_ticket(ticket):
        return {k: ticket.get(k) for k in ("id", "message", "reply", "status", "created_at")}

    def reply_ticket(self, admin_id, ticket_id, reply):
        self.require_admin(admin_id)
        if not isinstance(reply, str) or not 3 <= len(reply.strip()) <= 1500:
            raise PortalError("message_required")
        def operation(tx):
            ticket = tx.get("portal_tickets", ticket_id)
            if not ticket:
                raise PortalError("ticket_not_found", 404)
            ticket.update(reply=reply.strip(), status="resolved", reviewed_by=admin_id)
            tx.put("portal_tickets", ticket_id, ticket)
        self.store.transaction(operation)

    def require_admin(self, user_id):
        if user_id not in self.settings.admins:
            raise PortalError("admin_required", 403)

    def admin_overview(self, user_id):
        self.require_admin(user_id)
        return {"missions": sorted(self.store.all("portal_missions"), key=lambda m: m["created_at"], reverse=True),
            "submissions": [s for s in self.store.all("portal_submissions") if s["status"] == "pending"],
            "payments": [p for p in self.store.all("portal_payments") if p["status"] == "pending"],
            "tickets": [t for t in self.store.all("portal_tickets") if t["status"] == "open"],
            "users": len(self.store.all("users"))}


def build_service(settings=None, database=None, member_check=None):
    settings = settings or Settings.from_env()
    if settings.demo:
        return PortalService(MemoryStore(), settings, lambda uid: True)
    if database is None:
        if not settings.mongo_url:
            raise RuntimeError("MONGO_URL is required")
        from pymongo import MongoClient
        database = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000)[settings.database]
    return PortalService(MongoStore(database), settings, member_check)
