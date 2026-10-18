import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from .settings import (BASE_REWARD, DAILY_REWARD, EXTRA_REWARD, MAX_TOTAL_TOKENS_LIMIT,
                       REQUIRED_REFERRALS, Settings)
from .store import MemoryStore, MongoStore
from .features import PhaseTwoMixin
from .settings import CAMPAIGN_TIMEZONE


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

MIN_WITHDRAWAL = 20_000


def _telegram_error(payload, http_status=0):
    code = payload.get("error_code", http_status)
    description = str(payload.get("description", "")).lower()
    if code in (401, 404):
        error = "telegram_token_invalid"
    elif code == 403 or (code == 400 and any(text in description for text in (
        "chat not found", "chat_id is empty", "not enough rights", "not a member",
        "member list is inaccessible", "chat_admin_required", "administrator rights",
    ))):
        error = "telegram_channel_access"
    elif code == 429:
        error = "telegram_rate_limited"
    else:
        error = "telegram_unavailable"
    # Log only a fixed category, never Telegram's URL, description or token.
    logging.getLogger(__name__).warning("Telegram membership check failed: %s", error)
    raise PortalError(error, 503) from None


def _telegram_call(settings, method, parameters=None):
    token = settings.bot_token.strip()
    if not token:
        raise PortalError("telegram_token_invalid", 503)
    try:
        data = urlencode(parameters or {}).encode("utf-8")
        with urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=8) as response:
            payload = json.load(response)
    except HTTPError as error:
        try:
            payload = json.loads(error.read(16384))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        _telegram_error(payload, error.code)
    except Exception:
        raise PortalError("telegram_unavailable", 503) from None
    if not isinstance(payload, dict):
        raise PortalError("telegram_unavailable", 503)
    if payload.get("ok") is not True:
        _telegram_error(payload)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise PortalError("telegram_unavailable", 503)
    return result


def telegram_membership(settings, user_id):
    member = _telegram_call(settings, "getChatMember", {"chat_id": settings.channel.strip(), "user_id": user_id})
    status = member.get("status")
    if status in ("member", "administrator", "creator"):
        return True
    if status == "restricted":
        return member.get("is_member") is True
    if status in ("left", "kicked"):
        return False
    raise PortalError("telegram_unavailable", 503)


