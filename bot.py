import io
import csv
import os
import random
import time
import json
import threading
import re
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from telebot import TeleBot
from telebot.types import (InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
                           WebAppInfo, MenuButtonWebApp)
from pymongo import MongoClient, ReturnDocument
from portal.settings import (Settings, REQUIRED_REFERRALS, BASE_REWARD, EXTRA_REWARD, DAILY_REWARD, MAX_TOTAL_TOKENS_LIMIT,
                             CAPTCHA_MAX_ATTEMPTS, CAPTCHA_LOCK_SECONDS)
from portal.service import build_service, PortalError, with_burn
from portal.bot_bridge import BotBridge, PANEL_LABELS, PANEL_BUTTON_LABELS, MISSION_LABELS

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL environment variable is not set")

# اتصال به MongoDB با تعیین صریح نام دیتابیس
mongo_client = MongoClient(MONGO_URL)
db = mongo_client[os.getenv("MONGO_DB", "persepolis_db")]
users_col = db.users
captcha_col = db.captcha
settings_col = db.bot_settings
PORTAL_ENABLED = os.getenv("PORTAL_ENABLED", "0") == "1"
BOT_PORTAL_ONLY = PORTAL_ENABLED and os.getenv("BOT_PORTAL_ONLY", "1") == "1"

BOT_USERNAME = os.getenv("BOT_USERNAME", "PRS_Airdrop_Bot")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@persepolisToken6")
TWITTER_URL = "https://x.com/PersepolisPRS"
INSTAGRAM_URL = "https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"

ADMIN_IDS = list(Settings.from_env().admins)
ADMIN_CHAT_ID = ADMIN_IDS[0] if ADMIN_IDS else None


# شرایط مستقل چالش جدید (بدون تغییر در حد نصاب ایردراپ اصلی)
CHALLENGE_REQUIRED_REFERRALS = 10
CHALLENGE_QUIZ_MAX_ATTEMPTS = 1
CHALLENGE_QUIZ_PASS_SCORE = 3

# برای ارسال مستقیم فایل، PDF را کنار bot.py قرار دهید یا FILE_ID تلگرام را
# در متغیر محیطی WHITEPAPER_FILE_ID ثبت کنید. لینک نیز قابل تنظیم است.
WHITEPAPER_FILE_ID = os.getenv("WHITEPAPER_FILE_ID", "").strip()
WHITEPAPER_URL = os.getenv("WHITEPAPER_URL", "https://www.prstoken.com").strip()
WHITEPAPER_LOCAL_PATH = os.getenv(
    "WHITEPAPER_LOCAL_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "PRS_Whitepaper_v1.2_FA_EN-3.pdf")
)


BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

CHALLENGE_QUIZ = [
    {
        "fa": "توکن PRS روی کدام شبکه ساخته شده است؟",
        "en": "On which network is the PRS token built?",
        "options_fa": ["Ethereum", "BNB Smart Chain (BSC)", "TON", "Solana"],
        "options_en": ["Ethereum", "BNB Smart Chain (BSC)", "TON", "Solana"],
        "correct": 1
    },
    {
        "fa": "چه تعداد توکن PRS برای ایردراپ و چه تعداد برای استخر نقدینگی در نظر گرفته شده است؟",
        "en": "How many PRS tokens are allocated to the airdrop and the liquidity pool?",
        "options_fa": [
            "۳۰۰ میلیون برای ایردراپ و ۱ میلیارد برای استخر نقدینگی",
            "۱ میلیارد برای ایردراپ و ۳۰۰ میلیون برای استخر نقدینگی",
            "۶۰۰ میلیون برای ایردراپ و ۱ میلیارد برای استخر نقدینگی",
            "۳۰۰ میلیون برای ایردراپ و ۶۰۰ میلیون برای استخر نقدینگی"
        ],
        "options_en": [
            "300M for airdrop and 1B for liquidity",
            "1B for airdrop and 300M for liquidity",
            "600M for airdrop and 1B for liquidity",
            "300M for airdrop and 600M for liquidity"
        ],
        "correct": 0
    },
    {
        "fa": "مجموع عرضه کل توکن‌های PRS چقدر است؟",
        "en": "What is the total supply of PRS tokens?",
        "options_fa": ["۳۰۰ میلیون", "۱ میلیارد", "۳ میلیارد", "۶ میلیارد"],
        "options_en": ["300 million", "1 billion", "3 billion", "6 billion"],
        "correct": 3
    }
]

# Six handler threads instead of the library default of two, so a burst of
# registrations does not queue behind a few slow Telegram/MongoDB calls.
bot = TeleBot(TOKEN, threaded=True, num_threads=int(os.getenv("BOT_THREADS", "6")))

# ----------------- سیستم چندزبانه (فارسی / انگلیسی) -----------------
LANG = {
    "fa": {
        "global_off": "🛑 ربات در حال حاضر توسط مدیریت موقتاً خاموش شده است. لطفاً بعداً مراجعه کنید.",
        "airdrop_finished": "🛑 کل توکن های ایردارپ ( ۳۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.",
        "self_ref": "⚠️ **شما نمی‌توانید روی لینک دعوت خودتان کلیک کنید!**\n\nلطفاً این لینک را برای دوستان خود ارسال کنید تا از طریق آن وارد ربات شوند.",
        "join_req": "⚠️ **لطفاً برای ادامه کار ابتدا در کانال ما عضو شوید:**\n\n▫️ {}\n\nپس از عضویت، روی دکمه‌ی «عضو شدم، تایید کن» بزنید.",
        "join_btn": "📢 عضویت در کانال رسمی",
        "joined_btn": "✅ عضو شدم، تایید کن",
        "captcha_title": "🛡 *تایید هویت امنیتی (ضد ربات و فیک)* \n\nلطفاً حاصل جمع زیر را به عنوان پاسخ ارسال کنید:\n❓ {} + {} = ؟\n\n*(عدد پاسخ را در چت ارسال کنید)*",
        "captcha_wrong": "❌ پاسخ اشتباه است!\n\n🛡 یک سوال امنیتی جدید برای شما ارسال شد:\n❓ لطفاً حاصل جمع {} + {} را بفرستید:",
        "main_kb_status": "📊 وضعیت من و رتبه",
        "main_kb_ref": "🔗 دریافت لینک دعوت",
        "main_kb_daily": "🎁 پاداش روزانه",
        "main_kb_wallet": "📝 ارسال / ویرایش آدرس ولت",
        "main_kb_guide": "📖 راهنمای ولت و توکن",
        "main_kb_leaderboard": "🏆 برترین شرکت‌کنندگان",
        "main_kb_refresh": "🔄 به‌روزرسانی پنل کاربری",
        "main_kb_channel": "📢 کانال تلگرام",
        "main_kb_twitter": "🐦 توییتر (ایکس)",
        "main_kb_instagram": "📸 اینستاگرام",
        "main_kb_social": "🎟 ثبت آیدی شبکه‌های اجتماعی",
        "main_kb_challenge_quiz": "📝 آزمون چالش PRS",
        "btn_channel": "📢 کانال تلگرام",
        "btn_twitter": "🐦 توییتر (ایکس)",
        "btn_insta": "📸 اینستاگرام پرسپولیس",
        "btn_ref": "🔗 دریافت لینک دعوت جذاب و اختصاصی",
        "btn_daily": "🎁 پاداش روزانه (1000 PRS)",
        "btn_guide": "📖 راهنمای ولت و توکن PRS",
        "btn_top": "🏆 برترین شرکت‌کنندگان (تاپ ۱۰)",
        "btn_status": "📊 وضعیت من و رتبه",
        "btn_submit_w": "📝 ارسال / ویرایش ولت",
        "btn_social": "🎟 ثبت آیدی برای قرعه‌کشی",
        "btn_challenge_quiz": "📝 آزمون چالش PRS",
        "btn_refresh": "🔄 به‌روزرسانی پنل کاربری",
        "btn_lang": "🌐 تغییر زبان / Change Language",
        "lang_changed": "✅ زبان ربات با موفقیت به فارسی تغییر یافت.",
        "quick_menu_text": "👇 منوی دسترسی سریع همیشه در پایین صفحه شما قرار دارد:",
        "main_caption": (
            "🔴 *به ربات رسمی ایردراپ توکن هواداری پرسپولیس (PRS) خوش آمدید* 🏆\n\n"
            "⚡ **صدای مستقلِ یک جامعه‌؛ بدون مرز و قدرتمند!**\n\n"
            "توکن PRS فرصتی برای ساخت آینده‌ای نوین روی بلاک‌چین است. سهم خودت را از این موج بزرگ بگیر\n\n"
            "🦅 **ظرفیت محدود است؛ عقب نمان!**\n"
            "همین الان وارد شو و توکن‌هات رو دریافت کن.\n\n"
            "🎁 *سیستم پاداش‌دهی و ایردراپ:*\n"
            "▫️ پاداش پایه: `{base} PRS` (پس از عضویت در کانال و دعوت `{req}` دوست)\n"
            "▫️ پاداش روزانه: `{daily} PRS` (فعال‌سازی پس از تکمیل ۳ دعوت و هر ۲۴ ساعت یک‌بار)\n"
            "▫️ پاداش به ازای هر دعوت مازاد: `{extra} PRS`\n\n"
            "📊 *وضعیت حساب شما:*\n"
            "🆔 آیدی عددی شما: `{uid}`\n"
            "👥 دعوت‌های شما: `{refs} / {req}`\n"
            "🏅 رتبه شما در بین کاربران: `{rank}`\n"
            "🎉 پاداش‌های همگانی دریافتی: `{bonus:,} PRS`\n"
            "🎯 پاداش‌های دستی مدیریت: `{manual_bonus:,} PRS`\n"
            "🎁 کل توکن کسب‌شده: `{earned:,} PRS`\n"
            "💳 توکن پرداخت شده: `{paid:,} PRS`\n"
            "💰 موجودی باقی‌مانده: `{rem:,} PRS`"
        ),
        "ref_text": (
            "🔥 بزرگترین ایردراپ توکن هواداری پرسپولیس (PRS) 🔥\n\n"
            "🏆 فرصت استثنایی برای دریافت توکن رایگان و ورود به اکوسیستم دیجیتال پرسپولیس!\n"
            "🎁 همین الان با لینک زیر وارد ربات شو و پاداش ورودت رو بگیر:\n\n"
            "{link}\n\n"
            "این پیام رو برای دوستان خود ارسال کنید"
        ),
        "daily_locked": "⚠️ پاداش روزانه قفل است!\nبرای باز شدن آن باید حداقل {} دوست دعوت کنید.",
        "daily_already": "⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!\nلطفاً پس از {} ساعت و {} دقیقه دیگر تلاش کنید.",
        "daily_success": "🎁 تبریک! مبلغ {} توکن PRS به عنوان پاداش روزانه به حساب شما اضافه شد.",
        "wallet_guide_text": (
            "📖 *راهنمای کامل و گام‌به‌گام نصب کیف پول و اضافه کردن توکن پرسپولیس (PRS):*\n\n"
            "🔹 **مقدمه:** توکن هواداری پرسپولیس روی شبکه قدرتمند **BNB Smart Chain (BSC / BEP20)** راه‌اندازی شده است. برای دریافت و نگهداری آن، بهترین پیشنهاد استفاده از اپلیکیشن امن **Trust Wallet (تراست ولت)** است.\n\n"
            "📱 **مرحله اول: نصب و ساخت کیف پول**\n"
            "• برنامه Trust Wallet را از گوگل‌پلی یا اپ‌استور دانلود کنید.\n"
            "• یک کیف پول جدید بسازید و **۱۲ کلمه بازیابی (Seed Phrase)** خود را حتماً روی کاغذ یادداشت کنید و در جای امن نگه دارید.\n\n"
            "📋 **مرحله دوم: نحوه اضافه کردن توکن PRS (Custom Token)**\n"
            "چون این توکن جدید است، برای نمایش آن در تراست ولت باید مراحل زیر را انجام دهید:\n"
            "1. وارد تراست ولت شوید و در قسمت پایین سمت راست، روی آیکون ذره‌بین (Search) بزنید.\n"
            "2. آدرس قرارداد (Contract Address) توکن پرسپولیس را در کادر جستجو وارد کنید:\n"
            "`0x1f67eB3e7487b7D70C69264Ab907Dd074ef1d39f`\n"
            "3. **دقت کنید که نام کامل آن حتماً PERSEPOLIS باشد.**\n"
            "4. روی گزینه افزودن یا فعال‌سازی توکن بزنید تا به لیست کیف پول شما اضافه شود.\n\n"
            "📤 **مرحله سوم: ارسال آدرس ولت به ربات**\n"
            "• وارد توکن **PERSEPOLIS (PRS)** در کیف پول خود شوید و روی گزینه **Receive** (دریافت) بزنید.\n"
            "• آدرس اختصاصی ولت PRS خود (شروع شده با `0x`) را کپی کرده و در بخش **«ارسال / ویرایش آدرس ولت»** در همین ربات بفرستید.\n\n"
            "❓ اگر هر گونه سوالی داشتید، می‌توانید به پشتیبانی پیام دهید: @PRSsupportt"
        ),
        "top_title": "🏆 *۱۰ شرکت‌کننده برتر ایردراپ (براساس مجموع توکن‌ها)*:\n\n",
        "top_row": "{}. آیدی: `{uid}` — 🎁 توکن کل: *{total:,} PRS* (دعوت: {refs})\n",
        "submit_errors": "⚠️ **امکان ثبت/ویرایش ولت وجود ندارد:**\n\n{}\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.",
        "submit_err_ref": "❌ تعداد دعوت‌های شما ({} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {} نفر)",
        "submit_err_limit": "⚠️ شما سهمیه ثبت‌نام و تنها ویرایش مجاز خود را استفاده کرده‌اید و دیگر امکان تغییر ولت وجود ندارد.",
        "submit_edit_mode": "✏️ **حالت ویرایش ولت:**\nشما قبلاً ولت خود را ثبت کرده بودید. اکنون می‌توانید آدرس ولت اختصاصی **PRS** خود را ارسال کنید:",
        "submit_new_mode": "لطفاً آدرس ولت اختصاصی توکن **PERSEPOLIS (PRS)** (شروع شده با 0x) خود را ارسال کنید:",
        "wallet_saved": "✅ آدرس ولت توکن PRS شما با موفقیت ثبت شد.",
        "wallet_updated": "✅ آدرس ولت شما با موفقیت **ویرایش و به‌روزرسانی شد**.",
        "wallet_limit_err": "⚠️ شما سهمیه ویرایش خود را به اتمام رسانده‌اید.",
        "social_start": (
            "🎟 *ثبت آیدی شبکه‌های اجتماعی برای قرعه‌کشی*\n\n"
            "🐦 آیدی فعلی Twitter/X: `{twitter}`\n"
            "📸 آیدی فعلی Instagram: `{instagram}`\n\n"
            "ابتدا آیدی Twitter/X خود را ارسال کنید. می‌توانید `@username` یا لینک پروفایل را بفرستید.\n\n"
            "تا زمانی که هر دو آیدی را کامل نکنید، اطلاعات قبلی شما تغییر نمی‌کند."
        ),
        "social_instagram_prompt": (
            "✅ آیدی Twitter/X دریافت شد: `{twitter}`\n\n"
            "حالا آیدی Instagram خود را به‌صورت `@username` یا لینک پروفایل ارسال کنید:"
        ),
        "social_invalid_twitter": "❌ آیدی Twitter/X معتبر نیست. لطفاً فقط `@username` یا لینک صحیح پروفایل را ارسال کنید:",
        "social_invalid_instagram": "❌ آیدی Instagram معتبر نیست. لطفاً فقط `@username` یا لینک صحیح پروفایل را ارسال کنید:",
        "social_duplicate_twitter": "⚠️ این آیدی Twitter/X قبلاً توسط کاربر دیگری ثبت شده است. آیدی دیگری ارسال کنید:",
        "social_duplicate_instagram": "⚠️ این آیدی Instagram قبلاً توسط کاربر دیگری ثبت شده است. آیدی دیگری ارسال کنید:",
        "social_saved": (
            "✅ *آیدی‌های شما با موفقیت برای قرعه‌کشی ثبت شد.*\n\n"
            "🐦 Twitter/X: `{twitter}`\n"
            "📸 Instagram: `{instagram}`\n\n"
            "برای ویرایش، دوباره گزینه ثبت آیدی شبکه‌های اجتماعی را انتخاب کنید."
        ),
        "social_cancelled": "❌ ثبت آیدی شبکه‌های اجتماعی لغو شد و اطلاعات قبلی شما تغییر نکرد.",
        "social_cancel_btn": "❌ انصراف",
        "social_not_registered": "ثبت نشده",
        "challenge_intro": (
            "📝 *آزمون چالش PRS*\n\n"
            "ابتدا وایت‌پیپر رسمی را مطالعه کنید و سپس به ۳ سؤال پاسخ دهید. "
            "برای قبولی باید پاسخ هر سه سؤال صحیح باشد.\n\n"
            "🎯 شرط دعوت این چالش: حداقل `{required_refs}` دعوت موفق\n"
            "🔁 حداکثر دفعات شرکت: `{max_attempts}` بار\n"
            "⏳ فرصت باقی‌مانده شما: `{remaining_attempts}` بار\n\n"
            "پس از آمادگی، دکمه شروع آزمون را بزنید."
        ),
        "challenge_start_btn": "▶️ شروع آزمون",
        "challenge_whitepaper_btn": "📘 مشاهده وایت‌پیپر رسمی",
        "challenge_whitepaper_caption": "📘 وایت‌پیپر رسمی پروژه PRS؛ پیش از شروع آزمون آن را مطالعه کنید.",
        "challenge_passed_before": "✅ شما قبلاً آزمون چالش PRS را با موفقیت گذرانده‌اید.",
        "challenge_no_attempts": "❌ هر دو فرصت شما برای شرکت در آزمون استفاده شده و امکان تلاش مجدد وجود ندارد.",
        "challenge_question": "📝 *سؤال {number} از {total}*\n\n{question}",
        "challenge_result_passed": (
            "🎉 *تبریک! آزمون را با موفقیت گذراندید.*\n\n"
            "✅ امتیاز شما: `{score}` از `{total}`\n"
            "آزمون به‌عنوان یکی از شرایط چالش در حساب شما ثبت شد."
        ),
        "challenge_result_failed": (
            "❌ این بار حد نصاب آزمون را کسب نکردید.\n\n"
            "📊 امتیاز شما: `{score}` از `{total}`\n"
            "⏳ فرصت باقی‌مانده: `{remaining_attempts}` بار"
        ),
        "challenge_retry_btn": "🔄 تلاش دوباره",
        "challenge_stale_answer": "⚠️ این پاسخ مربوط به سؤال فعال شما نیست. آزمون را از منو ادامه دهید.",
        "status_box": (
            "📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            "🆔 آیدی عددی شما: `{uid}`\n"
            "👥 تعداد دعوت‌ها: `{refs} / {req}`\n"
            "🎉 پاداش‌های همگانی دریافتی: `{bonus:,} PRS`\n"
            "🎯 پاداش‌های دستی مدیریت: `{manual_bonus:,} PRS`\n"
            "🎁 کل توکن کسب‌شده: `{earned:,} PRS`\n"
            "💳 توکن پرداخت شده: `{paid:,} PRS`\n"
            "💰 موجودی باقی‌مانده: `{rem:,} PRS`\n"
            "🏅 رتبه شما در ایردراپ: `{rank}`\n"
            "👝 آدرس ولت فعلی: `{wallet}`\n"
            "🐦 آیدی Twitter/X: `{twitter}`\n"
            "📸 آیدی Instagram: `{instagram}`"
        )
    },
    "en": {
        "global_off": "🛑 The bot is currently turned off by management. Please try again later.",
        "airdrop_finished": "🛑 All airdrop tokens (300M PRS) have been claimed and this bot is now inactive. Tokens will be distributed soon.",
        "self_ref": "⚠️ **You cannot click on your own referral link!**\n\nPlease send this link to your friends so they can join via it.",
        "join_req": "⚠️ **Please join our official channel first to continue:**\n\n▫️ {}\n\nAfter joining, click the 'I have joined, verify' button.",
        "join_btn": "📢 Join Official Channel",
        "joined_btn": "✅ I joined, verify",
        "captcha_title": "🛡 *Security Verification (Anti-bot)* \n\nPlease send the sum of the following numbers as your answer:\n❓ {} + {} = ?\n\n*(Send the answer number in chat)*",
        "captcha_wrong": "❌ Wrong answer!\n\n🛡 A new security question has been sent:\n❓ Please send the sum of {} + {}:",
        "main_kb_status": "📊 My Status & Rank",
        "main_kb_ref": "🔗 Get Referral Link",
        "main_kb_daily": "🎁 Daily Bonus",
        "main_kb_wallet": "📝 Submit / Edit Wallet",
        "main_kb_guide": "📖 Wallet & Token Guide",
        "main_kb_leaderboard": "🏆 Top Participants",
        "main_kb_refresh": "🔄 Refresh User Panel",
        "main_kb_channel": "📢 Telegram Channel",
        "main_kb_twitter": "🐦 Twitter (X)",
        "main_kb_instagram": "📸 Instagram",
        "main_kb_social": "🎟 Register Social IDs",
        "main_kb_challenge_quiz": "📝 PRS Challenge Quiz",
        "btn_channel": "📢 Telegram Channel",
        "btn_twitter": "🐦 Twitter (X)",
        "btn_insta": "📸 Persepolis Instagram",
        "btn_ref": "🔗 Get Exclusive Referral Link",
        "btn_daily": "🎁 Daily Bonus (1000 PRS)",
        "btn_guide": "📖 PRS Wallet & Token Guide",
        "btn_top": "🏆 Top Participants (Top 10)",
        "btn_status": "📊 My Status & Rank",
        "btn_submit_w": "📝 Submit / Edit Wallet",
        "btn_social": "🎟 Register IDs for Lottery",
        "btn_challenge_quiz": "📝 PRS Challenge Quiz",
        "btn_refresh": "🔄 Refresh User Panel",
        "btn_lang": "🌐 تغییر زبان / Change Language",
        "lang_changed": "✅ Bot language successfully changed to English.",
        "quick_menu_text": "👇 Quick access menu is always at the bottom of your screen:",
        "main_caption": (
            "🔴 *Welcome to Official Persepolis Fan Token (PRS) Airdrop Bot* 🏆\n\n"
            "⚡ **The independent voice of a community; boundless and powerful!**\n\n"
            "PRS token is an opportunity to build a modern future on blockchain. Claim your share of this massive wave!\n\n"
            "🦅 **Capacity is limited; don't miss out!**\n"
            "Join right now and get your tokens.\n\n"
            "🎁 *Airdrop & Reward System:*\n"
            "▫️ Base Reward: `{base} PRS` (After joining channel & inviting `{req}` friends)\n"
            "▫️ Daily Bonus: `{daily} PRS` (Unlocked after 3 referrals, every 24 hours)\n"
            "▫️ Extra Referral Reward: `{extra} PRS`\n\n"
            "📊 *Your Account Status:*\n"
            "🆔 Your User ID: `{uid}`\n"
            "👥 Your Referrals: `{refs} / {req}`\n"
            "🏅 Your Rank: `{rank}`\n"
            "🎉 Global Rewards Received: `{bonus:,} PRS`\n"
            "🎯 Manual Admin Rewards: `{manual_bonus:,} PRS`\n"
            "🎁 Total Earned Tokens: `{earned:,} PRS`\n"
            "💳 Paid Tokens: `{paid:,} PRS`\n"
            "💰 Remaining Balance: `{rem:,} PRS`"
        ),
        "ref_text": (
            "🔥 Biggest Persepolis Fan Token (PRS) Airdrop 🔥\n\n"
            "🏆 Exceptional opportunity to get free tokens and enter the Persepolis digital ecosystem!\n"
            "🎁 Join the bot with the link below right now and claim your entry bonus:\n\n"
            "{link}\n\n"
            "Send this message to your friends!"
        ),
        "daily_locked": "⚠️ Daily bonus is locked!\nYou must invite at least {} friends to unlock it.",
        "daily_already": "⏳ You have already claimed your daily bonus today!\nPlease try again after {} hours and {} minutes.",
        "daily_success": "🎁 Congratulations! {} PRS tokens added to your account as daily bonus.",
        "wallet_guide_text": (
            "📖 *Complete Step-by-Step Guide to Installing Wallet & Adding Persepolis Token (PRS):*\n\n"
            "🔹 **Introduction:** Persepolis Fan Token runs on the powerful **BNB Smart Chain (BSC / BEP20)**. To receive and store it, **Trust Wallet** is recommended.\n\n"
            "📱 **Step 1: Install & Create Wallet**\n"
            "• Download Trust Wallet from Google Play or App Store.\n"
            "• Create a new wallet and securely write down your **12-word Seed Phrase** on paper.\n\n"
            "📋 **Step 2: Add PRS Token (Custom Token)**\n"
            "To display it in Trust Wallet:\n"
            "1. Open Trust Wallet and tap the search icon in the top/bottom right.\n"
            "2. Enter Persepolis contract address in the search box:\n"
            "`0x1f67eB3e7487b7D70C69264Ab907Dd074ef1d39f`\n"
            "3. **Ensure the full name is PERSEPOLIS.**\n"
            "4. Enable/add the token to your wallet list.\n\n"
            "📤 **Step 3: Send Wallet Address to Bot**\n"
            "• Go to **PERSEPOLIS (PRS)** token in your wallet and tap **Receive**.\n"
            "• Copy your PRS wallet address (starting with `0x`) and send it in the **«Submit / Edit Wallet»** section of this bot.\n\n"
            "❓ If you have any questions, contact support: @PRSsupportt"
        ),
        "top_title": "🏆 *Top 10 Airdrop Participants (By Total Tokens)*:\n\n",
        "top_row": "{}. ID: `{uid}` — 🎁 Total Tokens: *{total:,} PRS* (Refs: {refs})\n",
        "submit_errors": "⚠️ **Cannot submit/edit wallet:**\n\n{}\n\nPlease try again after resolving issues.",
        "submit_err_ref": "❌ Your referral count ({} users) has not reached the threshold. (Min required: {} users)",
        "submit_err_limit": "⚠️ You have used your registration and only allowed edit quota; wallet changes are no longer permitted.",
        "submit_edit_mode": "✏️ **Wallet Edit Mode:**\nYou have previously registered your wallet. You now can send your exclusive **PRS** wallet address:",
        "submit_new_mode": "Please send your exclusive **PERSEPOLIS (PRS)** token wallet address (starting with 0x):",
        "wallet_saved": "✅ Your PRS wallet address has been successfully registered.",
        "wallet_updated": "✅ Your wallet address has been successfully **edited and updated**.",
        "wallet_limit_err": "⚠️ You have exhausted your edit quota.",
        "social_start": (
            "🎟 *Register Social Media IDs for the Lottery*\n\n"
            "🐦 Current Twitter/X ID: `{twitter}`\n"
            "📸 Current Instagram ID: `{instagram}`\n\n"
            "First, send your Twitter/X ID. You can send `@username` or your profile link.\n\n"
            "Your previous information will not change until both IDs are completed."
        ),
        "social_instagram_prompt": (
            "✅ Twitter/X ID received: `{twitter}`\n\n"
            "Now send your Instagram ID as `@username` or a profile link:"
        ),
        "social_invalid_twitter": "❌ Invalid Twitter/X ID. Please send only `@username` or a valid profile link:",
        "social_invalid_instagram": "❌ Invalid Instagram ID. Please send only `@username` or a valid profile link:",
        "social_duplicate_twitter": "⚠️ This Twitter/X ID is already registered by another user. Please send another ID:",
        "social_duplicate_instagram": "⚠️ This Instagram ID is already registered by another user. Please send another ID:",
        "social_saved": (
            "✅ *Your social media IDs were successfully registered for the lottery.*\n\n"
            "🐦 Twitter/X: `{twitter}`\n"
            "📸 Instagram: `{instagram}`\n\n"
            "To edit them, select the social ID registration option again."
        ),
        "social_cancelled": "❌ Social media ID registration was cancelled. Your previous information was not changed.",
        "social_cancel_btn": "❌ Cancel",
        "social_not_registered": "Not registered",
        "challenge_intro": (
            "📝 *PRS Challenge Quiz*\n\n"
            "Read the official whitepaper first, then answer 3 questions. "
            "All three answers must be correct to pass.\n\n"
            "🎯 Referral requirement: at least `{required_refs}` successful referrals\n"
            "🔁 Maximum attempts: `{max_attempts}`\n"
            "⏳ Your remaining attempts: `{remaining_attempts}`\n\n"
            "When you are ready, press Start Quiz."
        ),
        "challenge_start_btn": "▶️ Start Quiz",
        "challenge_whitepaper_btn": "📘 View Official Whitepaper",
        "challenge_whitepaper_caption": "📘 Official PRS whitepaper; please read it before starting the quiz.",
        "challenge_passed_before": "✅ You have already passed the PRS challenge quiz.",
        "challenge_no_attempts": "❌ You have used both quiz attempts and cannot try again.",
        "challenge_question": "📝 *Question {number} of {total}*\n\n{question}",
        "challenge_result_passed": (
            "🎉 *Congratulations! You passed the quiz.*\n\n"
            "✅ Your score: `{score}` out of `{total}`\n"
            "The quiz has been recorded as one of your completed challenge requirements."
        ),
        "challenge_result_failed": (
            "❌ You did not pass the quiz this time.\n\n"
            "📊 Your score: `{score}` out of `{total}`\n"
            "⏳ Remaining attempts: `{remaining_attempts}`"
        ),
        "challenge_retry_btn": "🔄 Try Again",
        "challenge_stale_answer": "⚠️ This answer is not for your active question. Continue the quiz from the menu.",
        "status_box": (
            "📊 *Your Account Information & Status:*\n\n"
            "🆔 Your User ID: `{uid}`\n"
            "👥 Referrals: `{refs} / {req}`\n"
            "🎉 Global Rewards Received: `{bonus:,} PRS`\n"
            "🎯 Manual Admin Rewards: `{manual_bonus:,} PRS`\n"
            "🎁 Total Earned Tokens: `{earned:,} PRS`\n"
            "💳 Paid Tokens: `{paid:,} PRS`\n"
            "💰 Remaining Balance: `{rem:,} PRS`\n"
            "🏅 Your Rank: `{rank}`\n"
            "👝 Current Wallet Address: `{wallet}`\n"
            "🐦 Twitter/X ID: `{twitter}`\n"
            "📸 Instagram ID: `{instagram}`"
        )
    }
}

