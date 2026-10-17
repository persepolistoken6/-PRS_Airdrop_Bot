"""Normal Telegram bot handlers backed by the same service as the web portal."""
import html
from datetime import datetime, timezone

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .service import PortalError

PANEL_LABELS = ("🌐 پنل ایردراپ", "🌐 Airdrop portal")
MISSION_LABELS = ("🎯 مأموریت‌های جدید", "🎯 New missions")


class BotBridge:
    def __init__(self, bot, service, menu_factory, reserved_labels=()):
        self.bot, self.service, self.menu_factory = bot, service, menu_factory
        self.reserved_labels = set(reserved_labels) | set(PANEL_LABELS) | set(MISSION_LABELS)

    def language(self, uid):
        return (self.service.store.get("users", uid) or {}).get("lang", "fa")

    def text(self, uid, fa, en):
        return fa if self.language(uid) == "fa" else en

    def error_text(self, error, uid):
        messages = {
            "registration_required": ("ابتدا ثبت‌نام در ربات را کامل کن و دوباره تلاش کن.", "Complete registration in the bot first."),
            "portal_not_configured": ("پنل سایت هنوز فعال نشده است.", "The web portal has not been configured yet."),
            "membership_required": ("ابتدا در کانال رسمی عضو شو.", "Join the official channel first."),
            "daily_cooldown": ("پاداش این دوره را قبلاً گرفته‌ای؛ پس از ۲۴ ساعت دوباره تلاش کن.", "You already claimed this reward. Try again after 24 hours."),
            "referrals_required": ("برای دریافت این پاداش، حدنصاب دعوت فعلی کمپین را کامل کن.", "Reach the campaign's referral requirement first."),
            "already_completed": ("این مأموریت قبلاً ثبت شده است.", "This mission has already been submitted."),
            "attempts_exhausted": ("تلاش‌های مجاز این دوره تمام شده است.", "No attempts remain for this period."),
            "mission_expired": ("مهلت این مأموریت تمام شده است.", "This mission has ended."),
            "mission_not_found": ("این مأموریت فعلاً در دسترس نیست.", "This mission is not available."),
            "mission_budget_exhausted": ("ظرفیت پاداش این مأموریت تکمیل شده است.", "This mission's reward capacity has been reached."),
            "campaign_budget_exhausted": ("ظرفیت پاداش کمپین تکمیل شده است.", "The campaign reward capacity has been reached."),
            "campaign_paused": ("کمپین موقتاً متوقف شده است.", "The campaign is temporarily paused."),
            "evidence_required": ("لینک یا توضیحی بین ۱۰ تا ۱۵۰۰ نویسه بفرست.", "Send a link or description between 10 and 1,500 characters."),
            "rate_limited": ("تعداد درخواست‌ها زیاد است؛ کمی بعد تلاش کن.", "Too many requests. Try again shortly."),
            "wallet_locked": ("تا بررسی درخواست پرداخت فعلی، کیف پول قابل تغییر نیست.", "Your wallet is locked while a payment request is pending."),
            "wallet_edit_limit": ("دفعات مجاز ثبت و اصلاح کیف پول تمام شده است.", "Your wallet registration/edit limit has been reached."),
            "invalid_wallet": ("آدرس کیف پول معتبر نیست.", "The wallet address is invalid."),
            "account_suspended": ("حساب شما تعلیق شده است.", "Your account is suspended."),
        }
        pair = messages.get(error.code, ("سرویس موقتاً در دسترس نیست؛ کمی بعد تلاش کن.", "The service is temporarily unavailable. Try again shortly."))
        return self.text(uid, *pair)

    def _private(self, message):
        if message.chat.type == "private":
            return True
        self.bot.send_message(message.chat.id, "برای ورود و مأموریت‌ها، در گفت‌وگوی خصوصی ربات پیام بده. / Please open the bot privately.")
        return False

    def send_login(self, message):
        if not self._private(message):
            return
        uid = message.from_user.id
        try:
            url = self.service.issue_login(uid)
            # Keep the persistent reply keyboard, including the panel shortcut.
            self.bot.send_message(uid, self.text(uid,
                "برای بازکردن پنل در هر زمان، دکمه پنل کاربری را بزن.",
                "Use the user panel button any time to open the portal."),
                reply_markup=self.menu_factory(uid))
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton(self.text(uid, "🌐 ورود به پنل ایردراپ", "🌐 Open airdrop portal"), url=url))
            self.bot.send_message(uid, self.text(uid,
                "🌐 ثبت‌نام آماده است؛ برای ادامه وارد سایت شو.\nلینک شخصی تو ۵ دقیقه اعتبار دارد؛ آن را برای دیگران نفرست.",
                "🌐 Continue in the website.\nYour private sign-in link expires in 5 minutes. Keep it private."),
                reply_markup=keyboard, protect_content=False)
        except PortalError as error:
            self.bot.send_message(uid, self.error_text(error, uid))
        except Exception:
            self.bot.send_message(uid, self.text(uid, "ورود فعلاً در دسترس نیست؛ کمی بعد تلاش کن.", "Sign-in is temporarily unavailable. Please try again."))

    def list_missions(self, uid):
        self.service._user(self.service.store, uid)
        keyboard = InlineKeyboardMarkup()
        for mission in self.service.missions(uid):
            title = mission.get("title_en") if self.language(uid) == "en" and mission.get("title_en") else mission["title"]
            marker = "✅" if mission["status"] == "completed" else "⏳" if mission["status"] == "pending" else "🎯"
            keyboard.add(InlineKeyboardButton(f"{marker} {title}", callback_data=f"portal:mission:{mission['id']}"))
        self.bot.send_message(uid, self.text(uid, "🎯 مأموریت‌های جدید\nمأموریت را انتخاب کن. اطلاعات این بخش با پنل سایت مشترک است.",
            "🎯 New missions\nChoose a mission. Your progress is shared with the website."), reply_markup=keyboard if keyboard.keyboard else None)

    def show_mission(self, uid, mid):
        self.service._user(self.service.store, uid)
        mission = next((m for m in self.service.missions(uid) if m["id"] == mid), None)
        if not mission:
            raise PortalError("mission_not_found", 404)
        lang = self.language(uid)
        field = lambda key: mission.get(f"{key}_en") if lang == "en" and mission.get(f"{key}_en") else mission.get(key, "")
        title, description = field("title"), field("description")
        summary = f"🎯 {title}\n\n{description}\n\n🎁 {mission['reward']:,} PRS"
        keyboard = InlineKeyboardMarkup()
        if mission.get("url"):
            keyboard.add(InlineKeyboardButton(self.text(uid, "مطالعه منبع", "Read resource"), url=mission["url"]))
        if mission["status"] in ("completed", "pending", "exhausted", "expired"):
            labels = {"completed": ("✅ پاداش این دوره ثبت شده.", "✅ Reward recorded for this period."), "pending": ("⏳ مدرک در انتظار بررسی است.", "⏳ Submission in review."), "exhausted": ("ظرفیت یا تلاش‌های مجاز تمام شده.", "No capacity or attempts remain."), "expired": ("مهلت مأموریت تمام شده.", "This mission has ended.")}
            summary += "\n\n" + self.text(uid, *labels[mission["status"]])
        elif mission["kind"] == "quiz":
            summary += f"\n\n{field('question')}"
            for index, option in enumerate(field("options")):
                keyboard.add(InlineKeyboardButton(option, callback_data=f"portal:answer:{mid}:{index}"))
        else:
            summary += "\n\n" + self.text(uid, "لینک اثر یا توضیح فعالیتت را در پیام بعدی بفرست. برای انصراف /cancel را بزن.", "Send a link or description in your next message. Use /cancel to cancel.")
            expires = self.service.now() + 900
            self.service.store.put("portal_bot_states", uid, {"mission_id": mid, "until": expires,
                "expires_at": datetime.fromtimestamp(expires, timezone.utc)})
        keyboard.add(InlineKeyboardButton(self.text(uid, "فهرست مأموریت‌ها", "Mission list"), callback_data="portal:list"))
        self.bot.send_message(uid, summary, reply_markup=keyboard)

    def _expects_evidence(self, message):
        if message.chat.type != "private":
            return False
        item = self.service.store.get("portal_bot_states", message.from_user.id)
        if not item:
            return False
        if item["until"] <= self.service.now() or (message.text or "").startswith("/") or message.text in self.reserved_labels:
            self.service.store.delete("portal_bot_states", message.from_user.id)
            return False
        return True

    def install(self):
        @self.bot.message_handler(commands=["panel"])
        def panel_command(message):
            self.send_login(message)

        @self.bot.message_handler(func=lambda m: m.text in PANEL_LABELS)
        def panel_button(message):
            self.send_login(message)

        @self.bot.message_handler(commands=["missions"])
        @self.bot.message_handler(func=lambda m: m.text in MISSION_LABELS)
        def missions_command(message):
            if not self._private(message):
                return
            uid = message.from_user.id
            self.service.store.delete("portal_bot_states", uid)
            try:
                self.list_missions(uid)
            except PortalError as error:
                self.bot.send_message(uid, self.error_text(error, uid))

        @self.bot.message_handler(commands=["cancel"])
        def cancel(message):
            uid = message.from_user.id
            self.service.store.delete("portal_bot_states", uid)
            self.bot.send_message(message.chat.id, self.text(uid, "لغو شد.", "Cancelled."), reply_markup=self.menu_factory(uid))

        @self.bot.message_handler(content_types=["text"], func=self._expects_evidence)
        def evidence(message):
            uid = message.from_user.id
            item = self.service.store.get("portal_bot_states", uid)
            try:
                self.service.limit(f"mission-submit:{uid}", 20, 60)
                self.service.submit_mission(uid, item["mission_id"], {"evidence": message.text})
                self.service.store.delete("portal_bot_states", uid)
                self.bot.send_message(uid, self.text(uid, "⏳ مدرکت برای بررسی ثبت شد. نتیجه در ربات و سایت قابل مشاهده است.", "⏳ Your submission is in review. Check its status in the bot or website."), reply_markup=self.menu_factory(uid))
            except PortalError as error:
                self.bot.send_message(uid, self.error_text(error, uid))

        @self.bot.callback_query_handler(func=lambda call: bool(call.data and call.data.startswith("portal:")))
        def portal_callback(call):
            uid = call.from_user.id
            try:
                self.bot.answer_callback_query(call.id)
                self.service.store.delete("portal_bot_states", uid)
                parts = call.data.split(":")
                if parts == ["portal", "open"]:
                    # Send personal links privately even if a button is forwarded.
                    class PrivateMessage:
                        from_user = call.from_user
                        chat = type("Chat", (), {"type": "private", "id": uid})()
                    self.send_login(PrivateMessage())
                elif parts == ["portal", "list"]:
                    self.list_missions(uid)
                elif len(parts) == 3 and parts[1] == "mission":
                    self.show_mission(uid, parts[2])
                elif len(parts) == 4 and parts[1] == "answer" and parts[3].isdigit():
                    self.service.limit(f"mission-submit:{uid}", 20, 60)
                    result = self.service.submit_mission(uid, parts[2], {"answer": int(parts[3])})
                    text = self.text(uid, f"✅ {result['amount']:,} PRS پاداش ثبت شد.", f"✅ {result['amount']:,} PRS reward recorded.") if result["status"] == "completed" else self.text(uid, f"پاسخ صحیح نبود. {result['attempts_left']} تلاش باقی مانده.", f"Incorrect answer. {result['attempts_left']} attempts remain.")
                    self.bot.send_message(uid, text)
                    self.show_mission(uid, parts[2])
            except PortalError as error:
                self.bot.send_message(uid, self.error_text(error, uid))
            except Exception:
                self.bot.send_message(uid, self.text(uid, "سرویس فعلاً در دسترس نیست؛ کمی بعد تلاش کن.", "The service is temporarily unavailable. Try again shortly."))
        return self
