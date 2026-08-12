import io
import os
import random
import time
import json
import threading
import re
from datetime import datetime
from telebot import TeleBot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL environment variable is not set")

# اتصال به MongoDB با تعیین صریح نام دیتابیس
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["persepolis_db"]
users_col = db.users
captcha_col = db.captcha
settings_col = db.bot_settings

BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
TWITTER_URL = "https://x.com/PersepolisPRS"
INSTAGRAM_URL = "https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"

ADMIN_IDS = [6661478622, 84460885]
ADMIN_CHAT_ID = 6661478622

REQUIRED_REFERRALS = 3

BASE_REWARD = 1000
EXTRA_REWARD = 1000
DAILY_REWARD = 100
MAX_TOTAL_TOKENS_LIMIT = 300_000_000

BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = TeleBot(TOKEN, threaded=True)

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
        "btn_channel": "📢 کانال تلگرام",
        "btn_twitter": "🐦 توییتر (ایکس)",
        "btn_insta": "📸 اینستاگرام پرسپولیس",
        "btn_ref": "🔗 دریافت لینک دعوت جذاب و اختصاصی",
        "btn_daily": "🎁 پاداش روزانه (100 PRS)",
        "btn_guide": "📖 راهنمای ولت و توکن PRS",
        "btn_top": "🏆 برترین شرکت‌کنندگان (تاپ ۱۰)",
        "btn_status": "📊 وضعیت من و رتبه",
        "btn_submit_w": "📝 ارسال / ویرایش ولت",
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
        "status_box": (
            "📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            "🆔 آیدی عددی شما: `{uid}`\n"
            "👥 تعداد دعوت‌ها: `{refs} / {req}`\n"
            "🎁 کل توکن کسب‌شده: `{earned:,} PRS`\n"
            "💳 توکن پرداخت شده: `{paid:,} PRS`\n"
            "💰 موجودی باقی‌مانده: `{rem:,} PRS`\n"
            "🏅 رتبه شما در ایردراپ: `{rank}`\n"
            "👝 آدرس ولت فعلی: `{wallet}`"
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
        "btn_channel": "📢 Telegram Channel",
        "btn_twitter": "🐦 Twitter (X)",
        "btn_insta": "📸 Persepolis Instagram",
        "btn_ref": "🔗 Get Exclusive Referral Link",
        "btn_daily": "🎁 Daily Bonus (100 PRS)",
        "btn_guide": "📖 PRS Wallet & Token Guide",
        "btn_top": "🏆 Top Participants (Top 10)",
        "btn_status": "📊 My Status & Rank",
        "btn_submit_w": "📝 Submit / Edit Wallet",
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
        "status_box": (
            "📊 *Your Account Information & Status:*\n\n"
            "🆔 Your User ID: `{uid}`\n"
            "👥 Referrals: `{refs} / {req}`\n"
            "🎁 Total Earned Tokens: `{earned:,} PRS`\n"
            "💳 Paid Tokens: `{paid:,} PRS`\n"
            "💰 Remaining Balance: `{rem:,} PRS`\n"
            "🏅 Your Rank: `{rank}`\n"
            "👝 Current Wallet Address: `{wallet}`"
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
    lang = "fa"
    user = users_col.find_one({"user_id": user_id})
    if user and user.get("lang"):
        lang = user.get("lang")
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(get_msg(lang, "main_kb_status"), get_msg(lang, "main_kb_ref"))
    markup.row(get_msg(lang, "main_kb_daily"), get_msg(lang, "main_kb_wallet"))
    markup.row(get_msg(lang, "main_kb_guide"), get_msg(lang, "main_kb_leaderboard"))
    markup.row(get_msg(lang, "main_kb_refresh"), get_msg(lang, "main_kb_channel"))
    markup.row(get_msg(lang, "main_kb_twitter"), get_msg(lang, "main_kb_instagram"))
    return markup

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_bot_globally_disabled():
    setting = settings_col.find_one({"key": "bot_status"})
    if setting and setting.get("status") == "off":
        return True
    return False

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
        user.get("paid_amount", 0)
    )

def calculate_tokens(ref_count):
    if ref_count < REQUIRED_REFERRALS:
        return 0
    extra = ref_count - REQUIRED_REFERRALS
    return BASE_REWARD + (extra * EXTRA_REWARD)

def calculate_total_tokens(ref_count, daily_count):
    base_ref_tokens = calculate_tokens(ref_count)
    daily_tokens = daily_count * DAILY_REWARD
    return base_ref_tokens + daily_tokens

def get_global_total_distributed_tokens():
    all_users = users_col.find({}, {"ref_count": 1, "daily_count": 1})
    total = 0
    for u in all_users:
        r_cnt = u.get("ref_count", 0)
        d_cnt = u.get("daily_count", 0)
        total += calculate_total_tokens(r_cnt, d_cnt)
    return total

def is_airdrop_finished():
    return get_global_total_distributed_tokens() >= MAX_TOTAL_TOKENS_LIMIT

def check_membership(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        print(f"Error checking membership: {e}")
    return False

def get_admin_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👝 مدیریت و تایید ولت‌ها", "📊 گزارش کلی توکن‌ها")
    markup.row("🔍 جستجوی کاربر (آیدی یا ولت)", "✏️ ویرایش ولت کاربر با آیدی")
    markup.row("📁 آپلود اکسل پرداختی‌ها", "🟢 اکسل پرداخت‌شده‌ها")
    markup.row("🟡 اکسل در انتظار پرداخت", "📥 اکسل واجدین شرایط بی‌ولت")
    markup.row("📥 اکسل کاربران زیر حد نصاب (<3 دعوت)", "📊 گزارش تفکیکی کامل (فایل)")
    markup.row("📥 دریافت فوری بک‌آپ (JSON)", "📈 آمار کلی ربات")
    markup.row("🔄 به‌روزرسانی پنل ادمین", "📢 ارسال همگانی پیام")
    markup.row("✉️ ارسال پیام شخصی به کاربر", "🔴 خاموش کردن ربات")
    markup.row("🟢 روشن کردن ربات", "🔙 خروج از حالت ادمین / منوی اصلی")
    return markup

def register_user_after_verify(user_id, referrer_id):
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
            "lang": "fa"
        })
        
        if valid_referrer:
            users_col.update_one({"user_id": valid_referrer}, {"$inc": {"ref_count": 1}})
            try:
                ref_user = users_col.find_one({"user_id": valid_referrer})
                current_refs = ref_user.get("ref_count", 1) if ref_user else 1
                d_count = ref_user.get("daily_count", 0) if ref_user else 0
                earned_now = calculate_total_tokens(current_refs, d_count)
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
        if not current_referred_by and valid_referrer:
            users_col.update_one(
                {"user_id": user_id}, 
                {"$set": {"verified": 1, "referred_by": valid_referrer}}
            )
            users_col.update_one({"user_id": valid_referrer}, {"$inc": {"ref_count": 1}})
            try:
                ref_user = users_col.find_one({"user_id": valid_referrer})
                current_refs = ref_user.get("ref_count", 1) if ref_user else 1
                d_count = ref_user.get("daily_count", 0) if ref_user else 0
                earned_now = calculate_total_tokens(current_refs, d_count)
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
        {"$set": {"submitted": new_status, "wallet": wallet}}
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
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_ans = num1 + num2

    captcha_col.replace_one(
        {"user_id": user_id},
        {"user_id": user_id, "num1": num1, "num2": num2, "answer": correct_ans, "pending_referrer": referrer_id},
        upsert=True
    )

    text = get_msg(user_id, "captcha_title", num1, num2)
    bot.send_message(chat_id, text, parse_mode="Markdown")

