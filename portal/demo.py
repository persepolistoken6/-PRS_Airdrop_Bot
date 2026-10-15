from .service import PortalService


def seed_demo(service: PortalService):
    """Only synthetic records; no real Telegram token or Mongo connection."""
    now = service.now()
    for index, (refs, daily, bonus, paid) in enumerate([(7, 5, 1250, 10000), (12, 9, 2200, 15000), (9, 6, 800, 6000), (5, 4, 1500, 4000), (3, 2, 500, 0), (1, 0, 0, 0)]):
        uid = 1001 + index
        service.store.put("users", uid, {"user_id": uid, "ref_count": refs, "daily_count": daily,
            "manual_bonus_tokens": bonus, "bonus_tokens": 0, "paid_amount": paid, "verified": 2,
            "lang": "fa", "last_daily": now - 90000, "wallet": "0x" + f"{uid:040x}", "submitted": 1})
    admin = service.settings.admins[0]
    definitions = [
        {"title": "قدم اول؛ PRS را بشناس", "title_en": "Your first step into PRS", "description": "معرفی پروژه را مرور کن و به یک سؤال کوتاه پاسخ بده.", "description_en": "Explore the project introduction and answer one short question.", "kind": "quiz", "reward": 250, "budget": 25000, "max_claims": 100, "recurrence": "once", "url": "https://prstoken.com/home/", "question": "توکن فعلی PRS روی کدام شبکه است؟", "question_en": "Which network hosts the current PRS token?", "options": ["BNB Chain", "TON", "Solana"], "options_en": ["BNB Chain", "TON", "Solana"], "answer": 0},
        {"title": "سؤال امروز؛ امنیت کیف پول", "title_en": "Today's wallet safety question", "description": "دانش امنیتی خودت را با یک سؤال کوتاه مرور کن.", "description_en": "Refresh your wallet safety knowledge with a quick question.", "kind": "quiz", "reward": 100, "budget": 10000, "max_claims": 100, "recurrence": "daily", "question": "کدام اطلاعات را باید فقط نزد خودت نگه داری؟", "question_en": "Which information must stay private?", "options": ["آدرس عمومی کیف پول", "عبارت بازیابی کیف پول", "نام شبکه"], "options_en": ["Public wallet address", "Wallet recovery phrase", "Network name"], "answer": 1},
        {"title": "پیشنهاد تو برای PRS", "title_en": "Your idea for PRS", "description": "یک پیشنهاد مشخص و کاربردی برای بهبود سایت یا ربات بنویس. پاداش پس از بررسی ثبت می‌شود.", "description_en": "Share a specific, useful improvement for the website or bot. Rewards follow a review.", "kind": "manual", "reward": 500, "budget": 15000, "max_claims": 30, "recurrence": "once", "ends_at": now + 7 * 86400},
        {"title": "چالش خلاقیت این هفته", "title_en": "This week's creative challenge", "description": "یک طرح یا میم درباره PRS بساز و لینک اثر خودت را برای بررسی بفرست.", "description_en": "Create an original PRS design or meme and submit a link for review.", "kind": "manual", "reward": 750, "budget": 15000, "max_claims": 20, "recurrence": "weekly", "ends_at": now + 7 * 86400},
    ]
    for item in definitions:
        mission = service.create_mission(admin, item)
        service.set_mission_active(admin, mission["id"], True)
    sample = service.store.all("portal_missions")[2]
    service.submit_mission(1004, sample["id"], {"evidence": "پیشنهاد نمونه: زمان باقی‌مانده پاداش روزانه در صفحه اصلی نمایش داده شود."})
    service.ticket(1005, "پیام آزمایشی: چطور می‌توانم وضعیت پرداخت پاداشم را پیگیری کنم؟")