def get_msg(user_id_or_lang, key, *args, **kwargs):
    lang = "fa"
    if isinstance(user_id_or_lang, int):
        user = users_col.find_one({"user_id": user_id_or_lang})
        if user and user.get("lang"):
            lang = user.get("lang")
    elif isinstance(user_id_or_lang, str) and user_id_or_lang in ["fa", "en"]:
        lang = user_id_or_lang
    
    text = LANG.get(lang, LANG["fa"]).get(key, LANG["fa"].get(key, ""))
    if args or kwargs:
        try:
            return text.format(*args, **kwargs)
        except Exception:
            return text
    return text

def get_main_reply_markup(user_id):
    """One persistent user shortcut; existing commands and admin controls remain intact.

    With the website configured, the button opens the user's panel directly inside
    Telegram (Mini App): no link is shown and nothing is typed into the chat.
    """
    user = users_col.find_one({"user_id": user_id})
    lang = (user or {}).get("lang", "fa")
    index = 0 if lang == "fa" else 1
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1, is_persistent=True, one_time_keyboard=False)
    if PORTAL_ENABLED and os.getenv("WEB_BASE_URL", "").strip():
        try:
            markup.row(KeyboardButton(PANEL_BUTTON_LABELS[index], web_app=WebAppInfo(portal_service.panel_url(user_id))))
            return markup
        except Exception as error:
            print(f"PANEL BUTTON unavailable: {type(error).__name__}", flush=True)
    markup.row(KeyboardButton(PANEL_LABELS[index]))
    return markup

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_bot_globally_disabled():
    setting = settings_col.find_one({"key": "bot_status"})
    if setting and setting.get("status") == "off":
        return True
    return False


