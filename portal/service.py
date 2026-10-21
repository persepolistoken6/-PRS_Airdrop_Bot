import hashlib
import json
import logging
import re
import secrets
import threading
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
# A confirmed channel membership is reused for page views for this long.
# Reward, wallet and payment actions still ask Telegram directly.
MEMBER_CACHE_SECONDS = 600
# The running reward total is recounted from all users this often, which also
# absorbs changes made by legacy bot paths outside the portal service.
CREDIT_REBUILD_SECONDS = 300
EARNED_FIELDS = ("user_id", "ref_count", "daily_count", "bonus_tokens", "manual_bonus_tokens")
BOARD_FIELDS = EARNED_FIELDS + ("verified", "portal_suspended")


# Wallet payouts: wait this long after signing starts before a cancel, so a
# transaction that was just broadcast has time to be mined, and search at most
# this many blocks back for a transfer whose hash the browser lost.
PAYOUT_CANCEL_SETTLE_SECONDS = 90
PAYOUT_SCAN_MAX_BLOCKS = 400_000


def _expires(seconds_from_epoch):
    return datetime.fromtimestamp(seconds_from_epoch, timezone.utc)


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
    def __init__(self, store, settings, member_check=None, clock=time.time, cache_seconds=60):
        self.store, self.settings, self.clock = store, settings, clock
        self.member_check = member_check or (lambda uid: telegram_membership(settings, uid))
        # Per-process leaderboard snapshot; 0 disables caching (demo and tests).
        self.cache_seconds = cache_seconds
        self._board = None
        self._board_lock = threading.Lock()

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

    def _member(self, user_id, fresh=True):
        """Check channel membership.

        fresh=False (every page view) reuses a recent positive answer so the
        site does not call Telegram on each request with the bot's own token.
        Reward and payment actions keep fresh=True.
        """
        now = self.now()
        if not fresh:
            cached = self.store.get("portal_member_cache", user_id)
            if cached and int(cached.get("until", 0)) > now:
                return
        if not self.member_check(user_id):
            self.store.delete("portal_member_cache", user_id)
            raise PortalError("membership_required", 403)
        until = now + MEMBER_CACHE_SECONDS
        self.store.put("portal_member_cache", user_id, {"until": until, "expires_at": _expires(until)})

    def _credit_lock(self, tx, amount, commit=True):
        """Check (and by default record) new rewards against the campaign cap.

        One counter document replaces the old full scan of every user inside
        each reward transaction. All awards still serialize on this document,
        so the cap cannot be overshot by concurrent bot and web workers.
        """
        now = self.now()
        counter = tx.get("portal_state", "credit_total")
        if not counter or now - int(counter.get("rebuilt_at", 0)) >= CREDIT_REBUILD_SECONDS:
            counter = {"total": sum(earned(u) for u in tx.scan("users", EARNED_FIELDS)), "rebuilt_at": now,
                       "sequence": int((counter or {}).get("sequence", 0))}
        reserved = self.mining_config(tx)["reserved"]
        if counter["total"] + reserved + amount > MAX_TOTAL_TOKENS_LIMIT:
            raise PortalError("campaign_budget_exhausted", 409)
        if commit:
            counter["total"] += amount
        counter["sequence"] = int(counter.get("sequence", 0)) + 1
        tx.put("portal_state", "credit_total", counter)

    def _board_snapshot(self):
        """Ranking, campaign total and top rows, recomputed at most once per cache window."""
        with self._board_lock:
            now = self.now()
            if self._board and now - self._board["at"] < self.cache_seconds:
                return self._board
            users = [u for u in self.store.scan("users", BOARD_FIELDS) if u.get("user_id") is not None]
            pool = sum(earned(u) for u in users)
            ranked = sorted((u for u in users if not u.get("portal_suspended") and int(u.get("verified", 0) or 0) >= 1),
                            key=lambda u: (-earned(u), -int(u.get("ref_count", 0) or 0), int(u["user_id"])))
            ranks, top = {}, []
            for index, user in enumerate(ranked):
                ranks[user["user_id"]] = index + 1
                if index < 20:
                    top.append({"rank": index + 1, "label": f"PRS · {digest(str(user['user_id']))[:6].upper()}",
                                "earned": earned(user), "referrals": int(user.get("ref_count", 0) or 0),
                                "user_id": user["user_id"]})
            self._board = {"at": now, "pool": pool, "ranks": ranks, "top": top}
            return self._board

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
        """Top 20 rows (with user_id) from the cached snapshot."""
        return [dict(row) for row in self._board_snapshot()["top"]]

    def profile(self, user_id):
        self.check_access(user_id)
        user = self.store.get("users", user_id)
        admin = user_id in self.settings.admins
        if not user and not admin:
            raise PortalError("registration_required", 403)
        user = user or {"user_id": user_id}
        total = earned(user)
        paid = min(total, max(0, int(user.get("paid_amount", 0))))
        board = self._board_snapshot()
        pool = board["pool"]
        history = self.store.find("portal_history", {"user_id": user_id}, sort=[("created_at", -1)], limit=30)
        payments = self.store.find("portal_payments", {"user_id": user_id}, sort=[("created_at", -1)], limit=20)
        return {"user_id": user_id, "is_admin": admin, "language": user.get("lang", "fa"),
            "registered": int(user.get("verified", 0)) >= 1,
            "earned": total, "paid": paid, "unpaid": max(0, total - paid),
            "referrals": int(user.get("ref_count", 0)), "required_referrals": REQUIRED_REFERRALS,
            "min_withdrawal": MIN_WITHDRAWAL,
            "daily_count": int(user.get("daily_count", 0)), "daily_reward": DAILY_REWARD,
            "daily_available_at": max(0, int(user.get("last_daily", 0)) + 86400) if user.get("last_daily") else 0,
            "wallet": user.get("wallet") or "", "rank": board["ranks"].get(user_id),
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
            "tickets": [self._public_ticket(t) for t in self.store.find(
                "portal_tickets", {"user_id": user_id}, sort=[("created_at", -1)], limit=50)]}

    def public_leaderboard(self, user_id):
        return [{k: v for k, v in row.items() if k != "user_id"} | {"is_me": row["user_id"] == user_id} for row in self.leaderboard()]

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
            self._claim_wallet(tx, user, wallet.strip())
            user.update(wallet=wallet.strip(), wallet_lc=wallet.strip().lower(), submitted=1 if submitted == 0 else 2)
            tx.put("users", user_id, user)
        self.store.transaction(operation)

    def _claim_wallet(self, tx, user, wallet):
        """One wallet per account: refuse an address another account already uses.

        The claim document makes two simultaneous registrations of the same
        address conflict inside MongoDB instead of both succeeding.
        """
        key = wallet.lower()
        if (user.get("wallet") or "").lower() == key:
            return
        claim = tx.get("portal_wallet_claims", key)
        if claim and claim.get("user_id") != user["user_id"]:
            raise PortalError("wallet_in_use", 409)
        if any(other.get("user_id") != user["user_id"] for other in tx.find("users", {"wallet_lc": key}, limit=5)):
            raise PortalError("wallet_in_use", 409)
        previous = (user.get("wallet") or "").lower()
        if previous:
            old_claim = tx.get("portal_wallet_claims", previous)
            if old_claim and old_claim.get("user_id") == user["user_id"]:
                tx.delete("portal_wallet_claims", previous)
        tx.put("portal_wallet_claims", key, {"user_id": user["user_id"], "created_at": self.now()})

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

    def prepare_wallet_payout(self, admin_id, payment_id):
        """Reserve one withdrawal and return the exact BSC token transfer for wallet signing."""
        self.require_admin(admin_id)
        if not isinstance(payment_id, str) or not 1 <= len(payment_id) <= 64:
            raise PortalError("invalid_request")
        if self.settings.demo or not self.settings.bsc_rpc_url or not self.settings.payout_wallet_address:
            raise PortalError("payout_not_configured", 503)
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.settings.bsc_rpc_url, request_kwargs={"timeout": 15}))
            if not w3.is_connected() or int(w3.eth.chain_id) != 56:
                raise ValueError("wrong network")
            signer = Web3.to_checksum_address(self.settings.payout_wallet_address)
            token_address = Web3.to_checksum_address(self.settings.prs_token_address)
            token = w3.eth.contract(address=token_address, abi=[
                {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"}
            ])
            decimals = int(token.functions.decimals().call())
            if decimals != self.settings.prs_token_decimals:
                raise ValueError("token decimals mismatch")
            # Remember where to start looking on-chain if this attempt is later cancelled.
            signing_block = int(w3.eth.block_number)
        except PortalError:
            raise
        except Exception:
            raise PortalError("payout_unavailable", 503) from None

        payment = self.store.get("portal_payments", payment_id)
        if not payment:
            raise PortalError("user_not_found", 404)
        # A signer must not accidentally pay an arbitrary address selected by the browser.
        recipient = payment.get("wallet", "")
        if not Web3.is_address(recipient) or int(recipient, 16) == 0:
            raise PortalError("invalid_wallet")
        amount = int(payment.get("amount", 0))
        if amount < MIN_WITHDRAWAL:
            raise PortalError("invalid_request")
        amount_units = amount * (10 ** decimals)
        data = "0xa9059cbb" + recipient[2:].lower().rjust(64, "0") + format(amount_units, "064x")

        def reserve(tx):
            current = tx.get("portal_payments", payment_id)
            if not current or current.get("status") != "pending":
                raise PortalError("already_reviewed", 409)
            current.update(status="signing", signing_wallet=signer, signing_started_at=self.now(),
                           signing_block=signing_block)
            tx.put("portal_payments", payment_id, current)
            self._audit(tx, admin_id, "wallet_payout_prepared", payment_id,
                        {"amount": amount, "recipient": recipient, "signer": signer})
        self.store.transaction(reserve)
        return {"payment_id": payment_id, "amount": amount, "recipient": Web3.to_checksum_address(recipient),
                "payout_wallet": signer, "token_address": token_address, "chain_id": 56,
                "transaction": {"from": signer, "to": token_address, "value": "0x0", "data": data, "chainId": "0x38"}}

    def cancel_wallet_payout(self, admin_id, payment_id, force=False, not_sent=False):
        """Return a signing reservation to pending — but never after tokens left the treasury.

        The browser can lose the transaction hash (for example when the phone
        switches to Trust Wallet and the page reloads). Before allowing another
        attempt, the chain is searched for a transfer from the treasury to this
        recipient. A matching transfer is recorded instead of cancelled.
        """
        self.require_admin(admin_id)
        if type(force) is not bool or type(not_sent) is not bool:
            raise PortalError("invalid_request")
        payment = self.store.get("portal_payments", payment_id)
        if not payment or payment.get("status") != "signing" or payment.get("tx_hash") or payment.get("submitted_tx_hash"):
            raise PortalError("payment_not_cancellable", 409)
        # not_sent: the payout page knows the transfer never reached a signature
        # (wrong wallet, admin declined the summary, or the wallet returned
        # "user rejected" 4001). Any other cancel searches the chain first.
        if not not_sent:
            found = self._find_sent_payout(payment, force)
            if found:
                result = self.confirm_wallet_payout(admin_id, payment_id, found)
                return {"recovered": True, **result}
        def cancel(tx):
            current = tx.get("portal_payments", payment_id)
            if not current or current.get("status") != "signing" or current.get("tx_hash") or current.get("submitted_tx_hash"):
                raise PortalError("payment_not_cancellable", 409)
            current.update(status="pending", signing_wallet="", signing_started_at=0, signing_block=None)
            tx.put("portal_payments", payment_id, current)
            self._audit(tx, admin_id, "wallet_payout_cancelled", payment_id,
                        {"forced": force, "not_sent": not_sent})
        self.store.transaction(cancel)
        return {"cancelled": True}

    def _find_sent_payout(self, payment, force=False):
        """Search BSC for an unrecorded PRS transfer treasury → recipient since signing began."""
        waited = self.now() - int(payment.get("signing_started_at", 0))
        if waited < PAYOUT_CANCEL_SETTLE_SECONDS:
            raise PortalError("payout_cancel_too_soon", 409, remaining=PAYOUT_CANCEL_SETTLE_SECONDS - waited)
        if self.settings.demo or not self.settings.bsc_rpc_url:
            raise PortalError("payout_not_configured", 503)
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.settings.bsc_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected() or int(w3.eth.chain_id) != 56:
                raise ValueError("wrong network")
            signer = Web3.to_checksum_address(payment.get("signing_wallet") or self.settings.payout_wallet_address)
            token_address = Web3.to_checksum_address(self.settings.prs_token_address)
            recipient = Web3.to_checksum_address(payment.get("wallet", ""))
            # A treasury transaction still waiting in the mempool may be this payout.
            if int(w3.eth.get_transaction_count(signer, "pending")) > int(w3.eth.get_transaction_count(signer, "latest")):
                raise PortalError("payout_tx_pending", 409)
            latest = int(w3.eth.block_number)
        except PortalError:
            raise
        except Exception:
            raise PortalError("payout_check_unavailable", 503) from None
        start = payment.get("signing_block")
        if type(start) is not int or latest - start > PAYOUT_SCAN_MAX_BLOCKS:
            # Too old (or prepared by an older version) to search automatically.
            # Only an admin who has checked BscScan by hand may force the cancel.
            if not force:
                raise PortalError("payout_check_too_old", 409)
            return None
        def topic(address):
            return "0x" + address[2:].lower().rjust(64, "0")
        transfer = "0x" + bytes(w3.keccak(text="Transfer(address,address,uint256)")).hex()
        units = int(payment["amount"]) * (10 ** self.settings.prs_token_decimals)
        block, window = max(0, start - 5), 5000
        while block <= latest:
            end = min(latest, block + window - 1)
            try:
                logs = w3.eth.get_logs({"address": token_address, "fromBlock": block, "toBlock": end,
                                        "topics": [transfer, topic(signer), topic(recipient)]})
            except Exception:
                if window > 250:
                    window //= 4
                    continue
                raise PortalError("payout_check_unavailable", 503) from None
            for log in logs:
                raw_hash = log.get("transactionHash")
                tx_hash = raw_hash if isinstance(raw_hash, str) else "0x" + bytes(raw_hash).hex()
                tx_hash = tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash
                if self.store.get("portal_payment_receipts", tx_hash.lower()):
                    continue  # already recorded for another payment
                data = log.get("data", "0x0")
                value = int(data, 16) if isinstance(data, str) else int.from_bytes(bytes(data), "big")
                if value != units:
                    # Tokens went to this wallet with a different amount: stop and let a human look.
                    raise PortalError("payout_transfer_found", 409, tx_hash=tx_hash)
                return tx_hash
            block = end + 1
        return None

    def confirm_wallet_payout(self, admin_id, payment_id, tx_hash):
        self.require_admin(admin_id)
        if not isinstance(payment_id, str) or not 1 <= len(payment_id) <= 64:
            raise PortalError("invalid_request")
        if not isinstance(tx_hash, str) or not re.fullmatch(r"0x[a-fA-F0-9]{64}", tx_hash):
            raise PortalError("invalid_request")
        if self.settings.demo or not self.settings.bsc_rpc_url or not self.settings.payout_wallet_address:
            raise PortalError("payout_not_configured", 503)
        payment = self.store.get("portal_payments", payment_id)
        if not payment:
            raise PortalError("user_not_found", 404)
        if payment.get("status") == "recorded" and payment.get("tx_hash", "").lower() == tx_hash.lower():
            return {"payment_id": payment_id, "status": "paid", "tx_hash": tx_hash}
        if payment.get("status") not in ("signing", "sending"):
            raise PortalError("already_reviewed", 409)
        if payment.get("status") == "sending" and payment.get("tx_hash", "").lower() != tx_hash.lower():
            raise PortalError("already_reviewed", 409)
        if payment.get("status") == "signing" and payment.get("submitted_tx_hash") and payment["submitted_tx_hash"].lower() != tx_hash.lower():
            raise PortalError("already_reviewed", 409)
        if payment.get("status") == "signing":
            def remember_hash(store_tx):
                current = store_tx.get("portal_payments", payment_id)
                if (not current or current.get("status") != "signing"
                        or (current.get("submitted_tx_hash") and current["submitted_tx_hash"].lower() != tx_hash.lower())):
                    raise PortalError("already_reviewed", 409)
                current["submitted_tx_hash"] = tx_hash
                store_tx.put("portal_payments", payment_id, current)
            self.store.transaction(remember_hash)
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.settings.bsc_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected() or int(w3.eth.chain_id) != 56:
                raise ValueError("wrong network")
            signer = Web3.to_checksum_address(self.settings.payout_wallet_address)
            token_address = Web3.to_checksum_address(self.settings.prs_token_address)
            tx = w3.eth.get_transaction(tx_hash)
        except Exception as exc:
            if type(exc).__name__ in ("TransactionNotFound", "TimeExhausted"):
                raise PortalError("transaction_pending", 409) from None
            raise PortalError("payout_unavailable", 503) from None

        recipient = Web3.to_checksum_address(payment.get("wallet", ""))
        amount_units = int(payment["amount"]) * (10 ** self.settings.prs_token_decimals)
        expected_data = "0xa9059cbb" + recipient[2:].lower().rjust(64, "0") + format(amount_units, "064x")
        if (int(tx.get("chainId", 0)) != 56 or str(tx.get("from", "")).lower() != signer.lower()
                or str(tx.get("to", "")).lower() != token_address.lower()
                or int(tx.get("value", 0)) != 0 or str(tx.get("input", tx.get("data", ""))).lower() != expected_data.lower()):
            raise PortalError("transaction_mismatch", 400)
        def mark_sending(store_tx):
            current = store_tx.get("portal_payments", payment_id)
            if current and current.get("status") == "sending" and current.get("tx_hash", "").lower() == tx_hash.lower():
                return
            if not current or current.get("status") != "signing" or current.get("signing_wallet", "").lower() != signer.lower():
                raise PortalError("already_reviewed", 409)
            current.update(status="sending", tx_hash=tx_hash, submitted_tx_hash="", reviewed_by=admin_id, payout_started_at=self.now())
            store_tx.put("portal_payments", payment_id, current)
            self._audit(store_tx, admin_id, "wallet_payout_submitted", payment_id, {"tx_hash": tx_hash})
        self.store.transaction(mark_sending)
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as exc:
            if type(exc).__name__ in ("TransactionNotFound", "TimeExhausted"):
                raise PortalError("transaction_pending", 409) from None
            raise PortalError("payout_unavailable", 503) from None
        if int(receipt.status) != 1:
            self._reset_failed_onchain_payment(admin_id, payment_id, tx_hash)
            raise PortalError("transaction_failed", 409)

        signature = bytes(w3.keccak(text="Transfer(address,address,uint256)"))
        sender_bytes, recipient_bytes = bytes.fromhex(signer[2:]), bytes.fromhex(recipient[2:])
        matched = False
        for log in receipt.logs:
            topics = [bytes.fromhex(x[2:]) if isinstance(x, str) else bytes(x) for x in log.get("topics", [])]
            if (str(log.get("address", "")).lower() == token_address.lower() and len(topics) >= 3
                    and topics[0] == signature and topics[1][-20:] == sender_bytes and topics[2][-20:] == recipient_bytes):
                data = log.get("data", "0x0")
                value = int(data, 16) if isinstance(data, str) else int.from_bytes(bytes(data), "big")
                if value == amount_units:
                    matched = True
                    break
        if not matched:
            raise PortalError("transaction_mismatch", 400)

        self._finalize_onchain_payment(admin_id, payment_id, tx_hash, int(receipt.blockNumber))
        return {"payment_id": payment_id, "status": "paid", "tx_hash": tx_hash}

    def payout_payments(self, admin_id, payment_ids):
        """Legacy server-signing payout is intentionally disabled."""
        self.require_admin(admin_id)
        raise PortalError("wallet_signing_required", 409)

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
            self._claim_wallet(tx, user, wallet.strip())
            user.update(wallet=wallet.strip(), wallet_lc=wallet.strip().lower(), submitted=1)
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
        users = self.store.scan("users", EARNED_FIELDS + ("verified", "portal_suspended", "paid_amount"))
        mining = self.mining_config()
        return {"missions": sorted(self.store.all("portal_missions"), key=lambda m: m["created_at"], reverse=True),
            "submissions": self.store.find("portal_submissions", {"status": "pending"}, sort=[("created_at", 1)], limit=500),
            "payments": self.store.find("portal_payments", {"status": {"$in": ["pending", "signing", "sending"]}},
                                        sort=[("created_at", 1)], limit=500),
            "tickets": self.store.find("portal_tickets", {"status": "open"}, sort=[("created_at", 1)], limit=500),
            "users": len([u for u in users if int(u.get("verified", 0) or 0) >= 1]),
            "stats": {"earned": sum(earned(u) for u in users), "paid": sum(int(u.get("paid_amount", 0) or 0) for u in users),
                      "suspended": sum(bool(u.get("portal_suspended")) for u in users),
                      "active_mining": len(self.store.find("portal_mining", {"status": "active"})),
                      "mining_spent": mining["spent"], "mining_reserved": mining["reserved"],
                      "campaign_limit": MAX_TOTAL_TOKENS_LIMIT},
            "controls": self.campaign_controls(), "user_page": self.admin_users(user_id),
            "recent_payments": self.store.find("portal_payments", {}, sort=[("created_at", -1)], limit=50),
            "audit": self.store.find("portal_audit", {}, sort=[("created_at", -1)], limit=50)}


def build_service(settings=None, database=None, member_check=None):
    settings = settings or Settings.from_env()
    if settings.demo:
        return PortalService(MemoryStore(), settings, lambda uid: True, cache_seconds=0)
    if database is None:
        if not settings.mongo_url:
            raise RuntimeError("MONGO_URL is required")
        from pymongo import MongoClient
        database = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000)[settings.database]
    return PortalService(MongoStore(database), settings, member_check)