class PortalService(PhaseTwoMixin):
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
        # The existing Telegram registration flow stores verified=1 on success.
        if not user or int(user.get("verified", 0)) < 1:
            raise PortalError("registration_required", 403)
        if user.get("portal_suspended"):
            raise PortalError("account_suspended", 403)
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
        reserved = self.mining_config(tx)["reserved"]
        if sum(earned(u) for u in tx.all("users")) + reserved + amount > MAX_TOTAL_TOKENS_LIMIT:
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
        self.check_access(user_id)
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
            if (tx.get("users", login["user_id"]) or {}).get("portal_suspended"):
                raise PortalError("account_suspended", 403)
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
        self.check_access(item["user_id"])
        return item

    def logout(self, token):
        if token:
            self.store.delete("portal_sessions", digest(token))

    def leaderboard(self):
        users = sorted([u for u in self.store.all("users") if not u.get("portal_suspended") and int(u.get("verified", 0)) >= 1], key=lambda u: (-earned(u), -int(u.get("ref_count", 0)), int(u["user_id"])))
        return [{"rank": i + 1, "label": f"PRS · {digest(str(u['user_id']))[:6].upper()}",
                 "earned": earned(u), "referrals": int(u.get("ref_count", 0)), "user_id": u["user_id"]} for i, u in enumerate(users)]

    def profile(self, user_id):
        self.check_access(user_id)
        user = self.store.get("users", user_id)
        admin = user_id in self.settings.admins
        if not user and not admin:
            raise PortalError("registration_required", 403)
        user = user or {"user_id": user_id}
        total = earned(user)
        paid = min(total, max(0, int(user.get("paid_amount", 0))))
        ranking = self.leaderboard()
        pool = sum(earned(u) for u in self.store.all("users"))
        history = sorted([h for h in self.store.all("portal_history") if h["user_id"] == user_id], key=lambda h: h["created_at"], reverse=True)[:30]
        payments = sorted([p for p in self.store.all("portal_payments") if p["user_id"] == user_id], key=lambda p: p["created_at"], reverse=True)[:20]
        return {"user_id": user_id, "is_admin": admin, "language": user.get("lang", "fa"),
            "registered": int(user.get("verified", 0)) >= 1,
            "earned": total, "paid": paid, "unpaid": max(0, total - paid),
            "referrals": int(user.get("ref_count", 0)), "required_referrals": REQUIRED_REFERRALS,
            "min_withdrawal": MIN_WITHDRAWAL,
            "daily_count": int(user.get("daily_count", 0)), "daily_reward": DAILY_REWARD,
            "daily_available_at": max(0, int(user.get("last_daily", 0)) + 86400) if user.get("last_daily") else 0,
            "wallet": user.get("wallet") or "", "rank": next((r["rank"] for r in ranking if r["user_id"] == user_id), None),
            "instagram": user.get("instagram") or "", "twitter": user.get("twitter") or "",
            "wallet_edits_remaining": max(0, 2 - int(user.get("submitted", 0))),
            "referral_link": f"https://t.me/{self.settings.bot_username}?start={user_id}",
            "channel_link": f"https://t.me/{self.settings.channel.lstrip('@')}",
            "campaign_total": pool, "campaign_limit": MAX_TOTAL_TOKENS_LIMIT,
            "paused": (self.store.get("bot_settings", "bot_status") or {}).get("status") == "off",
            "history": history, "payments": payments, "server_time": self.now(),
            "withdrawals_enabled": self.campaign_controls()["withdrawals_enabled"],
            "timezone": CAMPAIGN_TIMEZONE, "mining": self.mining_status(user_id, user),
            "announcement": (self.store.get("portal_state", "announcement") or {}).get("text", ""),
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
            if mission.get("archived"):
                continue
            submission = self.store.get("portal_submissions", self._submission_id(mission, user_id)) or {}
            if not mission["active"] and not submission:
                continue
            item = {k: mission.get(k) for k in ("id", "title", "title_en", "description", "description_en", "kind", "reward", "recurrence", "ends_at", "url", "question", "question_en", "options", "options_en", "max_attempts")}
            if mission["kind"] == "quiz":
                item["max_attempts"] = 1
            item["status"] = submission.get("status", "available")
            if not mission["active"] and item["status"] not in ("pending", "completed"):
                item["status"] = "paused"
            item["reason"] = submission.get("reason", "")
            item["attempts_left"] = max(0, (1 if mission["kind"] == "quiz" else mission["max_attempts"]) - submission.get("attempts", 0))
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
        if payload.get("ends_at_tehran"):
            try:
                local_end = datetime.fromisoformat(payload["ends_at_tehran"])
                if local_end.tzinfo is not None:
                    raise ValueError("Expected a Tehran wall-clock date")
                ends = int(local_end.replace(tzinfo=ZoneInfo(CAMPAIGN_TIMEZONE)).timestamp())
            except (ValueError, TypeError):
                raise PortalError("invalid_mission", field="ends_at") from None
        if type(ends) is not int or (ends and ends <= self.now()):
            raise PortalError("invalid_mission", field="ends_at")
        mission = {"id": uuid4().hex[:20], "title": text("title", 100, True), "title_en": text("title_en", 100),
            "description": text("description", 1000, True), "description_en": text("description_en", 1000),
            "kind": kind, "recurrence": recurrence, "reward": reward, "budget": budget,
            "spent": 0, "reserved": 0, "completed": 0, "pending": 0, "max_claims": claims,
            "active": False, "ends_at": ends, "url": url, "created_at": self.now(), "created_by": admin_id,
            "question": "", "question_en": "", "options": [], "options_en": [], "answer": None, "max_attempts": 1}
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
        def operation(tx):
            tx.put("portal_missions", mission["id"], mission)
            self._audit(tx, admin_id, "create_mission", mission["id"], {"title": mission["title"], "reward": reward, "budget": budget})
        self.store.transaction(operation)
        return mission

    def set_mission_active(self, admin_id, mission_id, active):
        self.require_admin(admin_id)
        if type(active) is not bool:
            raise PortalError("invalid_mission")
        def operation(tx):
            mission = tx.get("portal_missions", mission_id)
            if not mission:
                raise PortalError("mission_not_found", 404)
            if active and mission.get("archived"):
                raise PortalError("mission_archived", 409)
            mission["active"] = active
            tx.put("portal_missions", mission_id, mission)
            self._audit(tx, admin_id, "mission_active", mission_id, {"active": active})
        self.store.transaction(operation)

    def archive_mission(self, admin_id, mission_id, archived):
        self.require_admin(admin_id)
        if type(archived) is not bool:
            raise PortalError("invalid_mission")
        def operation(tx):
            mission = tx.get("portal_missions", mission_id)
            if not mission:
                raise PortalError("mission_not_found", 404)
            if bool(mission.get("archived")) == archived:
                return
            # Keep submissions, reserved reviews, rewards and payment history.
            # Restoring requires an explicit activation before new submissions.
            mission.update(archived=archived, active=False)
            if archived:
                mission.update(archived_at=self.now(), archived_by=admin_id)
            tx.put("portal_missions", mission_id, mission)
            self._audit(tx, admin_id, "archive_mission" if archived else "restore_mission", mission_id)
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
            if not mission or not mission["active"] or mission.get("archived"):
                raise PortalError("mission_not_found", 404)
            if mission["ends_at"] and mission["ends_at"] <= self.now():
                raise PortalError("mission_expired", 409)
            sid = self._submission_id(mission, user_id)
            submission = tx.get("portal_submissions", sid) or {"id": sid, "mission_id": mission_id, "user_id": user_id,
                "period": self._period(mission), "attempts": 0, "reward": mission["reward"], "created_at": self.now()}
            if submission.get("status") in ("completed", "pending"):
                raise PortalError("already_completed", 409)
            if submission["attempts"] >= (1 if mission["kind"] == "quiz" else mission["max_attempts"]):
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
                    "attempts_left": max(0, (1 if mission["kind"] == "quiz" else mission["max_attempts"]) - submission["attempts"])}
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
            self._audit(tx, admin_id, "review_submission", submission_id, {"approve": approve, "reason": reason.strip()})
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

    def update_social_links(self, user_id, instagram, twitter):
        if not isinstance(instagram, str) or not isinstance(twitter, str) or len(instagram) > 300 or len(twitter) > 300:
            raise PortalError("invalid_request")
        def valid(value, hosts):
            if not value.strip():
                return True
            from urllib.parse import urlsplit
            candidate = value.strip()
            if not candidate.startswith(("https://", "http://")):
                candidate = "https://" + candidate.lstrip("/")
            parts = urlsplit(candidate)
            return parts.scheme == "https" and (parts.hostname or "").lower() in hosts and bool(parts.path.strip("/")) and not parts.username and not parts.password
        if not valid(instagram, {"instagram.com", "www.instagram.com"}) or not valid(twitter, {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}):
            raise PortalError("invalid_request")
        self._member(user_id)
        def operation(tx):
            user = self._user(tx, user_id)
            user["instagram"] = instagram.strip()
            user["twitter"] = twitter.strip()
            tx.put("users", user_id, user)
        self.store.transaction(operation)

    def request_payment(self, user_id, amount=None):
        # Full-balance requests only. Reject partial amounts even from old clients.
        if amount is not None and type(amount) is not int:
            raise PortalError("invalid_payment_amount")
        self._member(user_id)
        def operation(tx):
            self._enabled(tx)
            if not (tx.get("portal_state", "withdrawals") or {}).get("enabled", True):
                raise PortalError("withdrawals_disabled", 403)
            user = self._user(tx, user_id)
            if user.get("ref_count", 0) < REQUIRED_REFERRALS:
                raise PortalError("referrals_required", 403, required=REQUIRED_REFERRALS)
            if not user.get("wallet"):
                raise PortalError("wallet_required")
            if tx.get("portal_open_payments", user_id):
                raise PortalError("payment_pending", 409)
            balance = earned(user) - int(user.get("paid_amount", 0))
            if balance < MIN_WITHDRAWAL:
                raise PortalError("nothing_to_pay", 409)
            if amount is not None and amount != balance:
                raise PortalError("full_balance_required", 400)
            requested = balance
            pid = uuid4().hex
            payment = {"id": pid, "user_id": user_id, "amount": requested, "wallet": user["wallet"],
                       "status": "pending", "created_at": self.now(), "tx_hash": "", "reason": ""}
            # A real write to the same user document makes a simultaneous wallet
            # edit conflict/retry, avoiding snapshot-isolation write skew.
            user["portal_payment_version"] = int(user.get("portal_payment_version", 0)) + 1
            tx.put("users", user_id, user)
            tx.put("portal_payments", pid, payment)
            tx.put("portal_open_payments", user_id, {"payment_id": pid})
            return payment
        return self.store.transaction(operation)

    def payout_payments(self, admin_id, payment_ids):
        """Send approved pending withdrawals from the configured BSC signer."""
        self.require_admin(admin_id)
        if not isinstance(payment_ids, list) or not 1 <= len(payment_ids) <= 20 or any(not isinstance(x, str) or len(x) > 64 for x in payment_ids) or len(set(payment_ids)) != len(payment_ids):
            raise PortalError("invalid_request")
        if self.settings.demo:
            raise PortalError("payout_unavailable", 503)
        if not (self.settings.bsc_rpc_url and self.settings.payout_private_key):
            raise PortalError("payout_not_configured", 503)
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.settings.bsc_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected() or int(w3.eth.chain_id) != 56:
                raise ValueError("wrong network")
            account = w3.eth.account.from_key(self.settings.payout_private_key)
            token_address = Web3.to_checksum_address(self.settings.prs_token_address)
            token = w3.eth.contract(address=token_address, abi=[
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
                {"anonymous": False, "inputs": [{"indexed": True, "name": "from", "type": "address"}, {"indexed": True, "name": "to", "type": "address"}, {"indexed": False, "name": "value", "type": "uint256"}], "name": "Transfer", "type": "event"},
            ])
            decimals = int(token.functions.decimals().call())
            if decimals != self.settings.prs_token_decimals:
                raise ValueError("token decimals mismatch")
        except PortalError:
            raise
        except Exception:
            raise PortalError("payout_unavailable", 503) from None

        def transfer_confirmed(receipt, recipient, amount):
            signature = bytes(w3.keccak(text="Transfer(address,address,uint256)"))
            recipient_bytes = bytes.fromhex(recipient[2:]).lower()
            for log in receipt.logs:
                topics = [bytes.fromhex(x[2:]) if isinstance(x, str) else bytes(x) for x in log.get("topics", [])]
                if (str(log.get("address", "")).lower() == token_address.lower() and len(topics) >= 3
                        and topics[0] == signature and topics[2][-20:].lower() == recipient_bytes):
                    data = log.get("data", "0x0")
                    value = int(data, 16) if isinstance(data, str) else int.from_bytes(bytes(data), "big")
                    if value == amount:
                        return True
            return False

        lease_id = uuid4().hex
        def acquire(store_tx):
            lease = store_tx.get("portal_state", "onchain_payout_lease") or {}
            if int(lease.get("expires_at", 0)) > self.now():
                raise PortalError("payout_in_progress", 409)
            store_tx.put("portal_state", "onchain_payout_lease", {"id": lease_id, "expires_at": self.now() + 7200})
        self.store.transaction(acquire)
        try:
            results = []
            for payment_id in payment_ids:
                tx_hash = ""
                payment = self.store.get("portal_payments", payment_id)
                if payment and payment.get("status") == "sending" and payment.get("tx_hash"):
                    try:
                        receipt = w3.eth.get_transaction_receipt(payment["tx_hash"])
                        if int(receipt.status) == 1 and transfer_confirmed(receipt, payment["wallet"], int(payment["amount"]) * (10 ** decimals)):
                            self._finalize_onchain_payment(admin_id, payment_id, payment["tx_hash"], int(receipt.blockNumber))
                            results.append({"payment_id": payment_id, "status": "paid", "tx_hash": payment["tx_hash"]})
                        else:
                            self._reset_failed_onchain_payment(admin_id, payment_id, payment["tx_hash"])
                            results.append({"payment_id": payment_id, "status": "failed", "tx_hash": payment["tx_hash"]})
                    except Exception:
                        results.append({"payment_id": payment_id, "status": "sending", "tx_hash": payment["tx_hash"]})
                    continue
                if not payment or payment.get("status") != "pending":
                    results.append({"payment_id": payment_id, "status": "skipped"})
                    continue
                wallet = payment.get("wallet", "")
                if not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet) or int(payment.get("amount", 0)) < MIN_WITHDRAWAL:
                    results.append({"payment_id": payment_id, "status": "invalid_request"})
                    continue
                # Reserve before broadcasting. An uncertain RPC response stays locked
                # for reconciliation and cannot be accidentally paid a second time.
                nonce = w3.eth.get_transaction_count(account.address, "pending")
                amount_wei = int(payment["amount"]) * (10 ** decimals)
                try:
                    tx = token.functions.transfer(Web3.to_checksum_address(wallet), amount_wei).build_transaction({
                        "from": account.address, "nonce": nonce, "chainId": 56,
                        "gas": 100000, "gasPrice": w3.eth.gas_price,
                    })
                    signed = account.sign_transaction(tx)
                    tx_hash = Web3.to_hex(signed.hash)
                    def mark_sending(store_tx):
                        current = store_tx.get("portal_payments", payment_id)
                        if not current or current.get("status") != "pending":
                            raise PortalError("already_reviewed", 409)
                        current.update(status="sending", tx_hash=tx_hash, reviewed_by=admin_id,
                                       payout_started_at=self.now())
                        store_tx.put("portal_payments", payment_id, current)
                        self._audit(store_tx, admin_id, "payout_started", payment_id,
                                    {"amount": current["amount"], "tx_hash": tx_hash})
                    self.store.transaction(mark_sending)
                    try:
                        raw_transaction = getattr(signed, "raw_transaction", None) or signed.rawTransaction
                        sent = w3.eth.send_raw_transaction(raw_transaction)
                    except Exception:
                        # The RPC may have accepted the raw transaction before the
                        # connection failed; resolve by its deterministic hash.
                        try:
                            sent = w3.eth.get_transaction(tx_hash)
                        except Exception:
                            results.append({"payment_id": payment_id, "status": "sending", "tx_hash": tx_hash})
                            return {"results": results}
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180, poll_latency=3)
                    if int(receipt.status) != 1 or not transfer_confirmed(receipt, wallet, amount_wei):
                        self._reset_failed_onchain_payment(admin_id, payment_id, tx_hash)
                        results.append({"payment_id": payment_id, "status": "failed", "tx_hash": tx_hash})
                        continue
                    self._finalize_onchain_payment(admin_id, payment_id, tx_hash, int(receipt.blockNumber))
                    results.append({"payment_id": payment_id, "status": "paid", "tx_hash": tx_hash})
                except PortalError:
                    raise
                except Exception:
                    current = self.store.get("portal_payments", payment_id) or {}
                    results.append({"payment_id": payment_id,
                                    "status": "sending" if current.get("status") == "sending" else "failed",
                                    "tx_hash": current.get("tx_hash", "")})
            return {"results": results}
        finally:
            def release(store_tx):
                lease = store_tx.get("portal_state", "onchain_payout_lease") or {}
                if lease.get("id") == lease_id:
                    store_tx.delete("portal_state", "onchain_payout_lease")
            self.store.transaction(release)

    def _reset_failed_onchain_payment(self, admin_id, payment_id, tx_hash):
        def operation(tx):
            payment = tx.get("portal_payments", payment_id)
            if payment and payment.get("status") == "sending" and payment.get("tx_hash", "").lower() == tx_hash.lower():
                payment["last_failed_tx_hash"] = tx_hash
                payment.update(status="pending", tx_hash="")
                tx.put("portal_payments", payment_id, payment)
                self._audit(tx, admin_id, "payout_reverted", payment_id, {"tx_hash": tx_hash})
        self.store.transaction(operation)

    def _finalize_onchain_payment(self, admin_id, payment_id, tx_hash, block_number):
        def operation(tx):
            payment = tx.get("portal_payments", payment_id)
            if not payment:
                raise PortalError("user_not_found", 404)
            if payment.get("status") == "recorded" and payment.get("tx_hash", "").lower() == tx_hash.lower():
                return
            if payment.get("status") != "sending" or payment.get("tx_hash", "").lower() != tx_hash.lower():
                raise PortalError("payment_balance_changed", 409)
            user = tx.get("users", payment["user_id"])
            if not user or payment["amount"] > earned(user) - int(user.get("paid_amount", 0)):
                raise PortalError("payment_balance_changed", 409)
            receipt = tx_hash.lower()
            if tx.get("portal_payment_receipts", receipt):
                raise PortalError("transaction_used", 409)
            tx.put("portal_payment_receipts", receipt, {"payment_id": payment_id})
            user["paid_amount"] = int(user.get("paid_amount", 0)) + int(payment["amount"])
            user["paid"] = int(user["paid_amount"] >= earned(user))
            tx.put("users", user["user_id"], user)
            payment.update(status="recorded", tx_hash=tx_hash, reviewed_at=self.now(),
                           block_number=block_number)
            tx.put("portal_payments", payment_id, payment)
            tx.delete("portal_open_payments", payment["user_id"])
            # Durable outbox: the bot worker sends the success notice after the
            # payment transaction commits. This keeps a Telegram outage from
            # undoing a confirmed on-chain transfer.
            notification_id = f"payment-success:{payment_id}"
            if not tx.get("portal_payment_notifications", notification_id):
                tx.put("portal_payment_notifications", notification_id, {
                    "id": notification_id, "payment_id": payment_id,
                    "user_id": user["user_id"], "amount": int(payment["amount"]),
                    "tx_hash": tx_hash, "status": "pending", "attempts": 0,
                    "created_at": self.now(), "retry_at": self.now(),
                })
            self._history(tx, f"payment:{payment_id}", user["user_id"], "payment", -int(payment["amount"]), "پرداخت تأییدشده روی بلاکچین · On-chain payment confirmed")
            self._audit(tx, admin_id, "payout_confirmed", payment_id,
                        {"amount": payment["amount"], "tx_hash": tx_hash, "block_number": block_number})
        self.store.transaction(operation)

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
            self._audit(tx, admin_id, "update_wallet", user_id, {"wallet": wallet.strip()})
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
            self._audit(tx, admin_id, "review_payment", payment_id, {"approve": approve, "amount": payment["amount"], "tx_hash": payment["tx_hash"], "reason": reason.strip()})
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
            ticket["reviewed_at"] = self.now()
            tx.put("portal_tickets", ticket_id, ticket)
            self._audit(tx, admin_id, "reply_ticket", ticket_id)
        self.store.transaction(operation)

    def require_admin(self, user_id):
        if user_id not in self.settings.admins:
            raise PortalError("admin_required", 403)

    def admin_telegram_status(self, user_id):
        self.require_admin(user_id)
        result = {"ok": False, "channel": self.settings.channel,
                  "configured_bot_username": self.settings.bot_username}
        try:
            bot = _telegram_call(self.settings, "getMe")
            result["bot_username"] = bot.get("username", "")
            if str(bot.get("username", "")).casefold() != self.settings.bot_username.strip().lstrip("@").casefold():
                raise PortalError("telegram_bot_mismatch", 503)
            member = _telegram_call(self.settings, "getChatMember", {
                "chat_id": self.settings.channel.strip(), "user_id": bot["id"]})
            result["bot_status"] = member.get("status", "unknown")
            if member.get("status") not in ("administrator", "creator"):
                raise PortalError("telegram_bot_not_admin", 503)
            result["user_is_member"] = telegram_membership(self.settings, user_id)
            result["ok"] = True
        except PortalError as error:
            result["error"] = error.code
        return result

    def admin_overview(self, user_id):
        self.require_admin(user_id)
        users = self.store.all("users")
        payments = self.store.all("portal_payments")
        mining = self.mining_config()
        return {"missions": sorted(self.store.all("portal_missions"), key=lambda m: m["created_at"], reverse=True),
            "submissions": [s for s in self.store.all("portal_submissions") if s["status"] == "pending"],
            "payments": [p for p in self.store.all("portal_payments") if p["status"] in ("pending", "sending")],
            "tickets": [t for t in self.store.all("portal_tickets") if t["status"] == "open"],
            "users": len([u for u in users if int(u.get("verified", 0)) >= 1]),
            "stats": {"earned": sum(earned(u) for u in users), "paid": sum(int(u.get("paid_amount", 0)) for u in users),
                      "suspended": sum(bool(u.get("portal_suspended")) for u in users),
                      "active_mining": sum(c.get("status") == "active" for c in self.store.all("portal_mining")),
                      "mining_spent": mining["spent"], "mining_reserved": mining["reserved"],
                      "campaign_limit": MAX_TOTAL_TOKENS_LIMIT},
            "controls": self.campaign_controls(), "user_page": self.admin_users(user_id),
            "recent_payments": sorted(payments, key=lambda p: p["created_at"], reverse=True)[:50],
            "audit": sorted(self.store.all("portal_audit"), key=lambda a: a["created_at"], reverse=True)[:50]}


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