def get_admin_reports_markup():
    """Separate portal exports from legacy bot reports to avoid button collisions."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, row_width=2)
    markup.row("👥 کاربران پنل سایت (CSV)", "💳 پرداخت‌های پنل سایت (CSV)")
    markup.row("✅ پرداخت‌های موفق سایت (Excel)", "🌐 آیدی‌های اجتماعی سایت (Excel)")
    markup.row("🧾 سوابق مدیریت سایت (CSV)")
    markup.row("↩️ بازگشت به پنل مدیریت")
    return markup


def _portal_report_csv_value(value, field=""):
    if value is None:
        return ""
    if field.endswith("_at") and isinstance(value, (int, float)) and value:
        try:
            value = datetime.fromtimestamp(value, ZoneInfo("Asia/Tehran")).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    elif isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text_value = str(value)
    if text_value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        text_value = "'" + text_value
    return text_value


def send_portal_csv_report(chat_id, report_kind):
    reports = {
        "users": ("گزارش کاربران پنل سایت", "portal_site_users.csv", list(db.users.find({})),
                  ["user_id", "telegram_username", "registered", "referrals", "referred_by", "earned", "paid", "unpaid", "wallet", "instagram", "twitter", "suspended", "mining_total"]),
        "payments": ("گزارش درخواست‌ها و پرداخت‌های سایت", "portal_site_payments.csv",
                     [with_burn(p) for p in db.portal_payments.find({})],
                     ["id", "user_id", "amount", "net_amount", "burn_amount", "wallet", "status", "tx_hash", "block_number",
                      "reason", "created_at", "reviewed_at", "reviewed_by"]),
        "audit": ("گزارش سوابق مدیریت سایت", "portal_site_admin_audit.csv", list(db.portal_audit.find({})),
                  ["id", "admin_id", "action", "target", "details", "created_at"]),
    }
    if report_kind not in reports:
        return
    title, filename, rows, fields = reports[report_kind]
    if report_kind == "users":
        prepared = []
        for user in rows:
            total = calculate_total_tokens(user.get("ref_count", 0), user.get("daily_count", 0),
                                           user.get("bonus_tokens", 0), user.get("manual_bonus_tokens", 0))
            paid = int(user.get("paid_amount", 0) or 0)
            prepared.append({
                "user_id": user.get("user_id"), "telegram_username": user.get("telegram_username", ""),
                "registered": int(user.get("verified", 0) or 0) >= 1,
                "referrals": user.get("ref_count", 0), "referred_by": user.get("referred_by", ""),
                "earned": total, "paid": paid, "unpaid": max(0, total - paid),
                "wallet": user.get("wallet", ""), "instagram": user.get("instagram") or user.get("instagram_id", ""),
                "twitter": user.get("twitter") or user.get("twitter_id", ""),
                "suspended": bool(user.get("portal_suspended")), "mining_total": user.get("mining_total", 0),
            })
        rows = prepared
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_portal_report_csv_value(row.get(field, ""), field) for field in fields])
    file_bytes = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8"))
    file_bytes.name = filename
    bot.send_document(chat_id, file_bytes, caption=f"📁 {title} · {len(rows):,} ردیف", reply_markup=get_admin_reports_markup())


def send_portal_xlsx_report(chat_id, report_kind):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    if report_kind == "paid":
        rows = [with_burn(p) for p in db.portal_payments.find({"status": "recorded"})]
        headers = ["هش تراکنش", "آیدی عددی تلگرام", "PRS ارسال‌شده", "سهم توکن‌سوزی PRS", "مبلغ کل PRS", "کیف پول", "وضعیت",
                   "بلاک", "زمان درخواست", "زمان پرداخت", "آیدی مدیر"]
        fields = ["tx_hash", "user_id", "net_amount", "burn_amount", "amount", "wallet", "status", "block_number",
                  "created_at", "reviewed_at", "reviewed_by"]
        filename, title, sheet_title = "portal_site_paid_transactions.xlsx", "پرداخت‌های موفق سایت", "پرداخت‌های موفق"
    elif report_kind == "social":
        rows = list(db.users.find({}))
        headers = ["آیدی عددی تلگرام", "نام کاربری تلگرام", "Instagram", "X / Twitter", "کیف پول"]
        fields = ["user_id", "telegram_username", "instagram", "twitter", "wallet"]
        filename, title, sheet_title = "portal_site_social_profiles.xlsx", "آیدی‌های اجتماعی کاربران سایت", "پروفایل‌های اجتماعی"
    else:
        return
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_title
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="8B1E2D")
    if report_kind == "social":
        rows.sort(key=lambda row: int(row.get("user_id", 0) or 0), reverse=True)
    else:
        rows.sort(key=lambda row: row.get("reviewed_at", 0) or 0, reverse=True)
    for row in rows:
        values = []
        for field in fields:
            if report_kind == "social" and field == "instagram":
                value = row.get("instagram") or row.get("instagram_id", "")
            elif report_kind == "social" and field == "twitter":
                value = row.get("twitter") or row.get("twitter_id", "")
            else:
                value = row.get(field, "")
            if field.endswith("_at") and value:
                try:
                    value = datetime.fromtimestamp(value, ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, OverflowError, OSError, ValueError):
                    value = str(value)
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            values.append(value if value is not None else "")
        sheet.append(values)
    for col_index in range(1, len(headers) + 1):
        width = min(60, max(16, max((len(str(sheet.cell(row, col_index).value or "")) for row in range(1, min(sheet.max_row, 150) + 1)), default=12) + 2))
        sheet.column_dimensions[get_column_letter(col_index)].width = width
    output = io.BytesIO()
    book.save(output)
    output.seek(0)
    output.name = filename
    bot.send_document(chat_id, output, caption=f"📁 {title} · {len(rows):,} ردیف", reply_markup=get_admin_reports_markup())

def get_user_data(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return None
    return (
        user.get("ref_count", 0),
        user.get("submitted", 0),
        user.get("paid", 0),
        user.get("verified", 0),
        user.get("last_daily", 0),
        user.get("daily_count", 0),
        user.get("wallet", None),
        user.get("paid_amount", 0),
        user.get("bonus_tokens", 0),
        user.get("manual_bonus_tokens", 0),
        user.get("twitter_id", None),
        user.get("instagram_id", None)
    )

def calculate_tokens(ref_count):
    if ref_count < REQUIRED_REFERRALS:
        return 0
    extra = ref_count - REQUIRED_REFERRALS
    return BASE_REWARD + (extra * EXTRA_REWARD)

def calculate_total_tokens(ref_count, daily_count, bonus_tokens=0, manual_bonus_tokens=0):
    base_ref_tokens = calculate_tokens(ref_count)
    daily_tokens = daily_count * DAILY_REWARD
    return base_ref_tokens + daily_tokens + bonus_tokens + manual_bonus_tokens

def get_global_total_distributed_tokens():
    all_users = users_col.find({}, {"ref_count": 1, "daily_count": 1, "bonus_tokens": 1, "manual_bonus_tokens": 1})
    total = 0
    for u in all_users:
        r_cnt = u.get("ref_count", 0)
        d_cnt = u.get("daily_count", 0)
        total += calculate_total_tokens(
            r_cnt,
            d_cnt,
            u.get("bonus_tokens", 0),
            u.get("manual_bonus_tokens", 0)
        )
    return total

def is_airdrop_finished():
    return get_global_total_distributed_tokens() >= MAX_TOTAL_TOKENS_LIMIT

def remaining_reward_capacity():
    reserved = portal_service.mining_config()["reserved"] if BOT_PORTAL_ONLY else 0
    return max(0, MAX_TOTAL_TOKENS_LIMIT - get_global_total_distributed_tokens() - reserved)


def get_bonus_eligible_filter(operation_id=None):
    query = {
        "ref_count": {"$gte": REQUIRED_REFERRALS},
        "submitted": {"$gt": 0},
        "wallet": {"$regex": r"^0x[a-fA-F0-9]{40}$"}
    }
    if operation_id:
        query["bonus_operation_ids"] = {"$ne": operation_id}
    return query

def notify_portal_bonus_recipients(operation_id, amount, target_uid=None):
    """Best-effort Telegram delivery after the DB commit; never credits twice."""
    import threading
    def worker():
        import time as _time
        try:
            if target_uid is not None:
                recipients = [target_uid]
            else:
                recipients = [u["user_id"] for u in portal_service.store.scan("users", ("user_id", "bonus_operation_ids"))
                              if operation_id in (u.get("bonus_operation_ids") or [])]
            for uid in recipients:
                try:
                    bot.send_message(uid, f"🎁 پاداش جدید PRS\n\n🪙 {amount:,} PRS به حساب شما اضافه شد.\nبرای مشاهده موجودی وارد پنل ایردراپ شوید.")
                except Exception:
                    pass  # blocked users and Telegram outages must not roll back rewards
                _time.sleep(0.05)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True, name="prs-bonus-notify").start()

def execute_global_bonus(admin_chat_id, operation_id, amount):
    if BOT_PORTAL_ONLY:
        try:
            result = portal_service.admin_bot_bonus(admin_chat_id, operation_id, amount)
            if not result.get("already_completed"):
                notify_portal_bonus_recipients(operation_id, amount)
            bot.send_message(admin_chat_id,
                f"✅ پاداش همگانی ثبت شد.\n👥 تعداد: {result['count']:,}\n🎁 هر نفر: {amount:,} PRS\n🪙 مجموع: {result['total']:,} PRS\nنتیجه در حساب سایت کاربران نمایش داده می‌شود.",
                reply_markup=get_admin_reply_markup())
        except PortalError as error:
            bot.send_message(admin_chat_id, portal_bridge.error_text(error, admin_chat_id), reply_markup=get_admin_reply_markup())
        return
    eligible_users = list(users_col.find(
        get_bonus_eligible_filter(operation_id),
        {"user_id": 1, "lang": 1}
    ))
    eligible_count = len(eligible_users)

    if eligible_count == 0:
        bot.send_message(
            admin_chat_id,
            "⚠️ هیچ کاربر واجد شرایطی برای دریافت این پاداش یافت نشد.",
            reply_markup=get_admin_reply_markup()
        )
        return

    total_cost = amount * eligible_count
    current_total = get_global_total_distributed_tokens()
    if current_total + total_cost > MAX_TOTAL_TOKENS_LIMIT:
        remaining_capacity = remaining_reward_capacity()
        bot.send_message(
            admin_chat_id,
            f"❌ عملیات انجام نشد؛ مجموع پاداش از سقف ۳۰۰ میلیون عبور می‌کند.\n\n"
            f"ظرفیت باقی‌مانده: `{remaining_capacity:,} PRS`\n"
            f"مبلغ موردنیاز: `{total_cost:,} PRS`",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
        return

    event_time = int(time.time())
    result = users_col.update_many(
        get_bonus_eligible_filter(operation_id),
        {
            "$inc": {"bonus_tokens": amount},
            "$set": {"paid": 0},
            "$addToSet": {"bonus_operation_ids": operation_id},
            "$push": {
                "bonus_history": {
                    "operation_id": operation_id,
                    "amount": amount,
                    "created_at": event_time,
                    "created_by": admin_chat_id
                }
            }
        }
    )

    success_count = result.modified_count
    bot.send_message(
        admin_chat_id,
        f"✅ پاداش همگانی با موفقیت ثبت شد.\n\n"
        f"👥 دریافت‌کنندگان: `{success_count:,}` نفر\n"
        f"🎁 پاداش هر نفر: `{amount:,} PRS`\n"
        f"🪙 مجموع پاداش ثبت‌شده: `{success_count * amount:,} PRS`\n"
        f"🆔 شناسه عملیات: `{operation_id}`\n\n"
        f"ارسال پیام به کاربران در پس‌زمینه آغاز شد.",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

    def notify_bonus_receivers():
        sent_count = 0
        failed_count = 0
        for idx, user in enumerate(eligible_users):
            try:
                if user.get("lang", "fa") == "en":
                    notification = (
                        f"🎉 *You received a special PRS reward!*\n\n"
                        f"🎁 `{amount:,} PRS` has been added to your account by the PRS team."
                    )
                else:
                    notification = (
                        f"🎉 *شما از طرف مجموعه PRS پاداش دریافت کردید!*\n\n"
                        f"🎁 مبلغ `{amount:,} PRS` به موجودی حساب شما اضافه شد."
                    )
                bot.send_message(user["user_id"], notification, parse_mode="Markdown")
                update_user_delivery_status(user["user_id"], True)
                sent_count += 1
            except Exception as e:
                update_user_delivery_status(user["user_id"], False, e)
                failed_count += 1

            if (idx + 1) % 25 == 0:
                time.sleep(1)

        bot.send_message(
            admin_chat_id,
            f"📨 گزارش ارسال پیام پاداش:\n\n"
            f"✅ ارسال موفق: `{sent_count:,}` نفر\n"
            f"❌ ارسال ناموفق: `{failed_count:,}` نفر",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )

    threading.Thread(target=notify_bonus_receivers, daemon=True).start()

def is_valid_wallet(wallet):
    return bool(isinstance(wallet, str) and re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet.strip()))

def get_eligible_no_wallet_users():
    candidates = users_col.find(
        {"ref_count": {"$gte": REQUIRED_REFERRALS}},
        {"user_id": 1, "ref_count": 1, "wallet": 1, "submitted": 1}
    )
    return [u for u in candidates if not is_valid_wallet(u.get("wallet"))]

def is_blocked_api_error(error):
    error_text = str(error).lower()
    return "bot was blocked by the user" in error_text

def update_user_delivery_status(user_id, success, error=None):
    checked_at = int(time.time())
    if success:
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "bot_blocked": False,
                    "bot_status_checked_at": checked_at,
                    "last_delivery_success_at": checked_at
                },
                "$unset": {"last_delivery_error": ""}
            }
        )
        return False

    error_text = str(error)[:500] if error else "Unknown Telegram delivery error"
    blocked = is_blocked_api_error(error_text)
    update_fields = {
        "bot_status_checked_at": checked_at,
        "last_delivery_error": error_text
    }
    if blocked:
        update_fields["bot_blocked"] = True
        update_fields["bot_blocked_at"] = checked_at

    users_col.update_one({"user_id": user_id}, {"$set": update_fields})
    return blocked

def execute_manual_bonus(admin_chat_id, target_uid, operation_id, amount):
    if BOT_PORTAL_ONLY:
        try:
            result = portal_service.admin_bot_bonus(admin_chat_id, operation_id, amount, target_uid)
            if not result.get("already_completed"):
                notify_portal_bonus_recipients(operation_id, amount, target_uid)
            text = "این عملیات قبلاً ثبت شده است." if result["already_completed"] else f"✅ پاداش {amount:,} PRS برای کاربر {target_uid} ثبت شد.\nنتیجه در حساب سایت کاربر نمایش داده می‌شود."
            bot.send_message(admin_chat_id, text, reply_markup=get_admin_reply_markup())
        except PortalError as error:
            bot.send_message(admin_chat_id, portal_bridge.error_text(error, admin_chat_id), reply_markup=get_admin_reply_markup())
        return
    user = users_col.find_one({"user_id": target_uid})
    if not user:
        bot.send_message(
            admin_chat_id,
            "❌ کاربر موردنظر دیگر در دیتابیس وجود ندارد.",
            reply_markup=get_admin_reply_markup()
        )
        return

    current_total = get_global_total_distributed_tokens()
    remaining_capacity = remaining_reward_capacity()
    if amount > remaining_capacity:
        bot.send_message(
            admin_chat_id,
            f"❌ پاداش ثبت نشد؛ مبلغ از ظرفیت باقی‌مانده ایردراپ بیشتر است.\n\n"
            f"📌 ظرفیت باقی‌مانده: `{remaining_capacity:,} PRS`",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
        return

    event_time = int(time.time())
    result = users_col.update_one(
        {
            "user_id": target_uid,
            "manual_bonus_operation_ids": {"$ne": operation_id}
        },
        {
            "$inc": {"manual_bonus_tokens": amount},
            "$set": {"paid": 0},
            "$addToSet": {"manual_bonus_operation_ids": operation_id},
            "$push": {
                "manual_bonus_history": {
                    "operation_id": operation_id,
                    "amount": amount,
                    "created_at": event_time,
                    "created_by": admin_chat_id
                }
            }
        }
    )

    if result.modified_count != 1:
        bot.send_message(
            admin_chat_id,
            "⚠️ این عملیات قبلاً ثبت شده یا امکان به‌روزرسانی کاربر وجود نداشت.",
            reply_markup=get_admin_reply_markup()
        )
        return

    updated_user = users_col.find_one(
        {"user_id": target_uid},
        {"lang": 1, "manual_bonus_tokens": 1}
    ) or {}
    manual_total = updated_user.get("manual_bonus_tokens", amount)
    notification_sent = True

    try:
        if updated_user.get("lang", "fa") == "en":
            notification = (
                f"🎉 *You received a manual PRS reward from management!*\n\n"
                f"🎁 Reward amount: `{amount:,} PRS`\n"
                f"🎯 Total manual rewards: `{manual_total:,} PRS`\n"
                f"🆔 Operation ID: `{operation_id}`\n\n"
                f"This reward is registered in your account balance."
            )
        else:
            notification = (
                f"🎉 *از طرف مدیریت PRS پاداش دستی دریافت کردید!*\n\n"
                f"🎁 مبلغ پاداش: `{amount:,} PRS`\n"
                f"🎯 مجموع پاداش‌های دستی شما: `{manual_total:,} PRS`\n"
                f"🆔 شناسه عملیات: `{operation_id}`\n\n"
                f"این پاداش در موجودی حساب شما ثبت شده است."
            )
        bot.send_message(target_uid, notification, parse_mode="Markdown")
        update_user_delivery_status(target_uid, True)
    except Exception as e:
        notification_sent = False
        update_user_delivery_status(target_uid, False, e)

    delivery_text = "✅ پیام تأیید نیز برای کاربر ارسال شد." if notification_sent else "⚠️ پاداش ثبت شد، اما پیام تأیید به کاربر تحویل نشد."
    bot.send_message(
        admin_chat_id,
        f"✅ *پاداش دستی با موفقیت ثبت شد.*\n\n"
        f"👤 آیدی کاربر: `{target_uid}`\n"
        f"🎁 مبلغ پاداش: `{amount:,} PRS`\n"
        f"🎯 مجموع پاداش دستی کاربر: `{manual_total:,} PRS`\n"
        f"🆔 شناسه عملیات: `{operation_id}`\n\n"
        f"{delivery_text}",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def send_manual_bonus_report(chat_id):
    users = list(users_col.find(
        {"manual_bonus_history.0": {"$exists": True}},
        {
            "user_id": 1,
            "wallet": 1,
            "manual_bonus_tokens": 1,
            "manual_bonus_history": 1
        }
    ).sort("user_id", 1))

    if not users:
        bot.send_message(
            chat_id,
            "⚠️ هنوز هیچ پاداش دستی برای کاربران ثبت نشده است.",
            reply_markup=get_admin_reply_markup()
        )
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "User ID", "Wallet", "Reward Amount", "User Manual Bonus Total",
        "Operation ID", "Created At (UTC)", "Created By Admin"
    ])

    event_count = 0
    total_amount = 0
    for user in users:
        for event in user.get("manual_bonus_history", []):
            amount = int(event.get("amount", 0) or 0)
            created_at = int(event.get("created_at", 0) or 0)
            created_text = (
                datetime.utcfromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S UTC")
                if created_at else ""
            )
            writer.writerow([
                user.get("user_id", ""),
                user.get("wallet") or "Not Registered",
                amount,
                user.get("manual_bonus_tokens", 0),
                event.get("operation_id", ""),
                created_text,
                event.get("created_by", "")
            ])
            event_count += 1
            total_amount += amount

    file_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    file_bytes.name = "manual_bonus_report.csv"
    bot.send_document(
        chat_id,
        file_bytes,
        caption=(
            f"📊 **گزارش کامل پاداش‌های دستی**\n\n"
            f"👥 کاربران دریافت‌کننده: `{len(users):,}` نفر\n"
            f"🧾 تعداد عملیات: `{event_count:,}`\n"
            f"🎁 مجموع پاداش دستی: `{total_amount:,} PRS`"
        ),
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def send_blocked_users_csv(chat_id, blocked_users, checked_count, unknown_count):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User ID", "Blocked At (UTC)", "Last Check (UTC)", "Telegram Error"])

    for user in blocked_users:
        blocked_at = int(user.get("bot_blocked_at", 0) or 0)
        checked_at = int(user.get("bot_status_checked_at", 0) or 0)
        writer.writerow([
            user.get("user_id", ""),
            datetime.utcfromtimestamp(blocked_at).strftime("%Y-%m-%d %H:%M:%S UTC") if blocked_at else "",
            datetime.utcfromtimestamp(checked_at).strftime("%Y-%m-%d %H:%M:%S UTC") if checked_at else "",
            user.get("last_delivery_error", "")
        ])

    file_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    file_bytes.name = "blocked_bot_users.csv"
    bot.send_document(
        chat_id,
        file_bytes,
        caption=(
            f"🚫 **گزارش بررسی کاربران بلاک‌کننده ربات**\n\n"
            f"👤 تعداد بررسی‌شده: `{checked_count:,}` نفر\n"
            f"🚫 بلاک قطعی: `{len(blocked_users):,}` نفر\n"
            f"⚠️ خطاهای نامشخص: `{unknown_count:,}` مورد"
        ),
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def start_blocked_users_scan(chat_id):
    all_users = list(users_col.find({}, {"user_id": 1}))
    if not all_users:
        bot.send_message(chat_id, "⚠️ هیچ کاربری برای بررسی وجود ندارد.", reply_markup=get_admin_reply_markup())
        return

    bot.send_message(
        chat_id,
        f"🔎 بررسی بی‌صدای وضعیت `{len(all_users):,}` کاربر آغاز شد. پس از پایان، فایل خروجی ارسال می‌شود.",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

    def run_scan():
        unknown_count = 0
        blocked_ids = []
        for idx, user in enumerate(all_users):
            uid = user.get("user_id")
            if not uid:
                continue
            try:
                bot.send_chat_action(uid, "typing")
                update_user_delivery_status(uid, True)
            except Exception as e:
                if update_user_delivery_status(uid, False, e):
                    blocked_ids.append(uid)
                else:
                    unknown_count += 1

            if (idx + 1) % 20 == 0:
                time.sleep(1)

        blocked_users = list(users_col.find(
            {"user_id": {"$in": blocked_ids}},
            {"user_id": 1, "bot_blocked_at": 1, "bot_status_checked_at": 1, "last_delivery_error": 1}
        ).sort("user_id", 1)) if blocked_ids else []
        send_blocked_users_csv(chat_id, blocked_users, len(all_users), unknown_count)

    threading.Thread(target=run_scan, daemon=True).start()

def start_no_wallet_broadcast(chat_id, text):
    recipients = get_eligible_no_wallet_users()
    if not recipients:
        bot.send_message(
            chat_id,
            "⚠️ هیچ کاربری با حداقل ۳ دعوت و بدون ولت معتبر یافت نشد.",
            reply_markup=get_admin_reply_markup()
        )
        return

    bot.send_message(
        chat_id,
        f"🚀 ارسال پیام به `{len(recipients):,}` کاربر واجد شرایطِ بدون ولت آغاز شد...",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

    def run_broadcast():
        success_count = 0
        failed_count = 0
        blocked_count = 0
        for idx, user in enumerate(recipients):
            uid = user.get("user_id")
            try:
                bot.send_message(uid, text)
                update_user_delivery_status(uid, True)
                success_count += 1
            except Exception as e:
                failed_count += 1
                if update_user_delivery_status(uid, False, e):
                    blocked_count += 1

            if (idx + 1) % 25 == 0:
                time.sleep(1)

        bot.send_message(
            chat_id,
            f"📨 **گزارش ارسال پیام به واجدین بی‌ولت:**\n\n"
            f"👥 مخاطبان: `{len(recipients):,}` نفر\n"
            f"✅ ارسال موفق: `{success_count:,}` نفر\n"
            f"❌ ارسال ناموفق: `{failed_count:,}` نفر\n"
            f"🚫 بلاک قطعی ربات: `{blocked_count:,}` نفر",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )

    threading.Thread(target=run_broadcast, daemon=True).start()

def check_membership(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        print(f"Error checking membership: {e}")
    return False

def get_admin_reply_markup():
    markup = ReplyKeyboardMarkup(
        resize_keyboard=True, is_persistent=True, one_time_keyboard=False,
        input_field_placeholder="یکی از دکمه‌های مدیریت را بزن",
    )
    if PORTAL_ENABLED and os.getenv("WEB_BASE_URL", "").strip():
        markup.row("🌐 مدیریت سایت" if BOT_PORTAL_ONLY else PANEL_LABELS[0])
    markup.row("👝 مدیریت و تایید ولت‌ها", "📊 گزارش کلی توکن‌ها")
    markup.row("🔍 جستجوی کاربر (نام کاربری، آیدی یا ولت)", "✏️ ویرایش ولت کاربر با آیدی")
    markup.row("📁 آپلود اکسل پرداختی‌ها", "🟢 اکسل پرداخت‌شده‌ها")
    markup.row("🟡 اکسل در انتظار پرداخت", "📥 اکسل واجدین شرایط بی‌ولت")
    markup.row("📥 اکسل کاربران زیر حد نصاب (<3 دعوت)", "📊 گزارش تفکیکی کامل (فایل)")
    markup.row("📥 دریافت فوری بک‌آپ (JSON)", "📈 آمار کلی ربات")
    markup.row("🎁 پاداش همگانی واجدین شرایط")
    markup.row("🎯 پاداش دستی به کاربر", "📊 اکسل پاداش‌های دستی")
    markup.row("🚫 بررسی و خروجی بلاک‌کنندگان", "📣 پیام به واجدین بی‌ولت")
    markup.row("📂 گزارش‌های پنل سایت")
    markup.row("🔄 به‌روزرسانی پنل ادمین", "📢 ارسال همگانی پیام")
    markup.row("✉️ ارسال پیام شخصی به کاربر", "🔴 خاموش کردن ربات")
    markup.row("🟢 روشن کردن ربات", "🔙 خروج از حالت ادمین / منوی اصلی")
    return markup

def register_user_after_verify(user_id, referrer_id):
    if BOT_PORTAL_ONLY:
        return portal_service.register_gateway_user(user_id, referrer_id)
    user = users_col.find_one({"user_id": user_id})
    valid_referrer = referrer_id if (referrer_id and referrer_id != user_id) else None
    
    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "referred_by": valid_referrer,
            "ref_count": 0,
            "submitted": 0,
            "verified": 1,
            "wallet": None,
            "last_daily": 0,
            "daily_count": 0,
            "paid_amount": 0,
            "manual_bonus_tokens": 0,
            "challenge_quiz_attempts": 0,
            "challenge_quiz_passed": False,
            "lang": "fa"
        })
        
        if valid_referrer:
            users_col.update_one({"user_id": valid_referrer}, {"$inc": {"ref_count": 1}}, upsert=True)
            try:
                ref_user = users_col.find_one({"user_id": valid_referrer})
                current_refs = ref_user.get("ref_count", 1) if ref_user else 1
                d_count = ref_user.get("daily_count", 0) if ref_user else 0
                earned_now = calculate_total_tokens(
                    current_refs,
                    d_count,
                    ref_user.get("bonus_tokens", 0) if ref_user else 0,
                    ref_user.get("manual_bonus_tokens", 0) if ref_user else 0
                )
                ref_lang = ref_user.get("lang", "fa") if ref_user else "fa"
                
                notif_text = (
                    f"🎉 *یک زیرمجموعه جدید با لینک شما وارد شد!*\n\n"
                    f"👥 تعداد کل دعوت‌های شما: `{current_refs}`\n"
                    f"🎁 مجموع توکن کسب‌شده: `{earned_now}` PRS" if ref_lang == "fa" else
                    f"🎉 *A new referral joined via your link!*\n\n"
                    f"👥 Total referrals: `{current_refs}`\n"
                    f"🎁 Total tokens earned: `{earned_now}` PRS"
                )
                bot.send_message(valid_referrer, notif_text, parse_mode="Markdown")
            except Exception:
                pass
    else:
        current_referred_by = user.get("referred_by")
        if not current_referred_by and valid_referrer and int(user.get("verified", 0)) < 1:
            users_col.update_one(
                {"user_id": user_id}, 
                {"$set": {"verified": 1, "referred_by": valid_referrer}}
            )
            users_col.update_one({"user_id": valid_referrer}, {"$inc": {"ref_count": 1}}, upsert=True)
            try:
                ref_user = users_col.find_one({"user_id": valid_referrer})
                current_refs = ref_user.get("ref_count", 1) if ref_user else 1
                d_count = ref_user.get("daily_count", 0) if ref_user else 0
                earned_now = calculate_total_tokens(
                    current_refs,
                    d_count,
                    ref_user.get("bonus_tokens", 0) if ref_user else 0,
                    ref_user.get("manual_bonus_tokens", 0) if ref_user else 0
                )
                ref_lang = ref_user.get("lang", "fa") if ref_user else "fa"
                
                notif_text = (
                    f"🎉 *یک زیرمجموعه جدید با لینک شما وارد شد!*\n\n"
                    f"👥 تعداد کل دعوت‌های شما: `{current_refs}`\n"
                    f"🎁 مجموع توکن کسب‌شده: `{earned_now}` PRS" if ref_lang == "fa" else
                    f"🎉 *A new referral joined via your link!*\n\n"
                    f"👥 Total referrals: `{current_refs}`\n"
                    f"🎁 Total tokens earned: `{earned_now}` PRS"
                )
                bot.send_message(valid_referrer, notif_text, parse_mode="Markdown")
            except Exception:
                pass
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"verified": 1}})

def save_submission(user_id, wallet, current_submitted_status):
    new_status = 1 if current_submitted_status == 0 else 2
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"submitted": new_status, "wallet": wallet, "wallet_lc": wallet.lower()}}
    )


def wallet_used_by_other(user_id, wallet):
    """Legacy (portal off) path: one wallet address per account."""
    return users_col.find_one({"wallet_lc": wallet.strip().lower(), "user_id": {"$ne": user_id}}, {"_id": 1}) is not None


# ---- Captcha attempt limit (values in portal/settings.py, also shown on the rules page) ----


def captcha_lock_remaining(proof):
    return max(0, int((proof or {}).get("locked_until", 0)) - int(time.time()))


def register_captcha_failure(user_id):
    """Count a wrong answer; after CAPTCHA_MAX_ATTEMPTS lock the captcha for a while.

    Returns the remaining lock time in seconds (0 when the user may try again).
    """
    proof = captcha_col.find_one_and_update(
        {"user_id": user_id}, {"$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER) or {}
    if int(proof.get("attempts", 0)) >= CAPTCHA_MAX_ATTEMPTS:
        captcha_col.update_one({"user_id": user_id},
                               {"$set": {"attempts": 0, "locked_until": int(time.time()) + CAPTCHA_LOCK_SECONDS}})
        return CAPTCHA_LOCK_SECONDS
    return 0


def send_captcha_locked(chat_id, user_id, remaining):
    minutes = max(1, (remaining + 59) // 60)
    lang = (users_col.find_one({"user_id": user_id}, {"lang": 1}) or {}).get("lang", "fa")
    text = (f"⛔ Too many wrong answers. Try again in {minutes} minute(s)." if lang == "en"
            else f"⛔ تعداد پاسخ‌های اشتباه زیاد بود. {minutes} دقیقه دیگر دوباره امتحان کن.")
    bot.send_message(chat_id, text)

def normalize_social_handle(value, platform):
    value = (value or "").strip()
    if not value or len(value) > 200:
        return None

    if platform == "twitter":
        url_match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})(?:[/?#].*)?",
            value,
            flags=re.IGNORECASE
        )
        username = url_match.group(1) if url_match else value.lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
            return None
    elif platform == "instagram":
        url_match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})(?:[/?#].*)?",
            value,
            flags=re.IGNORECASE
        )
        username = url_match.group(1) if url_match else value.lstrip("@")
        if (
            not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username)
            or username.startswith(".")
            or username.endswith(".")
            or ".." in username
        ):
            return None
    else:
        return None

    return f"@{username}", username.lower()

def get_social_cancel_markup(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(get_msg(user_id, "social_cancel_btn"))
    return markup

def start_social_registration(chat_id, user_id):
    user = users_col.find_one({"user_id": user_id}) or {}
    not_registered = get_msg(user_id, "social_not_registered")
    current_twitter = user.get("twitter_id") or not_registered
    current_instagram = user.get("instagram_id") or not_registered

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"social_input_state": "waiting_twitter"},
            "$unset": {
                "pending_twitter_id": "",
                "pending_twitter_id_normalized": ""
            }
        }
    )
    bot.send_message(
        chat_id,
        get_msg(
            user_id,
            "social_start",
            twitter=current_twitter,
            instagram=current_instagram
        ),
        reply_markup=get_social_cancel_markup(user_id),
        parse_mode="Markdown"
    )

def handle_social_registration_input(message, text):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return False

    state = user.get("social_input_state")
    if state not in ["waiting_twitter", "waiting_instagram"]:
        return False

    cancel_texts = {
        LANG["fa"]["social_cancel_btn"],
        LANG["en"]["social_cancel_btn"]
    }
    if text in cancel_texts:
        users_col.update_one(
            {"user_id": user_id},
            {"$unset": {
                "social_input_state": "",
                "pending_twitter_id": "",
                "pending_twitter_id_normalized": ""
            }}
        )
        bot.send_message(
            chat_id,
            get_msg(user_id, "social_cancelled"),
            reply_markup=get_main_reply_markup(user_id)
        )
        return True

    if state == "waiting_twitter":
        normalized_result = normalize_social_handle(text, "twitter")
        if not normalized_result:
            bot.send_message(chat_id, get_msg(user_id, "social_invalid_twitter"))
            return True

        display_id, normalized_id = normalized_result
        duplicate = users_col.find_one({
            "twitter_id_normalized": normalized_id,
            "user_id": {"$ne": user_id}
        }, {"user_id": 1})
        if duplicate:
            bot.send_message(chat_id, get_msg(user_id, "social_duplicate_twitter"))
            return True

        users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "social_input_state": "waiting_instagram",
                "pending_twitter_id": display_id,
                "pending_twitter_id_normalized": normalized_id
            }}
        )
        bot.send_message(
            chat_id,
            get_msg(user_id, "social_instagram_prompt", twitter=display_id),
            reply_markup=get_social_cancel_markup(user_id),
            parse_mode="Markdown"
        )
        return True

    normalized_result = normalize_social_handle(text, "instagram")
    if not normalized_result:
        bot.send_message(chat_id, get_msg(user_id, "social_invalid_instagram"))
        return True

    display_id, normalized_id = normalized_result
    duplicate = users_col.find_one({
        "instagram_id_normalized": normalized_id,
        "user_id": {"$ne": user_id}
    }, {"user_id": 1})
    if duplicate:
        bot.send_message(chat_id, get_msg(user_id, "social_duplicate_instagram"))
        return True

    pending_twitter = user.get("pending_twitter_id")
    pending_twitter_normalized = user.get("pending_twitter_id_normalized")
    if not pending_twitter or not pending_twitter_normalized:
        start_social_registration(chat_id, user_id)
        return True

    event_time = int(time.time())
    update_fields = {
        "twitter_id": pending_twitter,
        "twitter_id_normalized": pending_twitter_normalized,
        "instagram_id": display_id,
        "instagram_id_normalized": normalized_id,
        "social_registered": True,
        "social_updated_at": event_time,
        "telegram_username": f"@{message.from_user.username}" if message.from_user.username else ""
    }
    if not user.get("social_registered_at"):
        update_fields["social_registered_at"] = event_time

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": update_fields,
            "$unset": {
                "social_input_state": "",
                "pending_twitter_id": "",
                "pending_twitter_id_normalized": ""
            }
        }
    )
    bot.send_message(
        chat_id,
        get_msg(
            user_id,
            "social_saved",
            twitter=pending_twitter,
            instagram=display_id
        ),
        reply_markup=get_main_reply_markup(user_id),
        parse_mode="Markdown"
    )
    return True

def get_user_language(user_id):
    user = users_col.find_one({"user_id": user_id}, {"lang": 1}) or {}
    return "en" if user.get("lang") == "en" else "fa"

def send_challenge_intro(chat_id, user_id):
    user = users_col.find_one({"user_id": user_id}) or {}
    attempts = int(user.get("challenge_quiz_attempts", 0) or 0)

    if user.get("challenge_quiz_passed") is True:
        bot.send_message(chat_id, get_msg(user_id, "challenge_passed_before"))
        return

    if attempts >= CHALLENGE_QUIZ_MAX_ATTEMPTS:
        bot.send_message(chat_id, get_msg(user_id, "challenge_no_attempts"))
        return

    # فایل وایت‌پیپر قبل از شروع آزمون برای کاربر ارسال می‌شود.
    try:
        if WHITEPAPER_FILE_ID:
            bot.send_document(
                chat_id,
                WHITEPAPER_FILE_ID,
                caption=get_msg(user_id, "challenge_whitepaper_caption")
            )
        elif os.path.isfile(WHITEPAPER_LOCAL_PATH):
            with open(WHITEPAPER_LOCAL_PATH, "rb") as whitepaper_file:
                bot.send_document(
                    chat_id,
                    whitepaper_file,
                    caption=get_msg(user_id, "challenge_whitepaper_caption")
                )
    except Exception as e:
        print(f"Whitepaper delivery error: {e}")

    markup = InlineKeyboardMarkup()
    if WHITEPAPER_URL:
        markup.row(InlineKeyboardButton(
            get_msg(user_id, "challenge_whitepaper_btn"),
            url=WHITEPAPER_URL
        ))
    markup.row(InlineKeyboardButton(
        get_msg(user_id, "challenge_start_btn"),
        callback_data="challenge_begin"
    ))

    bot.send_message(
        chat_id,
        get_msg(
            user_id,
            "challenge_intro",
            required_refs=CHALLENGE_REQUIRED_REFERRALS,
            max_attempts=CHALLENGE_QUIZ_MAX_ATTEMPTS,
            remaining_attempts=CHALLENGE_QUIZ_MAX_ATTEMPTS - attempts
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )

def send_challenge_question(chat_id, user_id):
    user = users_col.find_one({"user_id": user_id}) or {}
    if user.get("challenge_quiz_state") != "in_progress":
        send_challenge_intro(chat_id, user_id)
        return

    attempt_id = str(user.get("challenge_quiz_attempt_id", ""))
    question_index = int(user.get("challenge_quiz_question", 0) or 0)
    if not attempt_id or not 0 <= question_index < len(CHALLENGE_QUIZ):
        send_challenge_intro(chat_id, user_id)
        return

    lang = get_user_language(user_id)
    question = CHALLENGE_QUIZ[question_index]
    options = question["options_en"] if lang == "en" else question["options_fa"]

    markup = InlineKeyboardMarkup()
    for option_index, option_text in enumerate(options):
        markup.row(InlineKeyboardButton(
            option_text,
            callback_data=f"challenge_answer_{attempt_id}_{question_index}_{option_index}"
        ))

    bot.send_message(
        chat_id,
        get_msg(
            user_id,
            "challenge_question",
            number=question_index + 1,
            total=len(CHALLENGE_QUIZ),
            question=question[lang]
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )

def start_challenge_quiz(chat_id, user_id):
    user = users_col.find_one({"user_id": user_id}) or {}
    attempts = int(user.get("challenge_quiz_attempts", 0) or 0)

    if user.get("challenge_quiz_passed") is True:
        bot.send_message(chat_id, get_msg(user_id, "challenge_passed_before"))
        return

    if attempts >= CHALLENGE_QUIZ_MAX_ATTEMPTS:
        bot.send_message(chat_id, get_msg(user_id, "challenge_no_attempts"))
        return

    if (
        user.get("challenge_quiz_state") == "in_progress"
        and user.get("challenge_quiz_attempt_id")
        and 0 <= int(user.get("challenge_quiz_question", 0) or 0) < len(CHALLENGE_QUIZ)
    ):
        send_challenge_question(chat_id, user_id)
        return

    attempt_id = uuid4().hex[:8]
    attempt_filter = {
        "user_id": user_id,
        "challenge_quiz_passed": {"$ne": True}
    }
    if "challenge_quiz_attempts" in user:
        attempt_filter["challenge_quiz_attempts"] = attempts
    else:
        attempt_filter["challenge_quiz_attempts"] = {"$exists": False}

    result = users_col.update_one(
        attempt_filter,
        {"$set": {
            "challenge_quiz_attempts": attempts,
            "challenge_quiz_state": "in_progress",
            "challenge_quiz_attempt_id": attempt_id,
            "challenge_quiz_question": 0,
            "challenge_quiz_answers": [],
            "challenge_quiz_score": 0,
            "challenge_quiz_started_at": int(time.time())
        }}
    )
    if result.modified_count != 1:
        send_challenge_intro(chat_id, user_id)
        return

    send_challenge_question(chat_id, user_id)

def handle_challenge_answer(call):
    match = re.fullmatch(r"challenge_answer_([0-9a-f]{8})_(\d+)_(\d+)", call.data)
    if not match:
        bot.answer_callback_query(call.id, "Invalid quiz answer.", show_alert=True)
        return

    user_id = call.from_user.id
    chat_id = call.message.chat.id
    attempt_id = match.group(1)
    question_index = int(match.group(2))
    option_index = int(match.group(3))

    user = users_col.find_one({"user_id": user_id}) or {}
    if (
        user.get("challenge_quiz_state") != "in_progress"
        or user.get("challenge_quiz_attempt_id") != attempt_id
        or int(user.get("challenge_quiz_question", -1)) != question_index
        or not 0 <= question_index < len(CHALLENGE_QUIZ)
        or not 0 <= option_index < len(CHALLENGE_QUIZ[question_index]["options_fa"])
    ):
        bot.answer_callback_query(
            call.id,
            get_msg(user_id, "challenge_stale_answer"),
            show_alert=True
        )
        return

    is_correct = option_index == CHALLENGE_QUIZ[question_index]["correct"]
    answer_filter = {
        "user_id": user_id,
        "challenge_quiz_state": "in_progress",
        "challenge_quiz_attempt_id": attempt_id,
        "challenge_quiz_question": question_index
    }

    if question_index < len(CHALLENGE_QUIZ) - 1:
        result = users_col.update_one(
            answer_filter,
            {
                "$push": {"challenge_quiz_answers": option_index},
                "$inc": {"challenge_quiz_score": 1 if is_correct else 0},
                "$set": {"challenge_quiz_question": question_index + 1}
            }
        )
        if result.modified_count != 1:
            bot.answer_callback_query(
                call.id,
                get_msg(user_id, "challenge_stale_answer"),
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        send_challenge_question(chat_id, user_id)
        return

    final_score = int(user.get("challenge_quiz_score", 0) or 0) + (1 if is_correct else 0)
    completed_attempts = int(user.get("challenge_quiz_attempts", 0) or 0) + 1
    passed = final_score >= CHALLENGE_QUIZ_PASS_SCORE
    completed_at = int(time.time())
    final_answers = list(user.get("challenge_quiz_answers", [])) + [option_index]
    history_record = {
        "attempt": completed_attempts,
        "score": final_score,
        "passed": passed,
        "answers": final_answers,
        "completed_at": completed_at
    }
    final_fields = {
        "challenge_quiz_state": "completed",
        "challenge_quiz_question": len(CHALLENGE_QUIZ),
        "challenge_quiz_last_score": final_score,
        "challenge_quiz_last_completed_at": completed_at,
        "challenge_quiz_passed": passed
    }
    if passed:
        final_fields["challenge_quiz_passed_at"] = completed_at

    result = users_col.update_one(
        answer_filter,
        {
            "$push": {
                "challenge_quiz_answers": option_index,
                "challenge_quiz_history": history_record
            },
            "$inc": {
                "challenge_quiz_score": 1 if is_correct else 0,
                "challenge_quiz_attempts": 1
            },
            "$set": final_fields
        }
    )
    if result.modified_count != 1:
        bot.answer_callback_query(
            call.id,
            get_msg(user_id, "challenge_stale_answer"),
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    if passed:
        bot.send_message(
            chat_id,
            get_msg(
                user_id,
                "challenge_result_passed",
                score=final_score,
                total=len(CHALLENGE_QUIZ)
            ),
            reply_markup=get_main_reply_markup(user_id),
            parse_mode="Markdown"
        )
        return

    remaining_attempts = max(0, CHALLENGE_QUIZ_MAX_ATTEMPTS - completed_attempts)
    retry_markup = None
    if remaining_attempts > 0:
        retry_markup = InlineKeyboardMarkup()
        retry_markup.row(InlineKeyboardButton(
            get_msg(user_id, "challenge_retry_btn"),
            callback_data="challenge_begin"
        ))
    bot.send_message(
        chat_id,
        get_msg(
            user_id,
            "challenge_result_failed",
            score=final_score,
            total=len(CHALLENGE_QUIZ),
            remaining_attempts=remaining_attempts
        ),
        reply_markup=retry_markup or get_main_reply_markup(user_id),
        parse_mode="Markdown"
    )

def get_ref_details(ref_count):
    if ref_count >= REQUIRED_REFERRALS:
        base_used = REQUIRED_REFERRALS
        extra_count = ref_count - REQUIRED_REFERRALS
    else:
        base_used = ref_count
        extra_count = 0
    return base_used, extra_count

def send_language_selection(chat_id, referrer_id):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🇮🇷 فارسی", callback_data=f"setlang_fa_{referrer_id}"),
        InlineKeyboardButton("🇬🇧 English", callback_data=f"setlang_en_{referrer_id}")
    )
    bot.send_message(
        chat_id,
        "🌐 **لطفاً زبان خود را انتخاب کنید / Please select your language:**",
        reply_markup=markup,
        parse_mode="Markdown"
    )

def send_captcha(chat_id, user_id, referrer_id):
    existing = captcha_col.find_one({"user_id": user_id})
    remaining = captcha_lock_remaining(existing)
    if remaining:
        send_captcha_locked(chat_id, user_id, remaining)
        return
    num1 = random.randint(11, 49)
    num2 = random.randint(2, 9)
    correct_ans = num1 + num2

    # Keep the attempt counter and lock across new questions; replacing the
    # whole document used to reset them.
    captcha_col.update_one(
        {"user_id": user_id},
        {"$set": {"num1": num1, "num2": num2, "answer": correct_ans,
                  "pending_referrer": referrer_id, "solved_at": 0},
         "$setOnInsert": {"attempts": 0, "locked_until": 0}},
        upsert=True
    )

    text = get_msg(user_id, "captcha_title", num1, num2)
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_main_reply_markup(user_id))

BACKUP_MAX_BYTES = 45 * 1024 * 1024  # Telegram bots can upload at most 50 MB


def build_database_backup(prefix):
    """Compressed JSON of the users collection, or None when it is too large for Telegram."""
    import gzip
    all_users = list(users_col.find({}, {"_id": 0}))
    if not all_users:
        return None, 0
    raw = json.dumps(all_users, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(raw, compresslevel=9)
    if len(packed) > BACKUP_MAX_BYTES:
        return "too_large", len(all_users)
    file_bytes = io.BytesIO(packed)
    file_bytes.name = f"{prefix}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json.gz"
    return file_bytes, len(all_users)


def send_database_backup(target_chat_id):
    try:
        file_bytes, count = build_database_backup("manual_backup")
        if file_bytes is None:
            bot.send_message(target_chat_id, "⚠️ دیتابیس خالی است و کاربری برای بک‌آپ وجود ندارد.", reply_markup=get_admin_reply_markup())
            return
        if file_bytes == "too_large":
            bot.send_message(target_chat_id, "⚠️ حجم بک‌آپ از سقف ارسال تلگرام بیشتر است. از بک‌آپ خود MongoDB (مثلاً Atlas) استفاده کن.", reply_markup=get_admin_reply_markup())
            return
        bot.send_document(
            target_chat_id,
            file_bytes,
            caption=f"⚙️ فایل پشتیبان فشرده کاربران ({count:,} نفر) · شامل کیف پول‌ها؛ آن را جایی امن نگه دار و برای کسی نفرست.",
            reply_markup=get_admin_reply_markup()
        )
    except Exception as e:
        bot.send_message(target_chat_id, f"❌ خطا در تهیه بک‌آپ ({type(e).__name__}).", reply_markup=get_admin_reply_markup())

def auto_backup_scheduler():
    while True:
        time.sleep(86400)
        try:
            file_bytes, count = build_database_backup("auto_backup")
            if file_bytes == "too_large":
                bot.send_message(ADMIN_CHAT_ID, "⚠️ بک‌آپ خودکار ارسال نشد: حجم از سقف تلگرام بیشتر است. از بک‌آپ MongoDB استفاده کن.")
            elif file_bytes is not None:
                bot.send_document(
                    ADMIN_CHAT_ID,
                    file_bytes,
                    caption=f"⚙️ پشتیبان‌گیری خودکار روزانه ({count:,} کاربر) · فایل فشرده؛ شامل کیف پول‌ها."
                )
        except Exception as e:
            print(f"Auto backup error: {type(e).__name__}", flush=True)


def portal_message_scheduler():
    """Send queued Telegram messages: withdrawal alerts to admins, cancellations and referral changes to users."""
    messages = db.portal_messages
    while True:
        item = None
        now = int(time.time())
        try:
            messages.update_many({"status": "sending", "updated_at": {"$lt": now - 120}},
                                 {"$set": {"status": "pending", "retry_at": now}})
            item = messages.find_one_and_update(
                {"status": "pending", "retry_at": {"$lte": now}},
                {"$set": {"status": "sending", "updated_at": now}, "$inc": {"attempts": 1}},
                sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
            if not item:
                time.sleep(3)
                continue
            bot.send_message(item["chat_id"], item["text"], disable_web_page_preview=True)
            messages.update_one({"_id": item["_id"], "status": "sending"},
                                {"$set": {"status": "sent", "sent_at": int(time.time())}})
            time.sleep(0.05)
        except Exception as error:
            if item:
                attempts = int(item.get("attempts", 1))
                # A user who blocked the bot will never receive it: stop retrying.
                failed = is_blocked_api_error(error) or attempts >= 8
                update = ({"status": "failed", "failed_at": int(time.time())} if failed else
                          {"status": "pending", "retry_at": int(time.time()) + min(3600, 30 * (2 ** (attempts - 1)))})
                try:
                    messages.update_one({"_id": item["_id"], "status": "sending"}, {"$set": update})
                except Exception:
                    pass
            print(f"Portal message delivery failed: {bot_failure_label(error)}", flush=True)
            time.sleep(2)


def is_campaign_channel(chat):
    channel = CHANNEL_ID.strip()
    if channel.startswith("@"):
        return (getattr(chat, "username", "") or "").casefold() == channel[1:].casefold()
    return str(getattr(chat, "id", "")) == channel


def channel_member_state(member):
    """True / False from a Telegram ChatMember; None when the status is unclear."""
    status = getattr(member, "status", "")
    if status in ("member", "administrator", "creator"):
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    if status in ("left", "kicked"):
        return False
    return None


def channel_membership(user_id):
    """Strict check for referral deductions: any Telegram error is "unknown" (None), never "left"."""
    try:
        return channel_member_state(bot.get_chat_member(CHANNEL_ID, user_id))
    except Exception:
        return None


REFERRAL_CHECK_DELAY = 0.25        # 4 Telegram lookups per second
REFERRAL_SWEEP_PAUSE = 1800        # 30 minutes between full passes


def bot_is_channel_admin():
    try:
        me = bot.get_me()
        return getattr(bot.get_chat_member(CHANNEL_ID, me.id), "status", "") in ("administrator", "creator")
    except Exception:
        return False


def referral_membership_scheduler():
    """Check every invited user's channel membership; leaves remove the inviter's referral reward."""
    time.sleep(60)
    last_warning = 0
    while True:
        try:
            if not bot_is_channel_admin():
                # Without admin rights Telegram's answers are unreliable: change nothing.
                if time.time() - last_warning > 86400:
                    last_warning = time.time()
                    print("REFERRAL CHECK PAUSED: the bot is not an administrator of the channel", flush=True)
                    for admin_id in ADMIN_IDS:
                        try:
                            bot.send_message(admin_id, "⚠️ بررسی خروج زیرمجموعه‌ها متوقف است: ربات ادمین کانال نیست. "
                                                       "ربات را در کانال ادمین کنید.")
                        except Exception:
                            pass
            else:
                invitees = [u["user_id"] for u in users_col.find(
                    {"referred_by": {"$gt": 0}, "verified": {"$gte": 1}}, {"user_id": 1})]
                changed = 0
                for uid in invitees:
                    state = channel_membership(uid)
                    if state is not None:
                        try:
                            result = portal_service.update_referral_membership(uid, state)
                            changed += isinstance(result, dict)
                        except Exception as error:
                            print(f"Referral check failed: {type(error).__name__}", flush=True)
                    time.sleep(REFERRAL_CHECK_DELAY)
                print(f"REFERRAL CHECK: {len(invitees)} checked, {changed} changed", flush=True)
        except Exception as error:
            print(f"REFERRAL CHECK error: {type(error).__name__}", flush=True)
        time.sleep(REFERRAL_SWEEP_PAUSE)


def portal_maintenance_scheduler():
    """Every 10 minutes: return unclaimed, expired mining reservations to the budget."""
    while True:
        time.sleep(600)
        try:
            released = portal_service.expire_mining_cycles()
            if released:
                print(f"PORTAL MAINTENANCE: released {released} expired mining cycle(s)", flush=True)
        except Exception as e:
            print(f"PORTAL MAINTENANCE failed: {type(e).__name__}", flush=True)


def portal_payment_notification_scheduler():
    """Deliver confirmed on-chain payment notices from the durable outbox."""
    notifications = db.portal_payment_notifications
    while True:
        item = None
        now = int(time.time())
        try:
            # Re-queue work left claimed by a process that stopped unexpectedly.
            notifications.update_many(
                {"status": "sending", "updated_at": {"$lt": now - 120}},
                {"$set": {"status": "pending", "retry_at": now}},
            )
            item = notifications.find_one_and_update(
                {"status": "pending", "retry_at": {"$lte": now}},
                {"$set": {"status": "sending", "updated_at": now}, "$inc": {"attempts": 1}},
                sort=[("created_at", 1)], return_document=ReturnDocument.AFTER,
            )
            if not item:
                time.sleep(5)
                continue
            user = users_col.find_one({"user_id": item["user_id"]}, {"lang": 1}) or {}
            if user.get("lang", "fa") == "en":
                message = (
                    f"✅ Your transaction was confirmed and {int(item['amount']):,} PRS "
                    f"was sent to your wallet.\nTransaction hash: {item['tx_hash']}\n"
                    f"https://bscscan.com/tx/{item['tx_hash']}"
                )
            else:
                message = (
                    f"✅ تراکنش با موفقیت ثبت شد و {int(item['amount']):,} PRS برای شما ارسال شد.\n"
                    f"هش تراکنش: {item['tx_hash']}\n"
                    f"https://bscscan.com/tx/{item['tx_hash']}"
                )
            bot.send_message(item["user_id"], message, disable_web_page_preview=True)
            notifications.update_one(
                {"_id": item["_id"], "status": "sending"},
                {"$set": {"status": "sent", "sent_at": int(time.time())}},
            )
        except Exception:
            # Do not log exception text; Telegram client errors can include URLs.
            if item:
                attempts = int(item.get("attempts", 1))
                retry_at = int(time.time()) + min(3600, 30 * (2 ** min(attempts - 1, 7)))
                try:
                    notifications.update_one(
                        {"_id": item["_id"], "status": "sending"},
                        {"$set": {"status": "pending", "retry_at": retry_at,
                                  "last_attempt_at": int(time.time())}},
                    )
                except Exception:
                    pass
            print("Payment notice delivery failed; queued for retry.", flush=True)
            time.sleep(3)

def send_eligible_no_wallet_excel(chat_id):
    rows = list(users_col.find({"ref_count": {"$gte": REQUIRED_REFERRALS}, "$or": [{"submitted": 0}, {"submitted": {"$exists": False}}]}).sort("ref_count", -1))

    if not rows:
        bot.send_message(chat_id, "⚠️ هیچ کاربری با شرایط «دعوت ۳ نفر به بالا و بدون ثبت ولت» یافت نشد.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Referrals,Daily Bonus Count,Total Tokens,Wallet Status\n"
    for u in rows:
        uid = u.get("user_id")
        ref_cnt = u.get("ref_count", 0)
        d_count = u.get("daily_count", 0)
        total_tokens = calculate_total_tokens(
            ref_cnt, d_count, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
        )
        csv_content += f"{uid},{ref_cnt},{d_count},{total_tokens},Not Registered\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8-sig'))
    file_bytes.name = 'eligible_no_wallet_users.csv'
    
    bot.send_document(
        chat_id, 
        file_bytes, 
        caption="📁 فایل کاربران **واجد شرایط (دعوت ۳ نفر به بالا) که هنوز ولت ثبت نکرده‌اند**", 
        reply_markup=get_admin_reply_markup(), 
        parse_mode="Markdown"
    )

def send_under_threshold_excel(chat_id):
    rows = list(users_col.find({"ref_count": {"$lt": REQUIRED_REFERRALS}}).sort("ref_count", -1))

    if not rows:
        bot.send_message(chat_id, "⚠️ هیچ کاربری با تعداد دعوت کمتر از ۳ نفر یافت نشد.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Referrals,Daily Bonus Count,Total Tokens,Wallet Status,Submission Status\n"
    for u in rows:
        uid = u.get("user_id")
        ref_cnt = u.get("ref_count", 0)
        d_count = u.get("daily_count", 0)
        total_tokens = calculate_total_tokens(
            ref_cnt, d_count, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
        )
        wlt = u.get("wallet")
        wallet_status = f"Registered ({wlt})" if wlt else "Not Registered"
        sub_status = u.get("submitted", 0)
        
        csv_content += f"{uid},{ref_cnt},{d_count},{total_tokens},{wallet_status},{sub_status}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8-sig'))
    file_bytes.name = 'under_threshold_users.csv'
    
    bot.send_document(
        chat_id, 
        file_bytes, 
        caption="📁 فایل کاربران **زیر حد نصاب (کمتر از ۳ دعوت)**", 
        reply_markup=get_admin_reply_markup(), 
        parse_mode="Markdown"
    )

# Install before the legacy catch-all handlers. Both paths use the same service.
portal_service = build_service(database=db, member_check=check_membership)
portal_bridge = BotBridge(
    bot, portal_service,
    lambda uid: get_admin_reply_markup() if is_admin(uid) else get_main_reply_markup(uid),
    [value for messages in LANG.values() for key, value in messages.items() if key.startswith("main_kb_")]
)
if PORTAL_ENABLED and not BOT_PORTAL_ONLY:
    portal_bridge.install()


def send_portal_entry(user_id, link=False):
    """Registration steps first; then the panel button (or, with link=True, a personal sign-in link)."""
    user = users_col.find_one({"user_id": user_id}) or {}
    if user.get("portal_suspended"):
        bot.send_message(user_id, "حساب شما تعلیق شده است. / Your account is suspended.", reply_markup=ReplyKeyboardRemove())
        return
    if int(user.get("verified", 0)) < 1:
        pending = captcha_col.find_one({"user_id": user_id})
        if pending:
            if pending.get("solved_at"):
                ask_to_join(user_id, pending["pending_referrer"] or 0, user_id)
            elif captcha_lock_remaining(pending):
                send_captcha_locked(user_id, user_id, captcha_lock_remaining(pending))
            else:
                bot.send_message(user_id, get_msg(user_id, "captcha_title", pending["num1"], pending["num2"]))
        else:
            send_captcha(user_id, user_id, user.get("registration_referrer") or 0)
        return
    if not check_membership(user_id):
        ask_to_join(user_id, 0, user_id)
        return
    message = type("PrivateMessage", (), {
        "from_user": type("User", (), {"id": user_id})(),
        "chat": type("Chat", (), {"id": user_id, "type": "private"})(),
    })()
    (portal_bridge.send_link if link else portal_bridge.send_login)(message)


def gateway_welcome(message):
    uid = message.from_user.id
    user = users_col.find_one({"user_id": uid}) or {}
    telegram_username = getattr(message.from_user, "username", None)
    if telegram_username:
        users_col.update_one({"user_id": uid}, {"$set": {"telegram_username": f"@{telegram_username}"}})
    args = (message.text or "").split()
    ref = int(args[1]) if len(args) > 1 and len(args[1]) <= 20 and args[1].isdecimal() else 0
    if ref == uid:
        ref = 0
    if ref and int(user.get("verified", 0)) < 1 and not user.get("registration_referrer") and not user.get("referred_by"):
        users_col.update_one({"user_id": uid}, {"$set": {"registration_referrer": ref}}, upsert=True)
    if not user.get("lang") and int(user.get("verified", 0)) < 1:
        lang = "fa" if getattr(message.from_user, "language_code", "fa").startswith("fa") else "en"
        users_col.update_one({"user_id": uid}, {"$set": {"lang": lang}}, upsert=True)
    send_portal_entry(uid)


def gateway_captcha_reply(message):
    uid = message.from_user.id
    proof = captcha_col.find_one({"user_id": uid})
    text = (message.text or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not proof:
        send_portal_entry(uid)
        return
    remaining = captcha_lock_remaining(proof)
    if remaining:
        send_captcha_locked(uid, uid, remaining)
        return
    if not re.fullmatch(r"[0-9]{1,3}", text) or int(text) != proof["answer"]:
        locked = register_captcha_failure(uid)
        if locked:
            send_captcha_locked(uid, uid, locked)
            return
        send_captcha(uid, uid, proof.get("pending_referrer") or 0)
        return
    captcha_col.update_one({"user_id": uid}, {"$set": {"solved_at": int(time.time())}})
    if not check_membership(uid):
        ask_to_join(uid, proof.get("pending_referrer") or 0, uid)
        return
    register_user_after_verify(uid, proof.get("pending_referrer"))
    if getattr(message.from_user, "username", None):
        users_col.update_one({"user_id": uid}, {"$set": {"telegram_username": f"@{message.from_user.username}"}})
    captcha_col.delete_one({"user_id": uid})
    send_portal_entry(uid)


def send_admin_website(user_id):
    """Keep the admin reply menu visible while issuing a private site login."""
    if not is_admin(user_id):
        return send_portal_entry(user_id)
    captcha_col.delete_one({"user_id": user_id})
    try:
        url = portal_service.issue_login(user_id)
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🌐 ورود به مدیریت سایت", url=url))
        bot.send_message(user_id, "🔐 مدیریت سایت؛ لینک شخصی یک‌بارمصرف با اعتبار ۵ دقیقه.\nبرای مدیریت در ربات، منوی پایین همچنان فعال است.",
                         reply_markup=keyboard, protect_content=False)
    except PortalError as error:
        bot.send_message(user_id, portal_bridge.error_text(error, user_id), reply_markup=get_admin_reply_markup())


def route_admin_message(message):
    """Only server-configured admins, only in their own private conversation."""
    if not is_admin(message.from_user.id) or message.chat.type != "private" or message.chat.id != message.from_user.id:
        return
    uid = message.from_user.id
    text = (message.text or "").strip()
    parts = text.split()
    command = parts[0].split("@")[0] if parts else ""
    if (command in ("/panel", "/site") or text in (*PANEL_LABELS, *PANEL_BUTTON_LABELS, "🌐 مدیریت سایت")
            or getattr(message, "content_type", "text") == "web_app_data"
            or (command == "/start" and parts[1:] == ["portal"])):
        send_admin_website(uid)
    elif command in ("/start", "/menu", "/admin"):
        captcha_col.delete_one({"user_id": uid})
        admin_panel(message)
    elif command == "/register":
        gateway_welcome(message)
    elif getattr(message, "content_type", "text") == "document":
        handle_admin_documents(message)
    elif text and not text.startswith("/") and captcha_col.find_one({"user_id": uid}):
        gateway_captcha_reply(message)
    else:
        handle_all_messages(message)


if BOT_PORTAL_ONLY:
    # These handlers precede every legacy command, upload and reward handler.
    @bot.message_handler(content_types=["text", "document", "photo", "video", "audio", "voice", "sticker", "contact", "location", "animation", "video_note", "web_app_data"])
    def portal_only_message(message):
        if message.chat.type != "private":
            return
        # Confirm receipt without recording chat IDs, answers or message text.
        print("BOT UPDATE: private message received", flush=True)
        if is_admin(message.from_user.id):
            try:
                route_admin_message(message)
            except PortalError as error:
                bot.send_message(message.from_user.id, portal_bridge.error_text(error, message.from_user.id), reply_markup=get_admin_reply_markup())
            return
        text = (message.text or "").strip()
        command = text.split()[0].split("@")[0] if text else ""
        if command in ("/start", "/menu", "/register"):
            send_welcome(message)
        elif text in PANEL_BUTTON_LABELS:
            # Only a Telegram app too old to open the panel button sends its text: give a sign-in link.
            send_portal_entry(message.from_user.id, link=True)
        elif text and not text.startswith("/") and captcha_col.find_one({"user_id": message.from_user.id}):
            # Only the registration captcha can consume a text reply here.
            try:
                gateway_captcha_reply(message)
            except PortalError as error:
                bot.send_message(message.from_user.id, portal_bridge.error_text(error, message.from_user.id))
        else:
            send_portal_entry(message.from_user.id)

    @bot.callback_query_handler(func=lambda call: True)
    def portal_only_callback(call):
        uid = call.from_user.id
        message = getattr(call, "message", None)
        private = message and getattr(message.chat, "type", None) == "private" and message.chat.id == uid
        if private:
            print("BOT UPDATE: private callback received", flush=True)
        data = call.data or ""
        if is_admin(uid) and private and data.startswith("admin_"):
            handle_callbacks(call)
            return
        if is_admin(uid) and private and data == "portal:open":
            bot.answer_callback_query(call.id)
            send_admin_website(uid)
            return
        if private and re.fullmatch(r"check_join_\d+", data):
            user = users_col.find_one({"user_id": uid}) or {}
            proof = captcha_col.find_one({"user_id": uid}) or {}
            if int(user.get("verified", 0)) < 1 and (not proof.get("solved_at") or int(time.time()) - proof["solved_at"] > 900):
                bot.answer_callback_query(call.id, "ابتدا کپچا را پاسخ بده. / Solve the captcha first.")
                send_captcha(uid, uid, proof.get("pending_referrer") or user.get("registration_referrer") or 0)
                return
            if not check_membership(uid):
                bot.answer_callback_query(call.id, portal_bridge.text(uid, "هنوز عضو کانال نشده‌ای.", "Please join the channel first."), show_alert=True)
                return
            bot.answer_callback_query(call.id)
            try:
                if int(user.get("verified", 0)) < 1:
                    register_user_after_verify(uid, proof.get("pending_referrer"))
                    captcha_col.delete_one({"user_id": uid})
                send_portal_entry(uid)
            except PortalError as error:
                bot.send_message(uid, portal_bridge.error_text(error, uid))
            return
        bot.answer_callback_query(call.id, portal_bridge.text(uid,
            "فعالیت‌ها از پنل سایت انجام می‌شوند.", "Please use the website portal."))
        send_portal_entry(uid)

if PORTAL_ENABLED:
    @bot.chat_member_handler()
    def channel_member_update(update):
        try:
            if not is_campaign_channel(update.chat):
                return
            member = update.new_chat_member
            state = channel_member_state(member)
            if state is not None:
                portal_service.update_referral_membership(member.user.id, state)
        except Exception as error:
            print(f"Channel member update failed: {type(error).__name__}", flush=True)


def claim_bot_daily(user_id):
    if PORTAL_ENABLED:
        return portal_service.claim_daily(user_id)
    # Rollout remains opt-in; a legacy standalone MongoDB still supports this CAS.
    if not check_membership(user_id):
        raise PortalError("membership_required", 403)
    user = users_col.find_one({"user_id": user_id})
    if not user or user.get("ref_count", 0) < REQUIRED_REFERRALS:
        raise PortalError("referrals_required", 403)
    if is_bot_globally_disabled():
        raise PortalError("campaign_paused", 403)
    if is_airdrop_finished():
        raise PortalError("campaign_budget_exhausted", 409)
    current_time = int(time.time())
    result = users_col.update_one(
        {"user_id": user_id, "$or": [{"last_daily": {"$lte": current_time - 86400}}, {"last_daily": {"$exists": False}}]},
        {"$set": {"last_daily": current_time}, "$inc": {"daily_count": 1}}
    )
    if not result.modified_count:
        raise PortalError("daily_cooldown", 409)
    return {"amount": DAILY_REWARD}

@bot.message_handler(commands=['start', 'menu', 'register'])
def send_welcome(message):
    if BOT_PORTAL_ONLY:
        if is_admin(message.from_user.id):
            return route_admin_message(message)
        return gateway_welcome(message)
    user_id = message.from_user.id
    telegram_username = getattr(message.from_user, "username", None)
    if telegram_username:
        users_col.update_one({"user_id": user_id}, {"$set": {"telegram_username": f"@{telegram_username}"}})
    command = (message.text or "").split()[0].split("@")[0]
    registration_requested = command == "/register"

    if (registration_requested or BOT_PORTAL_ONLY) and message.chat.type != "private":
        bot.send_message(message.chat.id, "برای ثبت‌نام، در گفت‌وگوی خصوصی ربات /register را بفرست. / Send /register in the bot's private chat.")
        return
    
    if is_admin(user_id) and not registration_requested and not BOT_PORTAL_ONLY:
        # /start and /menu return to management and cancel a pending captcha.
        captcha_col.delete_one({"user_id": user_id})
        bot.send_message(
            user_id, 
            "👑 *به پنل مدیریت خوش آمدید.*\nاز دکمه‌های منوی پایین استفاده کنید.\nبرای ثبت‌نام کاربری، /register را بفرستید.",
            reply_markup=get_admin_reply_markup(), 
            parse_mode="Markdown"
        )
        return

    if is_bot_globally_disabled():
        bot.send_message(message.chat.id, get_msg(user_id, "global_off"))
        return

    if is_airdrop_finished():
        bot.send_message(user_id, get_msg(user_id, "airdrop_finished"))
        return

    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    if not referrer_id:
        pending = captcha_col.find_one({"user_id": user_id})
        if pending:
            referrer_id = pending.get("pending_referrer") or None
        if not referrer_id:
            user = users_col.find_one({"user_id": user_id}) or {}
            if int(user.get("verified", 0)) < 1:
                referrer_id = user.get("registration_referrer") or None
    
    if referrer_id == user_id:
        bot.send_message(message.chat.id, get_msg(user_id, "self_ref"), parse_mode="Markdown")
        return

    user = users_col.find_one({"user_id": user_id}) or {}
    if referrer_id and int(user.get("verified", 0)) < 1 and not user.get("registration_referrer"):
        # Preserve attribution if the user opens the website before selecting a language.
        users_col.update_one({"user_id": user_id}, {"$set": {"registration_referrer": referrer_id}}, upsert=True)

    if message.text and message.text.startswith('/menu'):
        if not check_membership(user_id):
            ask_to_join(message.chat.id, 0, user_id)
            return
        show_main_menu(message.chat.id, user_id)
        return

    user_data = get_user_data(user_id)
    if PORTAL_ENABLED and len(args) > 1 and args[1] == "portal" and user_data and user_data[3] >= 1:
        if BOT_PORTAL_ONLY:
            send_portal_entry(user_id)
        else:
            portal_bridge.send_login(message)
        return
    if user_data and user_data[3] >= 1:
        if not check_membership(user_id):
            ask_to_join(message.chat.id, referrer_id if referrer_id else 0, user_id)
            return
        if referrer_id:
            # Keep the existing attribution rule for users without a referrer.
            register_user_after_verify(user_id, referrer_id)
        show_main_menu(message.chat.id, user_id)
        return

    send_language_selection(message.chat.id, referrer_id if referrer_id else 0)

def ask_to_join(chat_id, referrer_id, user_id_or_lang="fa"):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(get_msg(user_id_or_lang, "join_btn"), url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    markup.row(InlineKeyboardButton(get_msg(user_id_or_lang, "joined_btn"), callback_data=f"check_join_{referrer_id}"))
    
    text = get_msg(user_id_or_lang, "join_req", CHANNEL_ID)
    bot.send_message(
        chat_id,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )

def get_user_rank(user_id):
    all_users = list(users_col.find({}))
    scored_users = []
    for u in all_users:
        uid = u.get("user_id")
        r_cnt = u.get("ref_count", 0)
        d_cnt = u.get("daily_count", 0)
        total = calculate_total_tokens(
            r_cnt, d_cnt, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
        )
        scored_users.append((uid, total, r_cnt))
    
    scored_users.sort(key=lambda x: (x[1], x[2]), reverse=True)
    for idx, (uid, _, _) in enumerate(scored_users, 1):
        if uid == user_id:
            return idx
    return "N/A"

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        return
    bot.send_message(
        message.from_user.id,
        "👑 *پنل مدیریت فعال است.*",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def show_token_summary_direct(chat_id):
    rows = list(users_col.find(
        {"submitted": {"$gt": 0}},
        {"ref_count": 1, "daily_count": 1, "bonus_tokens": 1, "manual_bonus_tokens": 1, "paid_amount": 1}
    ))

    total_all_tokens = get_global_total_distributed_tokens()
    paid_tokens = 0
    unpaid_tokens = 0

    for u in rows:
        r_cnt = u.get("ref_count", 0)
        d_cnt = u.get("daily_count", 0)
        t_tokens = calculate_total_tokens(
            r_cnt, d_cnt, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
        )
        paid_amount = min(max(0, u.get("paid_amount", 0)), t_tokens)
        paid_tokens += paid_amount
        unpaid_tokens += max(0, t_tokens - paid_amount)

    text = (
        f"📊 *گزارش جامع توکن‌های ایردراپ:*\n\n"
        f"🪙 کل توکن‌های کسب‌شده توسط تمام کاربران: `{total_all_tokens:,} PRS`\n"
        f"🟢 کل توکن‌های پرداخت‌شده به کاربران تایید شده: `{paid_tokens:,} PRS`\n"
        f"🟡 کل توکن‌های در انتظار پرداخت (پرداخت‌نشده): `{unpaid_tokens:,} PRS`\n\n"
        f"📌 سقف کل ایردراپ: `{MAX_TOTAL_TOKENS_LIMIT:,} PRS`"
    )
    bot.send_message(chat_id, text, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def send_paginated_wallets(message, offset=0, edit=False):
    rows = list(users_col.find({"submitted": {"$gt": 0}}).sort("ref_count", -1))

    if not rows:
        msg = "⚠️ هیچ کاربری هنوز فرم اطلاعاتش را ارسال نکرده است."
        if edit:
            bot.edit_message_text(msg, chat_id=message.chat.id, message_id=message.message_id)
        else:
            bot.send_message(message.chat.id, msg, reply_markup=get_admin_reply_markup())
        return

    limit = 5
    page_rows = rows[offset:offset+limit]

    text = f"👝 **لیست کاربران ثبت‌نام کرده (مجموع: {len(rows)} نفر):**\n\n"
    markup = InlineKeyboardMarkup()

    for u in page_rows:
        uid = u.get("user_id")
        ref_cnt = u.get("ref_count", 0)
        wlt = u.get("wallet", "None")
        paid = u.get("paid", 0)
        d_count = u.get("daily_count", 0)
        paid_amt = u.get("paid_amount", 0)
        manual_bonus = u.get("manual_bonus_tokens", 0)
        
        total_tokens = calculate_total_tokens(
            ref_cnt, d_count, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
        )
        remaining_tokens = max(0, total_tokens - paid_amt)
        base_used, extra_count = get_ref_details(ref_cnt)
        status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
        
        text += f"📌 آیدی عددی: `{uid}`\n" \
                f"👝 ولت: `{wlt}`\n" \
                f"👥 دعوت ثابت: {base_used} | مازاد: {extra_count} (کل: {ref_cnt})\n" \
                f"🎯 پاداش دستی مدیریت: `{manual_bonus:,} PRS`\n" \
                f"🎁 کل توکن: `{total_tokens:,}` | پرداخت‌شده: `{paid_amt:,}` | باقی‌مانده: `{remaining_tokens:,}` PRS\n" \
                f"وضعیت: *{status_str}*\n" \
                f"----------------------------------\n"
        
        btn_pay = InlineKeyboardButton(f"✅ تایید ({uid})", callback_data=f"admin_pay_{uid}_yes")
        btn_unpay = InlineKeyboardButton(f"❌ لغو ({uid})", callback_data=f"admin_pay_{uid}_no")
        btn_unpaid = InlineKeyboardButton(f"⚠️ پرداخت نشده ({uid})", callback_data=f"admin_pay_{uid}_unpaid")
        markup.row(btn_pay, btn_unpay, btn_unpaid)

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"admin_page_{offset - limit}"))
    if offset + limit < len(rows):
        nav_buttons.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"admin_page_{offset + limit}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    if edit:
        try:
            bot.edit_message_text(text, chat_id=message.chat.id, message_id=message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass
    else:
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

def send_status_excel_report(chat_id, status_filter):
    # اصلاح کوئری برای گزارش‌گیری دقیق وضعیت پرداخت‌شده یا در انتظار پرداخت
    if status_filter == 1:
        rows = list(users_col.find({"submitted": {"$gt": 0}, "paid": 1}).sort("ref_count", -1))
        status_name = "پرداخت‌شده"
        file_name = 'paid_users.csv'
    else:
        # در انتظار پرداخت یعنی فرم داده ولی فیلد paid آن 0 یا تعریف نشده است
        rows = list(users_col.find({"submitted": {"$gt": 0}, "$or": [{"paid": 0}, {"paid": {"$exists": False}}]}).sort("ref_count", -1))
        status_name = "در انتظار پرداخت"
        file_name = 'pending_users.csv'

    if not rows:
        bot.send_message(chat_id, f"⚠️ هیچ کاربری در وضعیت «{status_name}» وجود ندارد.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Wallet,Referrals,Daily Bonus Count,Global Bonus Tokens,Manual Bonus Tokens,Total Tokens,Paid Amount,Status\n"
    for u in rows:
        uid = u.get("user_id")
        ref_cnt = u.get("ref_count", 0)
        wlt = u.get("wallet", "None")
        paid = u.get("paid", 0)
        d_count = u.get("daily_count", 0)
        paid_amt = u.get("paid_amount", 0)
        
        bonus_tokens = u.get("bonus_tokens", 0)
        manual_bonus_tokens = u.get("manual_bonus_tokens", 0)
        total_tokens = calculate_total_tokens(
            ref_cnt, d_count, bonus_tokens, manual_bonus_tokens
        )
        st_text = "Paid" if paid == 1 else "Pending"
        csv_content += f"{uid},{wlt},{ref_cnt},{d_count},{bonus_tokens},{manual_bonus_tokens},{total_tokens},{paid_amt},{st_text}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8-sig'))
    file_bytes.name = file_name
    
    caption_text = f"📁 فایل گزارش کاربران **{status_name}** (فرمت سازگار با اکسل/CSV)"
    bot.send_document(chat_id, file_bytes, caption=caption_text, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def send_detailed_report_file(chat_id):
    rows = list(users_col.find({}).sort([("paid", 1), ("ref_count", -1)]))

    if not rows:
        bot.send_message(chat_id, f"⚠️ هیچ کاربری در دیتابیس ثبت نشده است.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Referred By,Referral Count,Submitted Status,Paid Status,Verified Status,Wallet,Twitter X ID,Instagram ID,Social Registered At,Social Updated At,Last Daily Timestamp,Daily Bonus Count,Global Bonus Tokens,Manual Bonus Tokens,Total Tokens,Paid Amount,Language\n"
    for u in rows:
        uid = u.get("user_id")
        ref_by = u.get("referred_by", "None")
        ref_cnt = u.get("ref_count", 0)
        submitted = u.get("submitted", 0)
        paid = u.get("paid", 0)
        verified = u.get("verified", 0)
        wlt = str(u.get("wallet", "None")).replace(',', '_')
        twitter_id = u.get("twitter_id", "")
        instagram_id = u.get("instagram_id", "")
        social_registered_at = u.get("social_registered_at", 0)
        social_updated_at = u.get("social_updated_at", 0)
        last_daily = u.get("last_daily", 0)
        d_count = u.get("daily_count", 0)
        paid_amt = u.get("paid_amount", 0)
        lang = u.get("lang", "fa")
        
        bonus_tokens = u.get("bonus_tokens", 0)
        manual_bonus_tokens = u.get("manual_bonus_tokens", 0)
        total_tokens = calculate_total_tokens(
            ref_cnt, d_count, bonus_tokens, manual_bonus_tokens
        )
        csv_content += f"{uid},{ref_by},{ref_cnt},{submitted},{paid},{verified},{wlt},{twitter_id},{instagram_id},{social_registered_at},{social_updated_at},{last_daily},{d_count},{bonus_tokens},{manual_bonus_tokens},{total_tokens},{paid_amt},{lang}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8-sig'))
    file_bytes.name = 'all_users_complete_database_report.csv'
    
    bot.send_document(
        chat_id, 
        file_bytes, 
        caption="📁 **گزارش اکسل جامع و کامل تمام اطلاعات کاربران**", 
        reply_markup=get_admin_reply_markup(), 
        parse_mode="Markdown"
    )

def show_stats_direct(chat_id):
    t_u = users_col.count_documents({})
    t_s = users_col.count_documents({"submitted": {"$gt": 0}})
    t_p = users_col.count_documents({"paid": 1})
    total_tokens_all = get_global_total_distributed_tokens()
    bot.send_message(chat_id, f"📊 آمار کلی ربات:\n\n👤 کل کاربران استارت کرده: {t_u}\n📝 تعداد ثبت‌فرم‌ها: {t_s}\n💰 پرداخت‌شده‌ها: {t_p}\n🪙 کل توکن توزیع‌شده: {total_tokens_all:,} PRS", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def show_main_menu(chat_id, user_id, message_id=None, edit=False):
    if BOT_PORTAL_ONLY:
        send_portal_entry(user_id)
        return
    if is_airdrop_finished():
        bot.send_message(chat_id, get_msg(user_id, "airdrop_finished"))
        return

    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    d_count = user_data[5] if user_data and len(user_data) > 5 else 0
    bonus_tokens = user_data[8] if user_data and len(user_data) > 8 else 0
    manual_bonus_tokens = user_data[9] if user_data and len(user_data) > 9 else 0
    total_earned = calculate_total_tokens(ref_count, d_count, bonus_tokens, manual_bonus_tokens)
    paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
    remaining_earned = max(0, total_earned - paid_amt)
    user_rank = get_user_rank(user_id)

    # --- محاسبه وضعیت تایمر برای دکمه پاداش روزانه ---
    daily_btn_text = get_msg(user_id, "btn_daily")
    if user_data:
        last_daily = user_data[4] if len(user_data) > 4 else 0
        current_time = int(time.time())
        if ref_count < REQUIRED_REFERRALS:
            daily_btn_text = f"🔒 {daily_btn_text}" # در صورت نرسیدن به حد نصاب
        elif current_time - last_daily < 86400:
            rem = 86400 - (current_time - last_daily)
            h = rem // 3600
            m = (rem % 3600) // 60
            daily_btn_text = f"⏳ {h:02d}:{m:02d} | {daily_btn_text}" # نمایش تایمر
        else:
            daily_btn_text = f"✅ {daily_btn_text}" # آماده دریافت
    # ----------------------------------------
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(get_msg(user_id, "btn_channel"), url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        InlineKeyboardButton(get_msg(user_id, "btn_twitter"), url=TWITTER_URL)
    )
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_insta"), url=INSTAGRAM_URL))
    
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_ref"), callback_data="get_ref_link"))
    if PORTAL_ENABLED:
        markup.row(InlineKeyboardButton(portal_bridge.text(user_id, "🎯 مأموریت‌های جدید", "🎯 New missions"), callback_data="portal:list"))
    if PORTAL_ENABLED and os.getenv("WEB_BASE_URL", "").strip():
        markup.row(InlineKeyboardButton(portal_bridge.text(user_id, "🌐 پنل ایردراپ", "🌐 Airdrop portal"), callback_data="portal:open"))
    # جایگذاری دکمه جدید با قابلیت تایمر
    markup.row(InlineKeyboardButton(daily_btn_text, callback_data="daily_bonus"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_guide"), callback_data="wallet_guide"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_top"), callback_data="leaderboard"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_status"), callback_data="my_status"), InlineKeyboardButton(get_msg(user_id, "btn_submit_w"), callback_data="submit_info"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_social"), callback_data="social_accounts"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_challenge_quiz"), callback_data="challenge_quiz"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_lang"), callback_data="toggle_language"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_refresh"), callback_data="refresh_menu"))

    caption_text = get_msg(
        user_id,
        "main_caption",
        base=BASE_REWARD,
        req=REQUIRED_REFERRALS,
        daily=DAILY_REWARD,
        extra=EXTRA_REWARD,
        uid=user_id,
        refs=ref_count,
        rank=user_rank,
        bonus=bonus_tokens,
        manual_bonus=manual_bonus_tokens,
        earned=total_earned,
        paid=paid_amt,
        rem=remaining_earned
    )
    
    reply_markup_kb = get_main_reply_markup(user_id)

    if edit and message_id:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            bot.send_message(chat_id, get_msg(user_id, "quick_menu_text"), reply_markup=reply_markup_kb)
            return
        except Exception:
            pass

    try:
        if BANNER_FILE_ID:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
        else:
            raise Exception("No banner")
    except Exception:
        try:
            bot.send_message(chat_id=chat_id, text=caption_text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"Error sending main menu text: {e}")

    try:
        bot.send_message(chat_id=chat_id, text=get_msg(user_id, "quick_menu_text"), reply_markup=reply_markup_kb)
    except Exception as e:
        print(f"Error sending reply markup: {e}")

PAYMENT_UPLOAD_WAIT_SECONDS = 600
PAYMENT_UPLOAD_MAX_ROWS = 5000


def _payment_upload_table(file_bytes, file_name):
    """Return the uploaded table as rows of strings (CSV with , or ; — or .xlsx)."""
    if (file_name or "").lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        sheet = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True).active
        return [["" if cell is None else str(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
    text = file_bytes.decode("utf-8-sig", errors="ignore")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = ";" if first.count(";") > first.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def parse_payment_upload(table):
    """Strict format: a "User ID" column is required, "Total Tokens" is optional.

    Other numbers in the file (amounts, referral counts...) are never read as
    user IDs. Returns (rows, skipped); each row is [user_id, paid_total or None].
    """
    header = None
    uid_index = total_index = None
    rows, skipped, seen = [], 0, set()
    for record in table:
        cells = [str(c).strip().lstrip("\ufeff") for c in record]
        if not any(cells):
            continue
        if header is None:
            lowered = [c.lower() for c in cells]
            if "user id" not in lowered:
                raise ValueError("missing_user_id_column")
            header = lowered
            uid_index = lowered.index("user id")
            total_index = lowered.index("total tokens") if "total tokens" in lowered else None
            continue
        uid_text = cells[uid_index] if uid_index < len(cells) else ""
        if uid_text.endswith(".0"):
            uid_text = uid_text[:-2]
        if not uid_text.isdigit() or int(uid_text) in seen:
            skipped += 1
            continue
        paid_total = None
        if total_index is not None:
            total_text = (cells[total_index] if total_index < len(cells) else "").replace(",", "")
            if total_text.endswith(".0"):
                total_text = total_text[:-2]
            if not total_text.isdigit():
                skipped += 1
                continue
            paid_total = int(total_text)
        seen.add(int(uid_text))
        rows.append([int(uid_text), paid_total])
    if header is None:
        raise ValueError("missing_user_id_column")
    return rows, skipped


def payment_upload_target(user, paid_total):
    """New paid_amount: the file's total (never above what the user earned, never lowering it)."""
    total = calculate_total_tokens(int(user.get("ref_count", 0) or 0), int(user.get("daily_count", 0) or 0),
                                   int(user.get("bonus_tokens", 0) or 0), int(user.get("manual_bonus_tokens", 0) or 0))
    before = max(0, int(user.get("paid_amount", 0) or 0))
    target = total if paid_total is None else min(total, max(before, paid_total))
    return before, target, total