def send_database_backup(target_chat_id):
    try:
        all_users = list(users_col.find({}, {"_id": 0}))
        if not all_users:
            bot.send_message(target_chat_id, "⚠️ دیتابیس خالی است و کاربری برای بک‌آپ وجود ندارد.", reply_markup=get_admin_reply_markup())
            return
        
        json_data = json.dumps(all_users, ensure_ascii=False, indent=4)
        file_bytes = io.BytesIO(json_data.encode('utf-8'))
        file_bytes.name = f"manual_backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        
        bot.send_document(
            target_chat_id, 
            file_bytes, 
            caption="⚙️ **فایل پشتیبان کامل دیتابیس (آماده برای ایمپورت در لیارا)**", 
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(target_chat_id, f"❌ خطا در تهیه بک‌آپ:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def auto_backup_scheduler():
    while True:
        time.sleep(86400)
        try:
            all_users = list(users_col.find({}, {"_id": 0}))
            if all_users:
                json_data = json.dumps(all_users, ensure_ascii=False, indent=4)
                file_bytes = io.BytesIO(json_data.encode('utf-8'))
                file_bytes.name = f"auto_backup_{datetime.now().strftime('%Y-%m-%d')}.json"
                bot.send_document(
                    ADMIN_CHAT_ID, 
                    file_bytes, 
                    caption="⚙️ **پشتیبان‌گیری خودکار روزانه دیتابیس**", 
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Auto backup error: {e}")

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
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        csv_content += f"{uid},{ref_cnt},{d_count},{total_tokens},Not Registered\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
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
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        wlt = u.get("wallet")
        wallet_status = f"Registered ({wlt})" if wlt else "Not Registered"
        sub_status = u.get("submitted", 0)
        
        csv_content += f"{uid},{ref_cnt},{d_count},{total_tokens},{wallet_status},{sub_status}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
    file_bytes.name = 'under_threshold_users.csv'
    
    bot.send_document(
        chat_id, 
        file_bytes, 
        caption="📁 فایل کاربران **زیر حد نصاب (کمتر از ۳ دعوت)**", 
        reply_markup=get_admin_reply_markup(), 
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if is_admin(user_id):
        bot.send_message(
            user_id, 
            "👑 *به پنل مدیریت خوش آمدید.*\nاز دکمه‌های منوی پایین استفاده کنید.", 
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
    
    if referrer_id == user_id:
        bot.send_message(message.chat.id, get_msg(user_id, "self_ref"), parse_mode="Markdown")
        return

    if message.text and message.text.startswith('/menu'):
        if not check_membership(user_id):
            ask_to_join(message.chat.id, 0, user_id)
            return
        show_main_menu(message.chat.id, user_id)
        return

    user_data = get_user_data(user_id)
    if user_data and user_data[3] >= 2:
        if not check_membership(user_id):
            ask_to_join(message.chat.id, referrer_id if referrer_id else 0, user_id)
            return
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
        total = calculate_total_tokens(r_cnt, d_cnt)
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
    rows = list(users_col.find({"submitted": {"$gt": 0}}, {"ref_count": 1, "daily_count": 1, "paid": 1}))

    total_all_tokens = get_global_total_distributed_tokens()
    paid_tokens = 0
    unpaid_tokens = 0

    for u in rows:
        r_cnt = u.get("ref_count", 0)
        d_cnt = u.get("daily_count", 0)
        paid = u.get("paid", 0)
        t_tokens = calculate_total_tokens(r_cnt, d_cnt)
        if paid == 1:
            paid_tokens += t_tokens
        else:
            unpaid_tokens += t_tokens

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
        
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        remaining_tokens = max(0, total_tokens - paid_amt)
        base_used, extra_count = get_ref_details(ref_cnt)
        status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
        
        text += f"📌 آیدی عددی: `{uid}`\n" \
                f"👝 ولت: `{wlt}`\n" \
                f"👥 دعوت ثابت: {base_used} | مازاد: {extra_count} (کل: {ref_cnt})\n" \
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
    rows = list(users_col.find({"submitted": {"$gt": 0}, "paid": status_filter}).sort("ref_count", -1))

    status_name = "پرداخت‌شده" if status_filter == 1 else "در انتظار پرداخت"
    if not rows:
        bot.send_message(chat_id, f"⚠️ هیچ کاربری در وضعیت «{status_name}» وجود ندارد.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Wallet,Referrals,Daily Bonus Count,Total Tokens,Paid Amount,Status\n"
    for u in rows:
        uid = u.get("user_id")
        ref_cnt = u.get("ref_count", 0)
        wlt = u.get("wallet", "None")
        paid = u.get("paid", 0)
        d_count = u.get("daily_count", 0)
        paid_amt = u.get("paid_amount", 0)
        
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        st_text = "Paid" if paid == 1 else "Pending"
        csv_content += f"{uid},{wlt},{ref_cnt},{d_count},{total_tokens},{paid_amt},{st_text}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
    file_name = 'paid_users.csv' if status_filter == 1 else 'pending_users.csv'
    file_bytes.name = file_name
    
    caption_text = f"📁 فایل گزارش کاربران **{status_name}** (فرمت سازگار با اکسل/CSV)"
    bot.send_document(chat_id, file_bytes, caption=caption_text, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def send_detailed_report_file(chat_id):
    rows = list(users_col.find({}).sort([("paid", 1), ("ref_count", -1)]))

    if not rows:
        bot.send_message(chat_id, f"⚠️ هیچ کاربری در دیتابیس ثبت نشده است.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Referred By,Referral Count,Submitted Status,Paid Status,Verified Status,Wallet,Last Daily Timestamp,Daily Bonus Count,Total Tokens,Paid Amount,Language\n"
    for u in rows:
        uid = u.get("user_id")
        ref_by = u.get("referred_by", "None")
        ref_cnt = u.get("ref_count", 0)
        submitted = u.get("submitted", 0)
        paid = u.get("paid", 0)
        verified = u.get("verified", 0)
        wlt = str(u.get("wallet", "None")).replace(',', '_')
        last_daily = u.get("last_daily", 0)
        d_count = u.get("daily_count", 0)
        paid_amt = u.get("paid_amount", 0)
        lang = u.get("lang", "fa")
        
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        csv_content += f"{uid},{ref_by},{ref_cnt},{submitted},{paid},{verified},{wlt},{last_daily},{d_count},{total_tokens},{paid_amt},{lang}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
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
    if is_airdrop_finished():
        bot.send_message(chat_id, get_msg(user_id, "airdrop_finished"))
        return

    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    d_count = user_data[5] if user_data and len(user_data) > 5 else 0
    total_earned = calculate_total_tokens(ref_count, d_count)
    paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
    remaining_earned = max(0, total_earned - paid_amt)
    user_rank = get_user_rank(user_id)
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(get_msg(user_id, "btn_channel"), url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        InlineKeyboardButton(get_msg(user_id, "btn_twitter"), url=TWITTER_URL)
    )
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_insta"), url=INSTAGRAM_URL))
    
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_ref"), callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_daily"), callback_data="daily_bonus"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_guide"), callback_data="wallet_guide"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_top"), callback_data="leaderboard"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_status"), callback_data="my_status"), InlineKeyboardButton(get_msg(user_id, "btn_submit_w"), callback_data="submit_info"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_lang"), callback_data="toggle_language"))
    markup.row(InlineKeyboardButton(get_msg(user_id, "btn_refresh"), callback_data="refresh_menu"))

    caption_text = get_msg(user_id, "main_caption", base=BASE_REWARD, req=REQUIRED_REFERRALS, daily=DAILY_REWARD, extra=EXTRA_REWARD, uid=user_id, refs=ref_count, rank=user_rank, earned=total_earned, paid=paid_amt, rem=remaining_earned)
    
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

@bot.message_handler(content_types=['document'])
def handle_admin_documents(message):
    if not is_admin(message.from_user.id):
        return
    
    valid_users = {u["user_id"] for u in users_col.find({"submitted": {"$gt": 0}}, {"user_id": 1})}

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_text = downloaded_file.decode('utf-8', errors='ignore')
        
        lines = file_text.splitlines()
        updated_count = 0
        not_found_count = 0

        for line in lines:
            line = line.strip()
            if not line or line.startswith("User") or line.startswith("user"):
                continue
            
            parts = [p.strip() for p in line.replace(';', ',').split(',')]
            target_id = None
            
            for part in parts:
                if part.isdigit():
                    val = int(part)
                    if val in valid_users or val > 10000:
                        target_id = val
                        break
            
            if target_id:
                usr = users_col.find_one({"user_id": target_id})
                if usr:
                    r_cnt = usr.get("ref_count", 0)
                    d_cnt = usr.get("daily_count", 0)
                    tot = calculate_total_tokens(r_cnt, d_cnt)
                    users_col.update_one({"user_id": target_id}, {"$set": {"paid": 1, "paid_amount": tot}})
                    updated_count += 1
                else:
                    not_found_count += 1
            else:
                not_found_count += 1

        bot.send_message(
            message.chat.id,
            f"✅ **فایل پرداختی با موفقیت پردازش شد!**\n\n"
            f"🟢 تعداد کاربرانی که وضعیت‌شان به «پرداخت‌شده» تغییر یافت و موجودی‌شان ثبت شد: `{updated_count}` نفر\n"
            f"⚠️ شناسایی‌نشده یا نامعتبر: `{not_found_count}` مورد",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خطا در پردازش فایل اکسل/متنی:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    text = text.translate(persian_to_english)
    
    if is_admin(user_id):
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
                            success_count += 1
                        except Exception:
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
                    bot.send_message(chat_id, f"✅ پیام شخصی با موفقیت به کاربر `{target_uid}` ارسال شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                except Exception as e:
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
                users_col.update_one({"user_id": target_uid}, {"$set": {"wallet": text, "submitted": 1}})
                bot.send_message(chat_id, f"✅ ولت کاربر `{target_uid}` با موفقیت به مقدار جدید تغییر یافت:\n`{text}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                return

        if text == "🔴 خاموش کردن ربات":
            settings_col.replace_one({"key": "bot_status"}, {"key": "bot_status", "status": "off"}, upsert=True)
            bot.send_message(chat_id, "🔴 ربات با موفقیت **خاموش** شد. کاربران عادی دیگر قادر به استفاده از ربات نخواهند بود.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "🟢 روشن کردن ربات":
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
        elif text == "👝 مدیریت و تایید ولت‌ها":
            send_paginated_wallets(message, offset=0)
            return
        elif text == "📊 گزارش کلی توکن‌ها":
            show_token_summary_direct(chat_id)
            return
        elif text == "🔍 جستجوی کاربر (آیدی یا ولت)":
            bot.send_message(chat_id, "🔍 برای جستجو، دستور زیر را ارسال کنید:\n`/search [آیدی عددی یا بخشی از ولت]`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📁 آپلود اکسل پرداختی‌ها":
            bot.send_message(chat_id, "📁 لطفاً فایل خروجی پرداختی خود (فرمت CSV یا متنی حاوی آیدی یا ولت کاربران) را مستقیماً در همین چت آپلود کنید تا وضعیت آن‌ها اتوماتیک به «پرداخت‌شده» تغییر يابد.", reply_markup=get_admin_reply_markup())
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
            query_filter = {"user_id": int(query)} if query.isdigit() else {"wallet": {"$regex": query, "$options": "i"}}
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
                total_tokens = calculate_total_tokens(ref_cnt, d_cnt)
                base_used, extra_count = get_ref_details(ref_cnt)
                
                paid_status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
                
                res += (
                    f"👤 آیدی عددی: `{uid}`\n"
                    f"👥 کل رفال: {ref_cnt} (ثابت: {base_used} | مازاد: {extra_count})\n"
                    f"🎁 توکن کل: {total_tokens:,} | پرداخت شده: {paid_amt:,} PRS\n"
                    f"👝 ولت: `{wlt}`\n"
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

        if text.isdigit() and int(text) == correct_ans:
            captcha_col.delete_one({"user_id": user_id})
            
            if not check_membership(user_id):
                ask_to_join(chat_id, referrer_id if referrer_id else 0, user_id)
                return

            register_user_after_verify(user_id, referrer_id)
            show_main_menu(chat_id, user_id)
        else:
            new_n1 = random.randint(1, 10)
            new_n2 = random.randint(1, 10)
            new_correct_ans = new_n1 + new_n2

            captcha_col.update_one(
                {"user_id": user_id},
                {"$set": {"num1": new_n1, "num2": new_n2, "answer": new_correct_ans}}
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

    if text in [LANG["fa"]["main_kb_status"], LANG["en"]["main_kb_status"]]:
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
        remaining_earned = max(0, total_earned - paid_amt)
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else ("ثبت نشده" if get_msg(user_id, "lang")=="fa" else "Not registered")
        user_rank = get_user_rank(user_id)
        
        status_msg = get_msg(user_id, "status_box", uid=user_id, refs=ref_count, req=REQUIRED_REFERRALS, earned=total_earned, paid=paid_amt, rem=remaining_earned, rank=user_rank, wallet=wallet)
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
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        if ref_count < REQUIRED_REFERRALS:
            bot.send_message(chat_id, get_msg(user_id, "daily_locked", REQUIRED_REFERRALS))
            return
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        if current_time - last_daily < 86400:
            remaining = 86400 - (current_time - last_daily)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.send_message(chat_id, get_msg(user_id, "daily_already", hours, minutes))
        else:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"last_daily": current_time}, "$inc": {"daily_count": 1}}
            )
            bot.send_message(chat_id, get_msg(user_id, "daily_success", DAILY_REWARD))
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
            total_t = calculate_total_tokens(r_cnt, d_cnt)
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: (x[2], x[1]), reverse=True)
        top_10 = ranked_list[:10]
        
        text_lb = get_msg(user_id, "top_title")
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text_lb += get_msg(user_id, "top_row", idx, uid=uid, total=total_t, refs=r_cnt)
        bot.send_message(chat_id, text_lb, parse_mode="Markdown", reply_markup=get_main_reply_markup(user_id))
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
        submitted_status = user_doc.get("submitted", 0) if user_doc else 0

        if submitted_status >= 2:
            bot.send_message(chat_id, get_msg(user_id, "wallet_limit_err"))
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
        if call.data.startswith("admin_pay_"):
            parts = call.data.split("_")
            target_uid = int(parts[2])
            action = parts[3]
            
            usr = users_col.find_one({"user_id": target_uid})
            if usr:
                r_cnt = usr.get("ref_count", 0)
                d_cnt = usr.get("daily_count", 0)
                tot_tokens = calculate_total_tokens(r_cnt, d_cnt)
                
                if action == "yes":
                    users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 1, "paid_amount": tot_tokens}})
                elif action == "no":
                    users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 0}})
                elif action == "unpaid":
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

    if call.data.startswith("setlang_"):
        parts = call.data.split("_")
        chosen_lang = parts[1]
        referrer_id = int(parts[2])
        
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
        
        if not check_membership(user_id):
            no_join_msg = "❌ شما هنوز در کانال عضو نشده‌اید!" if get_msg(user_id, "lang")=="fa" else "❌ You have not joined the channel yet!"
            bot.answer_callback_query(call.id, no_join_msg, show_alert=True)
            return

        ok_join_msg = "✅ عضویت شما تایید شد!" if get_msg(user_id, "lang")=="fa" else "✅ Membership verified!"
        bot.answer_callback_query(call.id, ok_join_msg)
        register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
        
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
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        
        if ref_count < REQUIRED_REFERRALS:
            bot.answer_callback_query(call.id, "⚠️ پاداش روزانه قفل است!", show_alert=True)
            return
            
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        
        if current_time - last_daily < 86400:
            bot.answer_callback_query(call.id, "⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!", show_alert=True)
        else:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"last_daily": current_time}, "$inc": {"daily_count": 1}}
            )
            bot.answer_callback_query(call.id, "🎁 تبریک! پاداش روزانه اضافه شد.", show_alert=True)
            show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
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
            total_t = calculate_total_tokens(r_cnt, d_cnt)
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: (x[2], x[1]), reverse=True)
        top_10 = ranked_list[:10]
        
        text_lb = get_msg(user_id, "top_title")
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text_lb += get_msg(user_id, "top_row", idx, uid=uid, total=total_t, refs=r_cnt)
        bot.send_message(chat_id, text_lb, parse_mode="Markdown")
    elif call.data == "my_status":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
        remaining_earned = max(0, total_earned - paid_amt)
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else ("ثبت نشده" if get_msg(user_id, "lang")=="fa" else "Not registered")
        user_rank = get_user_rank(user_id)
        
        status_msg = get_msg(user_id, "status_box", uid=user_id, refs=ref_count, req=REQUIRED_REFERRALS, earned=total_earned, paid=paid_amt, rem=remaining_earned, rank=user_rank, wallet=wallet)
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

if __name__ == "__main__":
    print("Bot is starting with MongoDB & Dual-Language Support...")
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)

    backup_thread = threading.Thread(target=auto_backup_scheduler, daemon=True)
    backup_thread.start()

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)