@bot.message_handler(content_types=['document'])
def handle_admin_documents(message):
    if not is_admin(message.from_user.id):
        return
    admin_id = message.from_user.id
    # A document only counts as a payment list right after the upload button.
    # Forwarding a report or any other file to the bot must never mark payments.
    waiting = settings_col.find_one_and_delete({"key": "admin_payment_upload_wait", "admin_id": admin_id})
    if not waiting or int(waiting.get("until", 0)) < int(time.time()):
        bot.send_message(message.chat.id,
            "ℹ️ این فایل به‌عنوان لیست پرداخت پردازش نشد.\nبرای ثبت پرداخت‌ها، اول دکمه «📁 آپلود اکسل پرداختی‌ها» را بزن و بعد فایل را بفرست.",
            reply_markup=get_admin_reply_markup())
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        rows, skipped = parse_payment_upload(_payment_upload_table(downloaded_file, message.document.file_name))
    except ValueError:
        bot.send_message(message.chat.id,
            "❌ ستون «User ID» در فایل پیدا نشد؛ هیچ تغییری ثبت نشد.\nخروجی «🟡 اکسل در انتظار پرداخت» را مبنا قرار بده (CSV یا XLSX).",
            reply_markup=get_admin_reply_markup())
        return
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خواندن فایل ممکن نشد ({type(e).__name__})؛ هیچ تغییری ثبت نشد.",
                         reply_markup=get_admin_reply_markup())
        return
    if not rows:
        bot.send_message(message.chat.id, "⚠️ هیچ ردیف معتبری در فایل نبود؛ هیچ تغییری ثبت نشد.", reply_markup=get_admin_reply_markup())
        return
    if len(rows) > PAYMENT_UPLOAD_MAX_ROWS:
        bot.send_message(message.chat.id, f"⚠️ فایل بیش از {PAYMENT_UPLOAD_MAX_ROWS:,} ردیف دارد؛ آن را چند بخش کن.",
                         reply_markup=get_admin_reply_markup())
        return

    found = {u["user_id"]: u for u in users_col.find(
        {"user_id": {"$in": [uid for uid, _ in rows]}},
        {"user_id": 1, "ref_count": 1, "daily_count": 1, "bonus_tokens": 1, "manual_bonus_tokens": 1, "paid_amount": 1})}
    newly_paid, missing = 0, 0
    for uid, paid_total in rows:
        user = found.get(uid)
        if not user:
            missing += 1
            continue
        before, target, _ = payment_upload_target(user, paid_total)
        newly_paid += max(0, target - before)

    operation_id = uuid4().hex[:16]
    settings_col.delete_many({"key": "admin_payment_upload", "admin_id": admin_id})
    settings_col.insert_one({"key": "admin_payment_upload", "admin_id": admin_id, "operation_id": operation_id,
                             "rows": rows, "created_at": int(time.time())})
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("✅ تأیید و ثبت پرداخت‌ها", callback_data=f"admin_payupload_confirm_{operation_id}"),
               InlineKeyboardButton("❌ انصراف", callback_data=f"admin_payupload_cancel_{operation_id}"))
    amount_note = ("مبلغ هر نفر از ستون «Total Tokens» خوانده شد." if rows[0][1] is not None else
                   "⚠️ ستون «Total Tokens» نبود؛ کل موجودی فعلی هر کاربر پرداخت‌شده ثبت می‌شود.")
    bot.send_message(message.chat.id,
        f"📋 پیش‌نمایش فایل پرداختی:\n\n"
        f"👥 ردیف‌های معتبر: {len(rows):,}\n"
        f"❓ آیدی‌های پیدانشده: {missing:,}\n"
        f"⏭ ردیف‌های ردشده (نامعتبر/تکراری): {skipped:,}\n"
        f"🪙 مجموع PRS که پرداخت‌شده ثبت می‌شود: {newly_paid:,}\n\n"
        f"{amount_note}\nتا تأیید نکنی، هیچ تغییری ثبت نمی‌شود.",
        reply_markup=markup)


def apply_payment_upload(admin_id, rows):
    updated = missing = blocked = 0
    for uid, paid_total in rows:
        if BOT_PORTAL_ONLY:
            try:
                portal_service.admin_bot_payment(admin_id, uid, "yes", paid_total=paid_total)
                updated += 1
            except PortalError as error:
                if error.code == "user_not_found":
                    missing += 1
                else:
                    blocked += 1
            continue
        user = users_col.find_one({"user_id": uid})
        if not user:
            missing += 1
            continue
        _, target, total = payment_upload_target(user, paid_total)
        users_col.update_one({"user_id": uid}, {"$set": {"paid": int(target >= total), "paid_amount": target}})
        updated += 1
    return updated, missing, blocked


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    text = text.translate(persian_to_english)
    
    # An admin explicitly registering must be able to answer the usual captcha.
    if is_admin(user_id) and not captcha_col.find_one({"user_id": user_id}):
        admin_state = settings_col.find_one({"key": "admin_state"})
        if admin_state:
            state_val = admin_state.get("state")
            if state_val == "waiting_broadcast":
                settings_col.delete_one({"key": "admin_state"})
                if text == "❌ انصراف":
                    bot.send_message(chat_id, "❌ ارسال همگانی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                
                bot.send_message(chat_id, "🚀 عملیات ارسال همگانی با مکانیزم ضد اسپم آغاز شد...", reply_markup=get_admin_reply_markup())
                
                def run_broadcast():
                    all_users = list(users_col.find({}, {"user_id": 1}))
                    success_count = 0
                    fail_count = 0
                    for idx, u in enumerate(all_users):
                        try:
                            bot.send_message(u["user_id"], text)
                            update_user_delivery_status(u["user_id"], True)
                            success_count += 1
                        except Exception as e:
                            update_user_delivery_status(u["user_id"], False, e)
                            fail_count += 1
                        
                        if (idx + 1) % 30 == 0:
                            time.sleep(1)
                    
                    bot.send_message(
                        chat_id,
                        f"📊 **گزارش پایان ارسال همگانی:**\n\n"
                        f"✅ ارسال موفق: `{success_count}` کاربر\n"
                        f"❌ ارسال ناموفق (بلاک شده یا غیرفعال): `{fail_count}` کاربر",
                        reply_markup=get_admin_reply_markup(),
                        parse_mode="Markdown"
                    )
                
                threading.Thread(target=run_broadcast, daemon=True).start()
                return

            elif state_val == "waiting_direct_target":
                settings_col.update_one({"key": "admin_state"}, {"$set": {"state": "waiting_direct_text", "target_uid": int(text) if text.isdigit() else 0}}, upsert=True)
                bot.send_message(chat_id, "✍️ حالا متن پیام شخصی خود را برای این کاربر ارسال کنید:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
                return

            elif state_val == "waiting_direct_text":
                target_uid = admin_state.get("target_uid")
                settings_col.delete_one({"key": "admin_state"})
                if text == "❌ انصراف":
                    bot.send_message(chat_id, "❌ ارسال پیام شخصی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                
                try:
                    bot.send_message(target_uid, f"📩 **پیام از طرف مدیریت ربات:**\n\n{text}", parse_mode="Markdown")
                    update_user_delivery_status(target_uid, True)
                    bot.send_message(chat_id, f"✅ پیام شخصی با موفقیت به کاربر `{target_uid}` ارسال شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                except Exception as e:
                    update_user_delivery_status(target_uid, False, e)
                    bot.send_message(chat_id, f"❌ خطا در ارسال پیام به کاربر:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                return

            elif state_val == "waiting_admin_edit_wallet_id":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ عملیات لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                if not text.isdigit():
                    bot.send_message(chat_id, "⚠️ لطفاً یک آیدی عددی معتبر وارد کنید:")
                    return
                target_uid = int(text)
                usr = users_col.find_one({"user_id": target_uid})
                if not usr:
                    bot.send_message(chat_id, "❌ کاربری با این آیدی در دیتابیس یافت نشد. لطفاً آیدی دیگری وارد کنید:")
                    return
                settings_col.update_one({"key": "admin_state"}, {"$set": {"state": "waiting_admin_edit_wallet_val", "target_uid": target_uid}}, upsert=True)
                current_wlt = usr.get("wallet", "ثبت نشده")
                bot.send_message(chat_id, f"👤 کاربر پیدا شد.\n👝 ولت فعلی: `{current_wlt}`\n\nحالا آدرس ولت جدید (یا متن جدید) را برای این کاربر ارسال کنید:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"), parse_mode="Markdown")
                return

            elif state_val == "waiting_admin_edit_wallet_val":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ عملیات لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                target_uid = admin_state.get("target_uid")
                settings_col.delete_one({"key": "admin_state"})
                if PORTAL_ENABLED:
                    try:
                        portal_service.admin_update_wallet(user_id, target_uid, text)
                    except PortalError as error:
                        bot.send_message(chat_id, portal_bridge.error_text(error, user_id), reply_markup=get_admin_reply_markup())
                        return
                else:
                    users_col.update_one({"user_id": target_uid}, {"$set": {"wallet": text, "wallet_lc": text.lower(), "submitted": 1}})
                bot.send_message(chat_id, f"✅ ولت کاربر `{target_uid}` با موفقیت به مقدار جدید تغییر یافت:\n`{text}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                return

            elif state_val == "waiting_manual_bonus_user_id":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ عملیات پاداش دستی لغو شد.", reply_markup=get_admin_reply_markup())
                    return

                if not text.isdigit():
                    bot.send_message(chat_id, "⚠️ لطفاً آیدی عددی معتبر کاربر را وارد کنید:")
                    return

                target_uid = int(text)
                target_user = users_col.find_one({"user_id": target_uid})
                if not target_user:
                    bot.send_message(chat_id, "❌ کاربری با این آیدی در دیتابیس یافت نشد. آیدی دیگری وارد کنید:")
                    return

                settings_col.update_one(
                    {"key": "admin_state"},
                    {"$set": {
                        "state": "waiting_manual_bonus_amount",
                        "admin_id": user_id,
                        "target_uid": target_uid
                    }},
                    upsert=True
                )
                bot.send_message(
                    chat_id,
                    f"👤 *کاربر پیدا شد*\n\n"
                    f"🆔 آیدی: `{target_uid}`\n"
                    f"👥 تعداد دعوت: `{target_user.get('ref_count', 0)}`\n"
                    f"👝 ولت: `{target_user.get('wallet') or 'ثبت نشده'}`\n"
                    f"🎯 پاداش دستی فعلی: `{target_user.get('manual_bonus_tokens', 0):,} PRS`\n\n"
                    f"حالا مقدار پاداش دلخواه را فقط به‌صورت عدد صحیح ارسال کنید:",
                    reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"),
                    parse_mode="Markdown"
                )
                return

            elif state_val == "waiting_manual_bonus_amount":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ عملیات پاداش دستی لغو شد.", reply_markup=get_admin_reply_markup())
                    return

                if not text.isdigit() or int(text) <= 0:
                    bot.send_message(chat_id, "⚠️ مقدار پاداش باید یک عدد صحیح بزرگ‌تر از صفر باشد:")
                    return

                amount = int(text)
                target_uid = admin_state.get("target_uid")
                target_user = users_col.find_one({"user_id": target_uid})
                if not target_user:
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ کاربر موردنظر دیگر در دیتابیس وجود ندارد.", reply_markup=get_admin_reply_markup())
                    return

                remaining_capacity = remaining_reward_capacity()
                if amount > remaining_capacity:
                    bot.send_message(
                        chat_id,
                        f"❌ مبلغ واردشده از ظرفیت باقی‌مانده ایردراپ بیشتر است.\n\n"
                        f"📌 ظرفیت باقی‌مانده: `{remaining_capacity:,} PRS`\n\n"
                        f"مقدار کمتری وارد کنید یا دکمه انصراف را بزنید.",
                        parse_mode="Markdown"
                    )
                    return

                operation_id = uuid4().hex[:12]
                settings_col.update_one(
                    {"key": "admin_state"},
                    {"$set": {
                        "state": "waiting_manual_bonus_confirmation",
                        "admin_id": user_id,
                        "target_uid": target_uid,
                        "operation_id": operation_id,
                        "amount": amount
                    }},
                    upsert=True
                )

                confirm_markup = InlineKeyboardMarkup()
                confirm_markup.row(
                    InlineKeyboardButton("✅ تأیید پاداش دستی", callback_data=f"admin_manual_bonus_confirm_{operation_id}"),
                    InlineKeyboardButton("❌ لغو عملیات", callback_data=f"admin_manual_bonus_cancel_{operation_id}")
                )
                bot.send_message(
                    chat_id,
                    f"⚠️ *تأیید نهایی پاداش دستی*\n\n"
                    f"👤 آیدی کاربر: `{target_uid}`\n"
                    f"👝 ولت: `{target_user.get('wallet') or 'ثبت نشده'}`\n"
                    f"🎁 مبلغ پاداش: `{amount:,} PRS`\n"
                    f"📌 ظرفیت باقی‌مانده پس از ثبت: `{remaining_capacity - amount:,} PRS`\n\n"
                    f"پس از تأیید، پاداش در موجودی حساب کاربر ثبت می‌شود.",
                    reply_markup=confirm_markup,
                    parse_mode="Markdown"
                )
                return

            elif state_val == "waiting_manual_bonus_confirmation":
                bot.send_message(chat_id, "⚠️ لطفاً از دکمه‌های تأیید یا لغو عملیات پاداش دستی استفاده کنید.")
                return

            elif state_val == "waiting_no_wallet_broadcast":
                settings_col.delete_one({"key": "admin_state"})
                if text == "❌ انصراف":
                    bot.send_message(chat_id, "❌ ارسال پیام به واجدین بی‌ولت لغو شد.", reply_markup=get_admin_reply_markup())
                    return

                if not text:
                    bot.send_message(chat_id, "⚠️ متن پیام خالی است؛ عملیات لغو شد.", reply_markup=get_admin_reply_markup())
                    return

                start_no_wallet_broadcast(chat_id, text)
                return

            elif state_val == "waiting_global_bonus_amount":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "❌ عملیات پاداش همگانی لغو شد.", reply_markup=get_admin_reply_markup())
                    return

                if not text.isdigit() or int(text) <= 0:
                    bot.send_message(chat_id, "⚠️ لطفاً مقدار پاداش را فقط به‌صورت یک عدد صحیح بزرگ‌تر از صفر وارد کنید:")
                    return

                amount = int(text)
                eligible_count = users_col.count_documents(get_bonus_eligible_filter())
                total_cost = amount * eligible_count
                current_total = get_global_total_distributed_tokens()
                remaining_capacity = remaining_reward_capacity()

                if eligible_count == 0:
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(chat_id, "⚠️ هیچ کاربری با ولت معتبر و حداقل ۳ دعوت یافت نشد.", reply_markup=get_admin_reply_markup())
                    return

                if total_cost > remaining_capacity:
                    bot.send_message(
                        chat_id,
                        f"❌ این پاداش از ظرفیت باقی‌مانده ایردراپ بیشتر است.\n\n"
                        f"👥 کاربران واجد شرایط: `{eligible_count:,}` نفر\n"
                        f"🪙 مبلغ موردنیاز: `{total_cost:,} PRS`\n"
                        f"📌 ظرفیت باقی‌مانده: `{remaining_capacity:,} PRS`\n\n"
                        f"مقدار کمتری وارد کنید یا دکمه انصراف را بزنید.",
                        parse_mode="Markdown"
                    )
                    return

                operation_id = uuid4().hex[:12]
                settings_col.update_one(
                    {"key": "admin_state"},
                    {"$set": {
                        "state": "waiting_global_bonus_confirmation",
                        "admin_id": user_id,
                        "operation_id": operation_id,
                        "amount": amount
                    }},
                    upsert=True
                )

                confirm_markup = InlineKeyboardMarkup()
                confirm_markup.row(
                    InlineKeyboardButton("✅ تأیید و ثبت پاداش", callback_data=f"admin_bonus_confirm_{operation_id}"),
                    InlineKeyboardButton("❌ لغو عملیات", callback_data=f"admin_bonus_cancel_{operation_id}")
                )
                bot.send_message(
                    chat_id,
                    f"⚠️ *تأیید نهایی پاداش همگانی*\n\n"
                    f"👥 تعداد کاربران واجد شرایط: `{eligible_count:,}` نفر\n"
                    f"🎁 پاداش هر نفر: `{amount:,} PRS`\n"
                    f"🪙 هزینه کل: `{total_cost:,} PRS`\n"
                    f"📌 ظرفیت باقی‌مانده پس از اجرا: `{remaining_capacity - total_cost:,} PRS`\n\n"
                    f"این پاداش فقط به کاربران دارای ولت معتبر و حداقل ۳ دعوت تعلق می‌گیرد.",
                    reply_markup=confirm_markup,
                    parse_mode="Markdown"
                )
                return

            elif state_val == "waiting_global_bonus_confirmation":
                bot.send_message(chat_id, "⚠️ لطفاً برای انجام یا لغو عملیات از دکمه‌های تأیید نهایی استفاده کنید.")
                return

        if text == "📂 گزارش‌های پنل سایت":
            bot.send_message(chat_id, "📂 خروجی‌های پنل سایت را از این بخش بگیر:", reply_markup=get_admin_reports_markup())
            return
        elif text == "👥 کاربران پنل سایت (CSV)":
            send_portal_csv_report(chat_id, "users")
            return
        elif text == "💳 پرداخت‌های پنل سایت (CSV)":
            send_portal_csv_report(chat_id, "payments")
            return
        elif text == "🧾 سوابق مدیریت سایت (CSV)":
            send_portal_csv_report(chat_id, "audit")
            return
        elif text == "✅ پرداخت‌های موفق سایت (Excel)":
            send_portal_xlsx_report(chat_id, "paid")
            return
        elif text == "🌐 آیدی‌های اجتماعی سایت (Excel)":
            send_portal_xlsx_report(chat_id, "social")
            return
        elif text == "↩️ بازگشت به پنل مدیریت":
            bot.send_message(chat_id, "👑 پنل مدیریت:", reply_markup=get_admin_reply_markup())
            return
        elif text == "🔴 خاموش کردن ربات":
            if BOT_PORTAL_ONLY:
                portal_service.admin_controls(user_id, {"paused": True})
            else:
                settings_col.replace_one({"key": "bot_status"}, {"key": "bot_status", "status": "off"}, upsert=True)
            bot.send_message(chat_id, ("⏸ پاداش‌های کمپین موقتاً متوقف شد؛ مدیریت و ورود سایت همچنان فعال است." if BOT_PORTAL_ONLY else "🔴 ربات با موفقیت **خاموش** شد. کاربران عادی دیگر قادر به استفاده از ربات نخواهند بود."), reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "🟢 روشن کردن ربات":
            if BOT_PORTAL_ONLY:
                portal_service.admin_controls(user_id, {"paused": False})
            else:
                settings_col.replace_one({"key": "bot_status"}, {"key": "bot_status", "status": "on"}, upsert=True)
            bot.send_message(chat_id, "🟢 ربات با موفقیت **روشن** شد و به حالت عادی برگشت.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📢 ارسال همگانی پیام":
            settings_col.replace_one({"key": "admin_state"}, {"key": "admin_state", "state": "waiting_broadcast"}, upsert=True)
            bot.send_message(chat_id, "📢 لطفاً متن پیام خود را برای ارسال همگانی به تمام کاربران ارسال کنید:\n*(برای انصراف دکمه زیر را بزنید)*", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
            return
        elif text == "✉️ ارسال پیام شخصی به کاربر":
            settings_col.replace_one({"key": "admin_state"}, {"key": "admin_state", "state": "waiting_direct_target"}, upsert=True)
            bot.send_message(chat_id, "👤 لطفاً آیدی عددی (User ID) کاربر مورد نظر را ارسال کنید:\n*(برای انصراف دکمه زیر را بزنید)*", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
            return
        elif text == "✏️ ویرایش ولت کاربر با آیدی":
            settings_col.replace_one({"key": "admin_state"}, {"key": "admin_state", "state": "waiting_admin_edit_wallet_id"}, upsert=True)
            bot.send_message(chat_id, "🔍 لطفاً آیدی عددی کاربر مورد نظری که می‌خواهید ولتش را تغییر دهید ارسال کنید:\n*(برای انصراف دکمه زیر را بزنید)*", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
            return
        elif text == "🎁 پاداش همگانی واجدین شرایط":
            settings_col.replace_one(
                {"key": "admin_state"},
                {"key": "admin_state", "state": "waiting_global_bonus_amount", "admin_id": user_id},
                upsert=True
            )
            eligible_count = users_col.count_documents(get_bonus_eligible_filter())
            remaining_capacity = remaining_reward_capacity()
            bot.send_message(
                chat_id,
                f"🎁 *ثبت پاداش همگانی PRS*\n\n"
                f"این پاداش به کاربران دارای ولت معتبر و حداقل ۳ دعوت داده می‌شود.\n\n"
                f"👥 تعداد فعلی کاربران واجد شرایط: `{eligible_count:,}` نفر\n"
                f"📌 ظرفیت باقی‌مانده ایردراپ: `{remaining_capacity:,} PRS`\n\n"
                f"مقدار پاداش برای هر نفر را به‌صورت عدد صحیح ارسال کنید:",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"),
                parse_mode="Markdown"
            )
            return
        elif text == "🎯 پاداش دستی به کاربر":
            settings_col.replace_one(
                {"key": "admin_state"},
                {"key": "admin_state", "state": "waiting_manual_bonus_user_id", "admin_id": user_id},
                upsert=True
            )
            bot.send_message(
                chat_id,
                "🎯 لطفاً آیدی عددی کاربری را که می‌خواهید به او پاداش دستی بدهید ارسال کنید:",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف")
            )
            return
        elif text == "📊 اکسل پاداش‌های دستی":
            send_manual_bonus_report(chat_id)
            return
        elif text == "🚫 بررسی و خروجی بلاک‌کنندگان":
            start_blocked_users_scan(chat_id)
            return
        elif text == "📣 پیام به واجدین بی‌ولت":
            recipients_count = len(get_eligible_no_wallet_users())
            if recipients_count == 0:
                bot.send_message(
                    chat_id,
                    "⚠️ هیچ کاربری با حداقل ۳ دعوت و بدون ولت معتبر یافت نشد.",
                    reply_markup=get_admin_reply_markup()
                )
                return
            settings_col.replace_one(
                {"key": "admin_state"},
                {"key": "admin_state", "state": "waiting_no_wallet_broadcast", "admin_id": user_id},
                upsert=True
            )
            bot.send_message(
                chat_id,
                f"📣 پیام بعدی فقط برای کاربران دارای حداقل ۳ دعوت و بدون ولت معتبر ارسال می‌شود.\n\n"
                f"👥 تعداد فعلی مخاطبان: `{recipients_count:,}` نفر\n\n"
                f"حالا متن پیام را ارسال کنید:",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"),
                parse_mode="Markdown"
            )
            return
        elif text == "👝 مدیریت و تایید ولت‌ها":
            send_paginated_wallets(message, offset=0)
            return
        elif text == "📊 گزارش کلی توکن‌ها":
            show_token_summary_direct(chat_id)
            return
        elif text == "🔍 جستجوی کاربر (نام کاربری، آیدی یا ولت)":
            bot.send_message(chat_id, "🔍 برای جستجو، دستور زیر را ارسال کنید:\n`/search [نام کاربری، آیدی عددی یا بخشی از ولت]`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📁 آپلود اکسل پرداختی‌ها":
            settings_col.replace_one(
                {"key": "admin_payment_upload_wait", "admin_id": user_id},
                {"key": "admin_payment_upload_wait", "admin_id": user_id,
                 "until": int(time.time()) + PAYMENT_UPLOAD_WAIT_SECONDS},
                upsert=True)
            bot.send_message(chat_id,
                "📁 فایل CSV پرداختی را در ۱۰ دقیقه آینده همین‌جا بفرست.\n\n"
                "• فایل باید ستون «User ID» داشته باشد (مثل خروجی «🟡 اکسل در انتظار پرداخت»).\n"
                "• فقط ردیف کاربرانی را نگه دار که واقعاً پرداخت کرده‌ای.\n"
                "• اگر ستون «Total Tokens» باشد، فقط همان مبلغ پرداخت‌شده ثبت می‌شود؛ پاداش‌هایی که بعد از تهیه فایل گرفته‌اند پرداخت‌نشده باقی می‌ماند.\n\n"
                "قبل از ثبت، خلاصه را می‌بینی و باید تأیید کنی.",
                reply_markup=get_admin_reply_markup())
            return
        elif text == "🟢 اکسل پرداخت‌شده‌ها":
            send_status_excel_report(chat_id, status_filter=1)
            return
        elif text == "🟡 اکسل در انتظار پرداخت":
            send_status_excel_report(chat_id, status_filter=0)
            return
        elif text == "📥 اکسل واجدین شرایط بی‌ولت":
            send_eligible_no_wallet_excel(chat_id)
            return
        elif text == "📥 اکسل کاربران زیر حد نصاب (<3 دعوت)":
            send_under_threshold_excel(chat_id)
            return
        elif text == "📊 گزارش تفکیکی کامل (فایل)":
            send_detailed_report_file(chat_id)
            return
        elif text == "📥 دریافت فوری بک‌آپ (JSON)":
            send_database_backup(chat_id)
            return
        elif text == "📈 آمار کلی ربات":
            show_stats_direct(chat_id)
            return
        elif text == "🔄 به‌روزرسانی پنل ادمین":
            bot.send_message(chat_id, "🔄 پنل مدیریت با موفقیت به‌روزرسانی و بازنشانی شد.", reply_markup=get_admin_reply_markup())
            return
        elif text == "🔙 خروج از حالت ادمین / منوی اصلی":
            bot.send_message(chat_id, "مجدداً پنل مدیریتی فعال است.", reply_markup=get_admin_reply_markup())
            return
        elif text.startswith("/search "):
            query = text.replace("/search", "").strip()
            search_term = query.lstrip("@")
            query_filter = {"user_id": int(query)} if query.isdigit() else {"$or": [
                {field: {"$regex": re.escape(search_term), "$options": "i"}}
                for field in ("wallet", "telegram_username", "instagram", "instagram_id", "twitter", "twitter_id")
            ]}
            rows = list(users_col.find(query_filter))
            if not rows:
                bot.send_message(chat_id, "❌ هیچ کاربری با این مشخصات پیدا نشد.", reply_markup=get_admin_reply_markup())
                return
            res = "🔍 *نتیجه جستجوی ادمین:*\n\n"
            for r in rows:
                uid = r.get("user_id")
                ref_cnt = r.get("ref_count", 0)
                d_cnt = r.get("daily_count", 0)
                wlt = r.get("wallet", "None")
                submitted = r.get("submitted", 0)
                paid = r.get("paid", 0)
                paid_amt = r.get("paid_amount", 0)
                bonus_tokens = r.get("bonus_tokens", 0)
                manual_bonus_tokens = r.get("manual_bonus_tokens", 0)
                twitter_id = r.get("twitter_id") or "ثبت نشده"
                instagram_id = r.get("instagram_id") or "ثبت نشده"
                telegram_username = r.get("telegram_username") or "ثبت نشده"
                total_tokens = calculate_total_tokens(ref_cnt, d_cnt, bonus_tokens, manual_bonus_tokens)
                base_used, extra_count = get_ref_details(ref_cnt)
                
                paid_status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
                
                res += (
                    f"👤 آیدی عددی: `{uid}`\n"
                    f"🔎 نام کاربری تلگرام: `{telegram_username}`\n"
                    f"👥 کل رفال: {ref_cnt} (ثابت: {base_used} | مازاد: {extra_count})\n"
                    f"🎁 پاداش همگانی: {bonus_tokens:,} | پاداش دستی: {manual_bonus_tokens:,} PRS\n"
                    f"🪙 توکن کل: {total_tokens:,} | پرداخت شده: {paid_amt:,} PRS\n"
                    f"👝 ولت: `{wlt}`\n"
                    f"🐦 Twitter/X: `{twitter_id}`\n"
                    f"📸 Instagram: `{instagram_id}`\n"
                    f"📌 ثبت فرم: `{submitted}` | وضعیت: *{paid_status_str}*\n"
                    f"---\n"
                )
            bot.send_message(chat_id, res, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text.startswith("/deleteuser "):
            target_id = text.replace("/deleteuser", "").strip()
            if target_id.isdigit():
                users_col.delete_one({"user_id": int(target_id)})
                captcha_col.delete_one({"user_id": int(target_id)})
                bot.send_message(chat_id, f"✅ کاربر با آیدی عددی `{target_id}` به طور کامل حذف شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "⚠️ آیدی عددی وارد شده معتبر نیست.", reply_markup=get_admin_reply_markup())
            return
        
        bot.send_message(chat_id, "👑 دستور یا دکمه نامعتبر. از منوی زیر استفاده کنید:", reply_markup=get_admin_reply_markup())
        return

    if is_bot_globally_disabled():
        bot.send_message(chat_id, get_msg(user_id, "global_off"))
        return

    captcha_data = captcha_col.find_one({"user_id": user_id})
    if captcha_data:
        n1 = captcha_data["num1"]
        n2 = captcha_data["num2"]
        correct_ans = captcha_data["answer"]
        referrer_id = captcha_data["pending_referrer"]

        remaining = captcha_lock_remaining(captcha_data)
        if remaining:
            send_captcha_locked(chat_id, user_id, remaining)
            return

        if text.isdigit() and int(text) == correct_ans:
            captcha_col.update_one({"user_id": user_id}, {"$set": {"solved_at": int(time.time())}})
            
            if not check_membership(user_id):
                ask_to_join(chat_id, referrer_id if referrer_id else 0, user_id)
                return

            register_user_after_verify(user_id, referrer_id)
            if getattr(message.from_user, "username", None):
                users_col.update_one({"user_id": user_id}, {"$set": {"telegram_username": f"@{message.from_user.username}"}})
            captcha_col.delete_one({"user_id": user_id})
            show_main_menu(chat_id, user_id)
        else:
            locked = register_captcha_failure(user_id)
            if locked:
                send_captcha_locked(chat_id, user_id, locked)
                return
            new_n1 = random.randint(11, 49)
            new_n2 = random.randint(2, 9)
            new_correct_ans = new_n1 + new_n2

            captcha_col.update_one(
                {"user_id": user_id},
                {"$set": {"num1": new_n1, "num2": new_n2, "answer": new_correct_ans, "solved_at": 0}}
            )

            wrong_text = get_msg(user_id, "captcha_wrong", new_n1, new_n2)
            bot.send_message(chat_id, wrong_text)
        return

    if is_airdrop_finished():
        bot.send_message(user_id, get_msg(user_id, "airdrop_finished"))
        return

    if not check_membership(user_id):
        ask_to_join(chat_id, 0, user_id)
        return

    if handle_social_registration_input(message, text):
        return

    if text in [LANG["fa"]["main_kb_status"], LANG["en"]["main_kb_status"]]:
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        bonus_tokens = user_data[8] if user_data and len(user_data) > 8 else 0
        manual_bonus_tokens = user_data[9] if user_data and len(user_data) > 9 else 0
        total_earned = calculate_total_tokens(ref_count, d_count, bonus_tokens, manual_bonus_tokens)
        paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
        remaining_earned = max(0, total_earned - paid_amt)
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else ("ثبت نشده" if get_msg(user_id, "lang")=="fa" else "Not registered")
        social_not_registered = get_msg(user_id, "social_not_registered")
        twitter_id = user_data[10] if user_data and len(user_data) > 10 and user_data[10] else social_not_registered
        instagram_id = user_data[11] if user_data and len(user_data) > 11 and user_data[11] else social_not_registered
        user_rank = get_user_rank(user_id)
        
        status_msg = get_msg(
            user_id, "status_box", uid=user_id, refs=ref_count, req=REQUIRED_REFERRALS,
            bonus=bonus_tokens, manual_bonus=manual_bonus_tokens, earned=total_earned,
            paid=paid_amt, rem=remaining_earned, rank=user_rank, wallet=wallet,
            twitter=twitter_id, instagram=instagram_id
        )
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
        return
    elif text in [LANG["fa"]["main_kb_ref"], LANG["en"]["main_kb_ref"]]:
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        link_text = get_msg(user_id, "ref_text", link=ref_link)
        try:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=link_text)
        except Exception:
            bot.send_message(chat_id=chat_id, text=link_text)
        return
    elif text in [LANG["fa"]["main_kb_daily"], LANG["en"]["main_kb_daily"]]:
        try:
            claim_bot_daily(user_id)
            bot.send_message(chat_id, get_msg(user_id, "daily_success", DAILY_REWARD))
        except PortalError as error:
            bot.send_message(chat_id, portal_bridge.error_text(error, user_id))
        return
    elif text in [LANG["fa"]["main_kb_guide"], LANG["en"]["main_kb_guide"]]:
        guide_text = get_msg(user_id, "wallet_guide_text")
        bot.send_message(chat_id, guide_text, parse_mode="Markdown")
        return
    elif text in [LANG["fa"]["main_kb_leaderboard"], LANG["en"]["main_kb_leaderboard"]]:
        all_users = list(users_col.find({}))
        ranked_list = []
        for u in all_users:
            uid = u.get("user_id")
            r_cnt = u.get("ref_count", 0)
            d_cnt = u.get("daily_count", 0)
            total_t = calculate_total_tokens(
                r_cnt, d_cnt, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
            )
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: (x[2], x[1]), reverse=True)
        top_10 = ranked_list[:10]
        
        text_lb = get_msg(user_id, "top_title")
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text_lb += get_msg(user_id, "top_row", idx, uid=uid, total=total_t, refs=r_cnt)
        bot.send_message(chat_id, text_lb, parse_mode="Markdown", reply_markup=get_main_reply_markup(user_id))
        return
    elif text in [LANG["fa"]["main_kb_social"], LANG["en"]["main_kb_social"]]:
        start_social_registration(chat_id, user_id)
        return
    elif text in [LANG["fa"]["main_kb_challenge_quiz"], LANG["en"]["main_kb_challenge_quiz"]]:
        send_challenge_intro(chat_id, user_id)
        return
    elif text in [LANG["fa"]["main_kb_refresh"], LANG["en"]["main_kb_refresh"]]:
        show_main_menu(chat_id, user_id)
        return
    elif text in [LANG["fa"]["main_kb_wallet"], LANG["en"]["main_kb_wallet"]]:
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        submitted = user_data[1] if user_data else 0
        
        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(get_msg(user_id, "submit_err_ref", ref_count, REQUIRED_REFERRALS))
        if submitted >= 2:
            errors.append(get_msg(user_id, "submit_err_limit"))
            
        if errors:
            bot.send_message(chat_id, get_msg(user_id, "submit_errors", "\n".join(errors)), parse_mode="Markdown")
            return
        
        if submitted == 1:
            bot.send_message(chat_id, get_msg(user_id, "submit_edit_mode"))
        else:
            bot.send_message(chat_id, get_msg(user_id, "submit_new_mode"))
        return
    elif text in [LANG["fa"]["main_kb_channel"], LANG["en"]["main_kb_channel"]]:
        bot.send_message(chat_id, f"📢 Channel: {CHANNEL_ID}")
        return
    elif text in [LANG["fa"]["main_kb_twitter"], LANG["en"]["main_kb_twitter"]]:
        bot.send_message(chat_id, f"🐦 Twitter: {TWITTER_URL}")
        return
    elif text in [LANG["fa"]["main_kb_instagram"], LANG["en"]["main_kb_instagram"]]:
        bot.send_message(chat_id, f"📸 Instagram: {INSTAGRAM_URL}")
        return

    wallet_address = text.strip()
    if re.match(r"^0x[a-fA-F0-9]{40}$", wallet_address):
        user_doc = users_col.find_one({"user_id": user_id})
        ref_count = user_doc.get("ref_count", 0) if user_doc else 0
        submitted_status = user_doc.get("submitted", 0) if user_doc else 0

        # کنترل نهایی در لحظه ذخیره تا ارسال مستقیم آدرس نتواند شرط دعوت را دور بزند
        if ref_count < REQUIRED_REFERRALS:
            bot.send_message(
                chat_id,
                get_msg(
                    user_id,
                    "submit_errors",
                    get_msg(user_id, "submit_err_ref", ref_count, REQUIRED_REFERRALS)
                ),
                parse_mode="Markdown"
            )
            return

        if submitted_status >= 2:
            bot.send_message(chat_id, get_msg(user_id, "wallet_limit_err"))
            return

        if PORTAL_ENABLED:
            try:
                portal_service.update_wallet(user_id, wallet_address)
            except PortalError as error:
                bot.send_message(chat_id, portal_bridge.error_text(error, user_id))
                return
        else:
            if wallet_used_by_other(user_id, wallet_address):
                bot.send_message(chat_id, portal_bridge.error_text(PortalError("wallet_in_use", 409), user_id))
                return
            save_submission(user_id, wallet_address, submitted_status)

        if submitted_status == 0:
            bot.send_message(chat_id, get_msg(user_id, "wallet_saved"))
        else:
            bot.send_message(chat_id, get_msg(user_id, "wallet_updated"))
        
        show_main_menu(chat_id, user_id)
        return

    bot.send_message(
        chat_id,
        "⚠️ لطفاً از پنل کاربری اقدام کنید / Please use the user panel.",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if is_admin(user_id):
        if call.data.startswith("admin_manual_bonus_confirm_"):
            operation_id = call.data.replace("admin_manual_bonus_confirm_", "", 1)
            pending = settings_col.find_one_and_delete({
                "key": "admin_state",
                "state": "waiting_manual_bonus_confirmation",
                "admin_id": user_id,
                "operation_id": operation_id
            })
            if not pending:
                bot.answer_callback_query(call.id, "⚠️ این عملیات قبلاً انجام یا لغو شده است.", show_alert=True)
                return

            amount = pending.get("amount", 0)
            target_uid = pending.get("target_uid")
            if not isinstance(amount, int) or amount <= 0 or not isinstance(target_uid, int):
                bot.answer_callback_query(call.id, "❌ اطلاعات پاداش دستی نامعتبر است.", show_alert=True)
                return

            bot.answer_callback_query(call.id, "✅ ثبت پاداش دستی آغاز شد.", show_alert=True)
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            execute_manual_bonus(chat_id, target_uid, operation_id, amount)
            return

        if call.data.startswith("admin_manual_bonus_cancel_"):
            operation_id = call.data.replace("admin_manual_bonus_cancel_", "", 1)
            pending = settings_col.find_one_and_delete({
                "key": "admin_state",
                "state": "waiting_manual_bonus_confirmation",
                "admin_id": user_id,
                "operation_id": operation_id
            })
            if pending:
                bot.answer_callback_query(call.id, "❌ عملیات پاداش دستی لغو شد.", show_alert=True)
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except Exception:
                    pass
                bot.send_message(chat_id, "❌ عملیات پاداش دستی لغو شد.", reply_markup=get_admin_reply_markup())
            else:
                bot.answer_callback_query(call.id, "⚠️ این عملیات قبلاً انجام یا لغو شده است.", show_alert=True)
            return

        if call.data.startswith("admin_bonus_confirm_"):
            operation_id = call.data.replace("admin_bonus_confirm_", "", 1)
            pending = settings_col.find_one_and_delete({
                "key": "admin_state",
                "state": "waiting_global_bonus_confirmation",
                "admin_id": user_id,
                "operation_id": operation_id
            })
            if not pending:
                bot.answer_callback_query(call.id, "⚠️ این عملیات قبلاً انجام یا لغو شده است.", show_alert=True)
                return

            amount = pending.get("amount", 0)
            if not isinstance(amount, int) or amount <= 0:
                bot.answer_callback_query(call.id, "❌ مقدار پاداش نامعتبر است.", show_alert=True)
                return

            bot.answer_callback_query(call.id, "✅ عملیات پاداش آغاز شد.", show_alert=True)
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            execute_global_bonus(chat_id, operation_id, amount)
            return

        if call.data.startswith("admin_bonus_cancel_"):
            operation_id = call.data.replace("admin_bonus_cancel_", "", 1)
            pending = settings_col.find_one_and_delete({
                "key": "admin_state",
                "state": "waiting_global_bonus_confirmation",
                "admin_id": user_id,
                "operation_id": operation_id
            })
            if pending:
                bot.answer_callback_query(call.id, "❌ عملیات پاداش لغو شد.", show_alert=True)
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except Exception:
                    pass
                bot.send_message(chat_id, "❌ عملیات پاداش همگانی لغو شد.", reply_markup=get_admin_reply_markup())
            else:
                bot.answer_callback_query(call.id, "⚠️ این عملیات قبلاً انجام یا لغو شده است.", show_alert=True)
            return

        if call.data.startswith("admin_payupload_"):
            confirm = call.data.startswith("admin_payupload_confirm_")
            operation_id = call.data.rsplit("_", 1)[-1]
            pending = settings_col.find_one_and_delete({"key": "admin_payment_upload", "admin_id": user_id,
                                                        "operation_id": operation_id})
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            if not pending:
                bot.answer_callback_query(call.id, "⚠️ این فایل قبلاً ثبت یا لغو شده است.", show_alert=True)
                return
            if not confirm:
                bot.answer_callback_query(call.id, "❌ ثبت فایل پرداختی لغو شد.")
                bot.send_message(chat_id, "❌ هیچ تغییری ثبت نشد.", reply_markup=get_admin_reply_markup())
                return
            bot.answer_callback_query(call.id, "⏳ در حال ثبت پرداخت‌ها...")
            updated, missing, blocked = apply_payment_upload(user_id, pending.get("rows") or [])
            bot.send_message(chat_id,
                f"✅ فایل پرداختی ثبت شد.\n\n🟢 پرداخت‌شده ثبت شد: {updated:,} نفر\n❓ پیدانشده: {missing:,}"
                + (f"\n⚠️ ثبت‌نشده (درخواست پرداخت باز در سایت دارند): {blocked:,} — آن‌ها را از سایت بررسی کن." if blocked else ""),
                reply_markup=get_admin_reply_markup())
            return

        if call.data.startswith("admin_pay_"):
            parts = call.data.split("_")
            target_uid = int(parts[2])
            action = parts[3]
            
            usr = users_col.find_one({"user_id": target_uid})
            if usr:
                r_cnt = usr.get("ref_count", 0)
                d_cnt = usr.get("daily_count", 0)
                tot_tokens = calculate_total_tokens(
                    r_cnt, d_cnt, usr.get("bonus_tokens", 0), usr.get("manual_bonus_tokens", 0)
                )
                
                if BOT_PORTAL_ONLY:
                    try:
                        portal_service.admin_bot_payment(user_id, target_uid, action)
                    except PortalError as error:
                        text = "این کاربر درخواست پرداخت باز در سایت دارد؛ ابتدا همان درخواست را بررسی کنید." if error.code == "payment_pending" else portal_bridge.error_text(error, user_id)
                        text = text[:190]  # Telegram alert text limit
                        bot.answer_callback_query(call.id, text, show_alert=True)
                        return
                elif action == "yes":
                    users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 1, "paid_amount": tot_tokens}})
                elif action == "no":
                    users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 0}})
                elif action == "unpaid":
                    if db.portal_payments.find_one({"user_id": target_uid, "status": "recorded"}, {"_id": 1}):
                        bot.answer_callback_query(call.id, portal_bridge.error_text(
                            PortalError("onchain_payment_recorded", 409), user_id), show_alert=True)
                        return
                    users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 0, "paid_amount": 0}})
            
            bot.answer_callback_query(call.id, f"✅ وضعیت کاربر {target_uid} به‌روز شد.")
            
            try:
                send_paginated_wallets(call.message, offset=0, edit=True)
            except Exception:
                pass
            return

        if call.data.startswith("admin_page_"):
            offset = int(call.data.split("_")[2])
            bot.answer_callback_query(call.id)
            send_paginated_wallets(call.message, offset=offset, edit=True)
            return

    if is_bot_globally_disabled() and not is_admin(user_id):
        bot.answer_callback_query(call.id, get_msg(user_id, "global_off"), show_alert=True)
        return

    if is_airdrop_finished() and not is_admin(user_id):
        bot.answer_callback_query(call.id, get_msg(user_id, "airdrop_finished"), show_alert=True)
        return

    if call.data == "challenge_quiz":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_challenge_intro(chat_id, user_id)
        return

    if call.data == "challenge_begin":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        start_challenge_quiz(chat_id, user_id)
        return

    if call.data.startswith("challenge_answer_"):
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            return
        handle_challenge_answer(call)
        return

    if call.data.startswith("setlang_"):
        parts = call.data.split("_")
        chosen_lang = parts[1]
        referrer_id = int(parts[2])
        user = users_col.find_one({"user_id": user_id}) or {}
        if int(user.get("verified", 0)) < 1 and user.get("registration_referrer"):
            referrer_id = user["registration_referrer"]
        
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"lang": chosen_lang}},
            upsert=True
        )
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
            
        send_captcha(chat_id, user_id, referrer_id)
        return

    if call.data == "toggle_language":
        user = users_col.find_one({"user_id": user_id})
        current_lang = user.get("lang", "fa") if user else "fa"
        new_lang = "en" if current_lang == "fa" else "fa"
        
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"lang": new_lang}},
            upsert=True
        )
        
        success_msg = "✅ زبان ربات با موفقیت به فارسی تغییر یافت." if new_lang == "fa" else "✅ Bot language successfully changed to English."
        bot.answer_callback_query(call.id, success_msg, show_alert=True)
        show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
        return

    if call.data.startswith("check_join_"):
        referrer_id = int(call.data.split("_")[2])
        user = users_col.find_one({"user_id": user_id}) or {}
        captcha_data = captcha_col.find_one({"user_id": user_id})
        if int(user.get("verified", 0)) < 1:
            solved_at = (captcha_data or {}).get("solved_at", 0)
            if not solved_at or int(time.time()) - solved_at > 900:
                bot.answer_callback_query(call.id, "ابتدا سؤال امنیتی را درست پاسخ بده. / Answer the security question first.", show_alert=True)
                send_captcha(chat_id, user_id, (captcha_data or {}).get("pending_referrer", referrer_id))
                return
            # Referral attribution comes from the solved challenge, not the button payload.
            referrer_id = captcha_data.get("pending_referrer", 0)
        
        if not check_membership(user_id):
            no_join_msg = "❌ شما هنوز در کانال عضو نشده‌اید!" if get_msg(user_id, "lang")=="fa" else "❌ You have not joined the channel yet!"
            bot.answer_callback_query(call.id, no_join_msg, show_alert=True)
            return

        ok_join_msg = "✅ عضویت شما تایید شد!" if get_msg(user_id, "lang")=="fa" else "✅ Membership verified!"
        bot.answer_callback_query(call.id, ok_join_msg)
        register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
        if getattr(call.from_user, "username", None):
            users_col.update_one({"user_id": user_id}, {"$set": {"telegram_username": f"@{call.from_user.username}"}})
        captcha_col.delete_one({"user_id": user_id})
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        
        show_main_menu(chat_id, user_id)
        return

    if call.data == "refresh_menu":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            ask_to_join(chat_id, 0, user_id)
            return
        bot.answer_callback_query(call.id, "🔄 پنل به‌روز شد.")
        show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
        return

    if call.data == "get_ref_link":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        link_text = get_msg(user_id, "ref_text", link=ref_link)
        try:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=link_text)
        except Exception:
            bot.send_message(chat_id=chat_id, text=link_text)
    elif call.data == "daily_bonus":
        try:
            claim_bot_daily(user_id)
            bot.answer_callback_query(call.id, portal_bridge.text(user_id, "🎁 پاداش روزانه ثبت شد.", "🎁 Daily reward recorded."), show_alert=True)
            show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
        except PortalError as error:
            bot.answer_callback_query(call.id, portal_bridge.error_text(error, user_id), show_alert=True)
    elif call.data == "wallet_guide":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        guide_text = get_msg(user_id, "wallet_guide_text")
        bot.send_message(chat_id, guide_text, parse_mode="Markdown")
    elif call.data == "leaderboard":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        all_users = list(users_col.find({}))
        ranked_list = []
        for u in all_users:
            uid = u.get("user_id")
            r_cnt = u.get("ref_count", 0)
            d_cnt = u.get("daily_count", 0)
            total_t = calculate_total_tokens(
                r_cnt, d_cnt, u.get("bonus_tokens", 0), u.get("manual_bonus_tokens", 0)
            )
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: (x[2], x[1]), reverse=True)
        top_10 = ranked_list[:10]
        
        text_lb = get_msg(user_id, "top_title")
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text_lb += get_msg(user_id, "top_row", idx, uid=uid, total=total_t, refs=r_cnt)
        bot.send_message(chat_id, text_lb, parse_mode="Markdown")
    elif call.data == "social_accounts":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        start_social_registration(chat_id, user_id)
    elif call.data == "my_status":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        bonus_tokens = user_data[8] if user_data and len(user_data) > 8 else 0
        manual_bonus_tokens = user_data[9] if user_data and len(user_data) > 9 else 0
        total_earned = calculate_total_tokens(ref_count, d_count, bonus_tokens, manual_bonus_tokens)
        paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
        remaining_earned = max(0, total_earned - paid_amt)
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else ("ثبت نشده" if get_msg(user_id, "lang")=="fa" else "Not registered")
        social_not_registered = get_msg(user_id, "social_not_registered")
        twitter_id = user_data[10] if user_data and len(user_data) > 10 and user_data[10] else social_not_registered
        instagram_id = user_data[11] if user_data and len(user_data) > 11 and user_data[11] else social_not_registered
        user_rank = get_user_rank(user_id)
        
        status_msg = get_msg(
            user_id, "status_box", uid=user_id, refs=ref_count, req=REQUIRED_REFERRALS,
            bonus=bonus_tokens, manual_bonus=manual_bonus_tokens, earned=total_earned,
            paid=paid_amt, rem=remaining_earned, rank=user_rank, wallet=wallet,
            twitter=twitter_id, instagram=instagram_id
        )
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
    elif call.data == "submit_info":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        submitted = user_data[1] if user_data else 0

        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(get_msg(user_id, "submit_err_ref", ref_count, REQUIRED_REFERRALS))
        if submitted >= 2:
            errors.append(get_msg(user_id, "submit_err_limit"))

        if errors:
            bot.answer_callback_query(call.id, "⚠️ شرایط لازم را ندارید!", show_alert=True)
            bot.send_message(
                chat_id,
                get_msg(user_id, "submit_errors", "\n".join(errors)),
                parse_mode="Markdown"
            )
            return

        bot.answer_callback_query(call.id)
        if submitted == 1:
            bot.send_message(chat_id, get_msg(user_id, "submit_edit_mode"))
        else:
            bot.send_message(chat_id, get_msg(user_id, "submit_new_mode"))

def bot_failure_label(error):
    """Never log exception strings: Telegram request URLs contain the token."""
    code = getattr(error, "error_code", None)
    return f"Telegram API {code}" if type(code) is int else type(error).__name__


def prepare_bot_polling():
    print("BOT CHECK: validating Telegram connection", flush=True)
    try:
        identity = bot.get_me()
    except Exception as error:
        label = bot_failure_label(error)
        print(f"BOT STARTUP FAILED: {label} during getMe", flush=True)
        raise RuntimeError(f"Bot connection failed: {label}") from None
    username = str(getattr(identity, "username", "") or "")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise RuntimeError("Telegram returned an invalid bot username")
    print(f"BOT CONNECTED: @{username}", flush=True)
    if username.casefold() != BOT_USERNAME.strip().lstrip("@").casefold():
        print(f"BOT CONFIG WARNING: set BOT_USERNAME to {username} in both services", flush=True)
    print("BOT CHECK: clearing webhook before polling", flush=True)
    try:
        bot.delete_webhook(drop_pending_updates=not BOT_PORTAL_ONLY)
    except Exception as error:
        label = bot_failure_label(error)
        print(f"BOT STARTUP FAILED: {label} during deleteWebhook", flush=True)
        raise RuntimeError(f"Bot webhook setup failed: {label}") from None
    print("BOT WEBHOOK: cleared", flush=True)


def setup_panel_menu_button():
    """The button next to the message box opens the user panel; Telegram signs who opened it."""
    if not (PORTAL_ENABLED and os.getenv("WEB_BASE_URL", "").strip()):
        return
    try:
        bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="پنل", web_app=WebAppInfo(portal_service.webapp_url())))
        print("BOT MENU BUTTON: opens the user panel", flush=True)
    except Exception as error:
        print(f"BOT MENU BUTTON not set: {bot_failure_label(error)}", flush=True)


def poll_bot_updates():
    # Telegram retains a previous allowed_updates filter when it is omitted.
    # Request both update types used by this bot explicitly on every poll.
    print("BOT POLLING: message, callback_query and chat_member enabled", flush=True)
    return bot.infinity_polling(timeout=30, long_polling_timeout=30,
                                skip_pending=not BOT_PORTAL_ONLY,
                                allowed_updates=["message", "callback_query", "chat_member"])


if __name__ == "__main__":
    if PORTAL_ENABLED:
        if not portal_service.store.ready():
            raise RuntimeError("Portal requires MongoDB transaction support; keep PORTAL_ENABLED=0 until ready")
        if not portal_service.store.ensure_indexes():
            print("PORTAL WARNING: users.user_id unique index missing; run scripts/prepare_portal.py", flush=True)
        try:
            portal_service.store.backfill_wallet_keys()
        except Exception as error:
            print(f"PORTAL WARNING: wallet key backfill failed ({type(error).__name__})", flush=True)
    else:
        try:
            users_col.create_index("wallet_lc")
            users_col.update_many({"wallet": {"$type": "string"}, "wallet_lc": {"$exists": False}},
                                  [{"$set": {"wallet_lc": {"$toLower": "$wallet"}}}])
        except Exception as error:
            print(f"WALLET INDEX WARNING: {type(error).__name__}", flush=True)
    print("PHASE 2: user website gateway and dual admin management starting..." if BOT_PORTAL_ONLY else "Bot is starting with MongoDB & Dual-Language Support...", flush=True)
    prepare_bot_polling()
    setup_panel_menu_button()
    time.sleep(2)

    backup_thread = threading.Thread(target=auto_backup_scheduler, daemon=True)
    backup_thread.start()
    if PORTAL_ENABLED:
        payment_notice_thread = threading.Thread(target=portal_payment_notification_scheduler, daemon=True)
        payment_notice_thread.start()
        threading.Thread(target=portal_maintenance_scheduler, daemon=True, name="prs-maintenance").start()
        threading.Thread(target=portal_message_scheduler, daemon=True, name="prs-messages").start()
        threading.Thread(target=referral_membership_scheduler, daemon=True, name="prs-referrals").start()

    while True:
        try:
            poll_bot_updates()
        except Exception as e:
            print(f"BOT POLLING FAILED: {bot_failure_label(e)}", flush=True)
            time.sleep(10)

