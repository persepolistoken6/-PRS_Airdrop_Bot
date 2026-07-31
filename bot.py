import io
import os
import random
import time
import json
import threading
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
settings_col = db.bot_settings  # کالکشن جدید برای ذخیره تنظیمات ربات (مانند وضعیت روشن/خاموش)

BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
TWITTER_URL = "https://x.com/PersepolisPRS"
INSTAGRAM_URL = "https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"
ADMIN_CHAT_ID = 6661478622
REQUIRED_REFERRALS = 3

BASE_REWARD = 1000
EXTRA_REWARD = 1000
DAILY_REWARD = 100
MAX_TOTAL_TOKENS_LIMIT = 500_000_000

BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = TeleBot(TOKEN, threaded=True)

def is_bot_globally_disabled():
    """بررسی اینکه آیا ربات توسط ادمین خاموش شده است یا خیر"""
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

def get_main_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📊 وضعیت من و رتبه", "🔗 دریافت لینک دعوت")
    markup.row("🎁 پاداش روزانه", "📝 ارسال / ویرایش آدرس ولت")
    markup.row("📖 راهنمای ولت و توکن", "🏆 برترین شرکت‌کنندگان")
    markup.row("🔄 به‌روزرسانی پنل کاربری", "📢 کانال تلگرام")
    markup.row("🐦 توییتر (ایکس)", "📸 اینستاگرام")
    return markup

def get_admin_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👝 مدیریت و تایید ولت‌ها", "📊 گزارش کلی توکن‌ها")
    markup.row("🔍 جستجوی کاربر (آیدی یا ولت)", "📁 آپلود اکسل پرداختی‌ها")
    markup.row("🟢 اکسل پرداخت‌شده‌ها", "🟡 اکسل در انتظار پرداخت")
    markup.row("📊 گزارش تفکیکی کامل (فایل)", "📥 دریافت فوری بک‌آپ (JSON)")
    markup.row("📈 آمار کلی ربات", "🔄 به‌روزرسانی پنل ادمین")
    markup.row("📢 ارسال همگانی پیام", "✉️ ارسال پیام شخصی به کاربر")
    markup.row("🔴 خاموش کردن ربات", "🟢 روشن کردن ربات")
    markup.row("🔙 خروج از حالت ادمین / منوی اصلی")
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
            "paid": 0,
            "verified": 1,
            "wallet": None,
            "last_daily": 0,
            "daily_count": 0,
            "paid_amount": 0
        })
        
        if valid_referrer:
            users_col.update_one({"user_id": valid_referrer}, {"$inc": {"ref_count": 1}})
            try:
                ref_user = users_col.find_one({"user_id": valid_referrer})
                current_refs = ref_user.get("ref_count", 1) if ref_user else 1
                d_count = ref_user.get("daily_count", 0) if ref_user else 0
                earned_now = calculate_total_tokens(current_refs, d_count)
                bot.send_message(
                    valid_referrer,
                    f"🎉 *یک زیرمجموعه جدید با لینک شما وارد شد!*\n\n"
                    f"👥 تعداد کل دعوت‌های شما: `{current_refs}`\n"
                    f"🎁 مجموع توکن کسب‌شده: `{earned_now}` PRS",
                    parse_mode="Markdown"
                )
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
                bot.send_message(
                    valid_referrer,
                    f"🎉 *یک زیرمجموعه جدید با لینک شما وارد شد!*\n\n"
                    f"👥 تعداد کل دعوت‌های شما: `{current_refs}`\n"
                    f"🎁 مجموع توکن کسب‌شده: `{earned_now}` PRS",
                    parse_mode="Markdown"
                )
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

def send_captcha(chat_id, user_id, referrer_id):
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_ans = num1 + num2

    captcha_col.replace_one(
        {"user_id": user_id},
        {"user_id": user_id, "num1": num1, "num2": num2, "answer": correct_ans, "pending_referrer": referrer_id},
        upsert=True
    )

    bot.send_message(
        chat_id,
        f"🛡 *تایید هویت امنیتی (ضد ربات و فیک)* \n\n"
        f"لطفاً حاصل جمع زیر را به عنوان پاسخ ارسال کنید:\n"
        f"❓ {num1} + {num2} = ؟\n\n"
        f"*(عدد پاسخ را در چت ارسال کنید)*",
        parse_mode="Markdown"
    )

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

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if user_id == ADMIN_CHAT_ID:
        bot.send_message(
            user_id, 
            "👑 *به پنل مدیریت دائمی خوش آمدید.*\nاز دکمه‌های منوی پایین استفاده کنید.", 
            reply_markup=get_admin_reply_markup(), 
            parse_mode="Markdown"
        )
        return

    if is_bot_globally_disabled():
        bot.send_message(message.chat.id, "🛑 ربات در حال حاضر توسط مدیریت موقتاً خاموش شده است. لطفاً بعداً مراجعه کنید.")
        return

    if is_airdrop_finished():
        bot.send_message(user_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    if message.text and message.text.startswith('/menu'):
        if not check_membership(user_id):
            ask_to_join(message.chat.id, 0)
            return
        show_main_menu(message.chat.id, user_id)
        return

    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    if referrer_id == user_id:
        bot.send_message(
            message.chat.id, 
            "⚠️ **شما نمی‌توانید روی لینک دعوت خودتان کلیک کنید!**\n\nلطفاً این لینک را برای دوستان خود ارسال کنید تا از طریق آن وارد ربات شوند.",
            parse_mode="Markdown"
        )
        return

    user_data = get_user_data(user_id)
    if user_data and user_data[3] >= 2:
        if not check_membership(user_id):
            ask_to_join(message.chat.id, referrer_id if referrer_id else 0)
            return
        show_main_menu(message.chat.id, user_id)
        return

    send_captcha(message.chat.id, user_id, referrer_id)

def ask_to_join(chat_id, referrer_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📢 عضویت در کانال رسمی", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    markup.row(InlineKeyboardButton("✅ عضو شدم، تایید کن", callback_data=f"check_join_{referrer_id}"))
    
    bot.send_message(
        chat_id,
        f"⚠️ **لطفاً برای ادامه کار ابتدا در کانال ما عضو شوید:**\n\n"
        f"▫️ {CHANNEL_ID}\n\n"
        f"پس از عضویت، روی دکمه‌ی «عضو شدم، تایید کن» بزنید.",
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
    return "محاسبه‌نشده"

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    bot.send_message(
        ADMIN_CHAT_ID,
        "👑 *پنل مدیریت ثابت فعال است.*",
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
            bot.edit_message_text(msg, chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
        else:
            bot.send_message(ADMIN_CHAT_ID, msg, reply_markup=get_admin_reply_markup())
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
            bot.edit_message_text(text, chat_id=ADMIN_CHAT_ID, message_id=message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass
    else:
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")

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

    csv_content = "User ID,Referred By,Referral Count,Submitted Status,Paid Status,Verified Status,Wallet,Last Daily Timestamp,Daily Bonus Count,Total Tokens,Paid Amount\n"
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
        
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        csv_content += f"{uid},{ref_by},{ref_cnt},{submitted},{paid},{verified},{wlt},{last_daily},{d_count},{total_tokens},{paid_amt}\n"

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
        bot.send_message(chat_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
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
        InlineKeyboardButton("📢 کانال تلگرام", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        InlineKeyboardButton("🐦 توییتر (ایکس)", url=TWITTER_URL)
    )
    markup.row(InlineKeyboardButton("📸 اینستاگرام پرسپولیس", url=INSTAGRAM_URL))
    
    markup.row(InlineKeyboardButton("🔗 دریافت لینک دعوت جذاب و اختصاصی", callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton("🎁 پاداش روزانه (100 PRS)", callback_data="daily_bonus"))
    markup.row(InlineKeyboardButton("📖 راهنمای ولت و توکن PRS", callback_data="wallet_guide"))
    markup.row(InlineKeyboardButton("🏆 برترین شرکت‌کنندگان (تاپ ۱۰)", callback_data="leaderboard"))
    markup.row(InlineKeyboardButton("📊 وضعیت من و رتبه", callback_data="my_status"), InlineKeyboardButton("📝 ارسال / ویرایش ولت", callback_data="submit_info"))
    markup.row(InlineKeyboardButton("🔄 به‌روزرسانی پنل کاربری", callback_data="refresh_menu"))

    caption_text = (
        f"🔴 *به ربات رسمی ایردراپ توکن هواداری پرسپولیس (PRS) خوش آمدید* 🏆\n\n"
        f"🪙 *معرفی پروژه:* توکن هواداری پرسپولیس بستری مدرن برای هواداران عزیز است تا در اکوسیستم دیجیتال باشگاه سهم داشته باشند.\n\n"
        f"🎁 *سیستم پاداش‌دهی و ایردراپ:*\n"
        f"▫️ پاداش پایه: `{BASE_REWARD} PRS` (پس از عضویت در کانال و دعوت `{REQUIRED_REFERRALS}` دوست)\n"
        f"▫️ پاداش روزانه: `{DAILY_REWARD} PRS` (فعال‌سازی پس از تکمیل ۳ دعوت و هر ۲۴ ساعت یک‌بار)\n"
        f"▫️ پاداش به ازای هر دعوت مازاد: `{EXTRA_REWARD} PRS`\n\n"
        f"📊 *وضعیت حساب شما:*\n"
        f"🆔 آیدی عددی شما: `{user_id}`\n"
        f"👥 دعوت‌های شما: `{ref_count} / {REQUIRED_REFERRALS}`\n"
        f"🏅 رتبه شما در بین کاربران: `{user_rank}`\n"
        f"🎁 کل توکن کسب‌شده: `{total_earned:,} PRS`\n"
        f"💳 توکن پرداخت شده: `{paid_amt:,} PRS`\n"
        f"💰 موجودی باقی‌مانده: `{remaining_earned:,} PRS`"
    )
    
    reply_markup_kb = get_main_reply_markup()

    if edit and message_id:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            bot.send_message(chat_id, "👇 منوی دسترسی سریع همیشه در پایین صفحه شما قرار دارد:", reply_markup=reply_markup_kb)
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
        bot.send_message(chat_id=chat_id, text="👇 منوی دسترسی سریع همیشه در پایین صفحه شما قرار دارد:", reply_markup=reply_markup_kb)
    except Exception as e:
        print(f"Error sending reply markup: {e}")

@bot.message_handler(content_types=['document'])
def handle_admin_documents(message):
    if message.from_user.id != ADMIN_CHAT_ID:
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
            ADMIN_CHAT_ID,
            f"✅ **فایل پرداختی با موفقیت پردازش شد!**\n\n"
            f"🟢 تعداد کاربرانی که وضعیت‌شان به «پرداخت‌شده» تغییر یافت و موجودی‌شان ثبت شد: `{updated_count}` نفر\n"
            f"⚠️ شناسایی‌نشده یا نامعتبر: `{not_found_count}` مورد",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ خطا در پردازش فایل اکسل/متنی:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    text = text.translate(persian_to_english)
    
    if is_bot_globally_disabled() and user_id != ADMIN_CHAT_ID:
        bot.send_message(chat_id, "🛑 ربات در حال حاضر توسط مدیریت موقتاً خاموش شده است. لطفاً بعداً مراجعه کنید.")
        return

    if user_id == ADMIN_CHAT_ID:
        admin_state = settings_col.find_one({"key": "admin_state"})
        if admin_state:
            state_val = admin_state.get("state")
            if state_val == "waiting_broadcast":
                settings_col.delete_one({"key": "admin_state"})
                if text == "❌ انصراف":
                    bot.send_message(ADMIN_CHAT_ID, "❌ ارسال همگانی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                
                bot.send_message(ADMIN_CHAT_ID, "🚀 عملیات ارسال همگانی با مکانیزم ضد اسپم آغاز شد...", reply_markup=get_admin_reply_markup())
                
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
                        ADMIN_CHAT_ID,
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
                bot.send_message(ADMIN_CHAT_ID, "✍️ حالا متن پیام شخصی خود را برای این کاربر ارسال کنید:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
                return

            elif state_val == "waiting_direct_text":
                target_uid = admin_state.get("target_uid")
                settings_col.delete_one({"key": "admin_state"})
                if text == "❌ انصراف":
                    bot.send_message(ADMIN_CHAT_ID, "❌ ارسال پیام شخصی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                
                try:
                    bot.send_message(target_uid, f"📩 **پیام از طرف مدیریت ربات:**\n\n{text}", parse_mode="Markdown")
                    bot.send_message(ADMIN_CHAT_ID, f"✅ پیام شخصی با موفقیت به کاربر `{target_uid}` ارسال شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                except Exception as e:
                    bot.send_message(ADMIN_CHAT_ID, f"❌ خطا در ارسال پیام به کاربر:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                return

            elif state_val == "waiting_manual_pay_id":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(ADMIN_CHAT_ID, "❌ ثبت پرداخت دستی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                if not text.isdigit():
                    bot.send_message(ADMIN_CHAT_ID, "⚠️ لطفاً یک آیدی عددی معتبر وارد کنید:")
                    return
                target_uid = int(text)
                usr = users_col.find_one({"user_id": target_uid})
                if not usr:
                    bot.send_message(ADMIN_CHAT_ID, "❌ کاربری با این آیدی در دیتابیس یافت نشد. لطفاً آیدی دیگری وارد کنید:")
                    return
                settings_col.update_one({"key": "admin_state"}, {"$set": {"state": "waiting_manual_pay_amount", "target_uid": target_uid}}, upsert=True)
                r_cnt = usr.get("ref_count", 0)
                d_cnt = usr.get("daily_count", 0)
                tot = calculate_total_tokens(r_cnt, d_cnt)
                bot.send_message(ADMIN_CHAT_ID, f"👤 کاربر پیدا شد.\n🎁 کل توکن محاسبه‌شده برای این کاربر: `{tot:,} PRS`\n\nحالا مقدار توکنی که می‌خواهید به عنوان پرداخت ثبت شود را وارد کنید (یا بنویسید `all` تا کل مبلغ ثبت شود):", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"), parse_mode="Markdown")
                return

            elif state_val == "waiting_manual_pay_amount":
                if text == "❌ انصراف":
                    settings_col.delete_one({"key": "admin_state"})
                    bot.send_message(ADMIN_CHAT_ID, "❌ ثبت پرداخت دستی لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                target_uid = admin_state.get("target_uid")
                settings_col.delete_one({"key": "admin_state"})
                usr = users_col.find_one({"user_id": target_uid})
                if not usr:
                    bot.send_message(ADMIN_CHAT_ID, "❌ خطا: کاربر یافت نشد.", reply_markup=get_admin_reply_markup())
                    return
                r_cnt = usr.get("ref_count", 0)
                d_cnt = usr.get("daily_count", 0)
                tot = calculate_total_tokens(r_cnt, d_cnt)
                
                if text.lower() == "all":
                    pay_amt = tot
                elif text.isdigit():
                    pay_amt = int(text)
                else:
                    bot.send_message(ADMIN_CHAT_ID, "⚠️ مقدار وارد شده نامعتبر است. عملیات لغو شد.", reply_markup=get_admin_reply_markup())
                    return
                
                users_col.update_one({"user_id": target_uid}, {"$set": {"paid": 1, "paid_amount": pay_amt}})
                bot.send_message(ADMIN_CHAT_ID, f"✅ پرداخت دستی با موفقیت ثبت شد!\n🆔 آیدی: `{target_uid}`\n💳 مبلغ ثبت‌شده: `{pay_amt:,} PRS`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
                return

        if text == "🔴 خاموش کردن ربات":
            settings_col.replace_one({"key": "bot_status"}, {"key": "bot_status", "status": "off"}, upsert=True)
            bot.send_message(ADMIN_CHAT_ID, "🔴 ربات با موفقیت **خاموش** شد. کاربران عادی دیگر قادر به استفاده از ربات نخواهند بود.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "🟢 روشن کردن ربات":
            settings_col.replace_one({"key": "bot_status"}, {"key": "bot_status", "status": "on"}, upsert=True)
            bot.send_message(ADMIN_CHAT_ID, "🟢 ربات با موفقیت **روشن** شد و به حالت عادی برگشت.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📢 ارسال همگانی پیام":
            settings_col.replace_one({"key": "admin_state"}, {"key": "admin_state", "state": "waiting_broadcast"}, upsert=True)
            bot.send_message(ADMIN_CHAT_ID, "📢 لطفاً متن پیام خود را برای ارسال همگانی به تمام کاربران ارسال کنید:\n*(برای انصراف دکمه زیر را بزنید)*", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
            return
        elif text == "✉️ ارسال پیام شخصی به کاربر":
            settings_col.replace_one({"key": "admin_state"}, {"key": "admin_state", "state": "waiting_direct_target"}, upsert=True)
            bot.send_message(ADMIN_CHAT_ID, "👤 لطفاً آیدی عددی (User ID) کاربر مورد نظر را ارسال کنید:\n*(برای انصراف دکمه زیر را بزنید)*", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).row("❌ انصراف"))
            return
        elif text == "👝 مدیریت و تایید ولت‌ها":
            send_paginated_wallets(message, offset=0)
            return
        elif text == "📊 گزارش کلی توکن‌ها":
            show_token_summary_direct(ADMIN_CHAT_ID)
            return
        elif text == "🔍 جستجوی کاربر (آیدی یا ولت)":
            bot.send_message(ADMIN_CHAT_ID, "🔍 برای جستجو، دستور زیر را ارسال کنید:\n`/search [آیدی عددی یا بخشی از ولت]`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📁 آپلود اکسل پرداختی‌ها":
            bot.send_message(ADMIN_CHAT_ID, "📁 لطفاً فایل خروجی پرداختی خود (فرمت CSV یا متنی حاوی آیدی یا ولت کاربران) را مستقیماً در همین چت آپلود کنید تا وضعیت آن‌ها اتوماتیک به «پرداخت‌شده» تغییر یابد.", reply_markup=get_admin_reply_markup())
            return
        elif text == "🟢 اکسل پرداخت‌شده‌ها":
            send_status_excel_report(ADMIN_CHAT_ID, status_filter=1)
            return
        elif text == "🟡 اکسل در انتظار پرداخت":
            send_status_excel_report(ADMIN_CHAT_ID, status_filter=0)
            return
        elif text == "📊 گزارش تفکیکی کامل (فایل)":
            send_detailed_report_file(ADMIN_CHAT_ID)
            return
        elif text == "📥 دریافت فوری بک‌آپ (JSON)":
            send_database_backup(ADMIN_CHAT_ID)
            return
        elif text == "📈 آمار کلی ربات":
            show_stats_direct(ADMIN_CHAT_ID)
            return
        elif text == "🔄 به‌روزرسانی پنل ادمین":
            bot.send_message(ADMIN_CHAT_ID, "🔄 پنل مدیریت با موفقیت به‌روزرسانی و بازنشانی شد.", reply_markup=get_admin_reply_markup())
            return
        elif text == "🔙 خروج از حالت ادمین / منوی اصلی":
            bot.send_message(ADMIN_CHAT_ID, "مجدداً پنل مدیریتی ثابت فعال است.", reply_markup=get_admin_reply_markup())
            return
        elif text.startswith("/search "):
            query = text.replace("/search", "").strip()
            query_filter = {"user_id": int(query)} if query.isdigit() else {"wallet": {"$regex": query, "$options": "i"}}
            rows = list(users_col.find(query_filter))
            if not rows:
                bot.send_message(ADMIN_CHAT_ID, "❌ هیچ کاربری با این مشخصات پیدا نشد.", reply_markup=get_admin_reply_markup())
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
                res += f"👤 آیدی عددی: `{uid}`\n👥 کل رفال: {ref_cnt} (ثابت: {base_used} | مازاد: {extra_count})\n🎁 توکن کل: {total_tokens:,} | پرداخت شده: {paid_amt:,} PRS\n👝 ولت: `{wlt}`\n📌 ثبت فرم: `{submitted}` | پرداخت: `{paid}`\n---\n"
            bot.send_message(ADMIN_CHAT_ID, res, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text.startswith("/deleteuser "):
            target_id = text.replace("/deleteuser", "").strip()
            if target_id.isdigit():
                users_col.delete_one({"user_id": int(target_id)})
                captcha_col.delete_one({"user_id": int(target_id)})
                bot.send_message(ADMIN_CHAT_ID, f"✅ کاربر با آیدی عددی `{target_id}` به طور کامل حذف شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            else:
                bot.send_message(ADMIN_CHAT_ID, "⚠️ آیدی عددی وارد شده معتبر نیست.", reply_markup=get_admin_reply_markup())
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
                ask_to_join(chat_id, referrer_id if referrer_id else 0)
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

            bot.send_message(
                chat_id, 
                f"❌ پاسخ اشتباه است!\n\n"
                f"🛡 یک سوال امنیتی جدید برای شما ارسال شد:\n"
                f"❓ لطفاً حاصل جمع {new_n1} + {new_n2} را بفرستید:"
            )
        return

    if is_airdrop_finished() and user_id != ADMIN_CHAT_ID:
        bot.send_message(user_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    if not check_membership(user_id):
        ask_to_join(chat_id, 0)
        return

    if text == "📊 وضعیت من و رتبه":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        paid_amt = user_data[7] if user_data and len(user_data) > 7 else 0
        remaining_earned = max(0, total_earned - paid_amt)
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"🆔 آیدی عددی شما: `{user_id}`\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 کل توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"💳 توکن پرداخت شده: `{paid_amt:,} PRS`\n"
            f"💰 موجودی باقی‌مانده: `{remaining_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"👝 آدرس ولت فعلی: `{wallet}`"
        )
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
        return
    elif text == "🔗 دریافت لینک دعوت":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        link_text = (
            f"🔥 بزرگترین ایردراپ توکن هواداری پرسپولیس (PRS) 🔥\n\n"
            f"🏆 فرصت استثنایی برای دریافت توکن رایگان و ورود به اکوسیستم دیجیتال پرسپولیس!\n"
            f"🎁 همین الان با لینک زیر وارد ربات شو و پاداش ورودت رو بگیر:\n\n"
            f"{ref_link}\n\n"
            f"این پیام رو برای دوستان خود ارسال کنید"
        )
        try:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=link_text)
        except Exception:
            bot.send_message(chat_id=chat_id, text=link_text)
        return
    elif text == "🎁 پاداش روزانه":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        if ref_count < REQUIRED_REFERRALS:
            bot.send_message(chat_id, f"⚠️ پاداش روزانه قفل است!\nبرای باز شدن آن باید حداقل {REQUIRED_REFERRALS} دوست دعوت کنید.")
            return
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        if current_time - last_daily < 86400:
            remaining = 86400 - (current_time - last_daily)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.send_message(chat_id, f"⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!\nلطفاً پس از {hours} ساعت و {minutes} دقیقه دیگر تلاش کنید.")
        else:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"last_daily": current_time}, "$inc": {"daily_count": 1}}
            )
            bot.send_message(chat_id, f"🎁 تبریک! مبلغ {DAILY_REWARD} توکن PRS به عنوان پاداش روزانه به حساب شما اضافه شد.")
        return
    elif text == "📖 راهنمای ولت و توکن":
        guide_text = (
            f"📖 *راهنمای کامل و گام‌به‌گام نصب کیف پول و اضافه کردن توکن پرسپولیس (PRS):*\n\n"
            f"🔹 **مقدمه:** توکن هواداری پرسپولیس روی شبکه قدرتمند **BNB Smart Chain (BSC / BEP20)** راه‌اندازی شده است. برای دریافت و نگهداری آن، بهترین پیشنهاد استفاده از اپلیکیشن امن **Trust Wallet (تراست ولت)** است.\n\n"
            f"📱 **مرحله اول: نصب و ساخت کیف پول**\n"
            f"• برنامه Trust Wallet را از گوگل‌پلی یا اپ‌استور دانلود کنید.\n"
            f"• یک کیف پول جدید بسازید و **۱۲ کلمه بازیابی (Seed Phrase)** خود را حتماً روی کاغذ یادداشت کنید و در جای امن نگه دارید.\n\n"
            f"📋 **مرحله دوم: کپی کردن آدرس ولت (برای ارسال به ربات)**\n"
            f"• در صفحه اصلی تراست ولت، روی ارز **BNB** (یا شبکه اسمارت چین / Smart Chain) بزنید.\n"
            f"• روی گزینه **Receive** (دریافت) بزنید.\n"
            f"• آدرس کیف پول خود (متن طولانی شروع شده با `0x`) را کپی کرده و در بخش **«ارسال / ویرایش آدرس ولت»** در همین ربات بفرستید.\n\n"
            f"🪙 **مرحله سوم: چطور توکن پرسپولیس (PRS) را در تراست ولت نمایش دهیم؟**\n"
            f"چون این توکن جدید است، ممکن است به صورت خودکار در لیست ارزهای شما دیده نشود. برای اضافه کردن دستی (Custom Token):\n"
            f"1. وارد تراست ولت شوید و روی **علامت مثبت (+)** یا آیکون تنظیمات در بالای صفحه بزنید.\n"
            f"2. شبکه (Network) را روی حالت **BNB Smart Chain** قرار دهید.\n"
            f"3. آدرس قرارداد (Contract Address) توکن پرسپولیس را در کادر مربوطه وارد کنید تا نام و مشخصات توکن ظاهر شود.\n"
            f"4. روی گزینه **Save** یا **Add Token** بزنید تا توکن پرسپولیس به لیست کیف پول شما اضافه شود و پس از واریز، موجودی خود را ببینید."
        )
        bot.send_message(chat_id, guide_text, parse_mode="Markdown")
        return
    elif text == "🏆 برترین شرکت‌کنندگان":
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
        
        text = "🏆 *۱۰ شرکت‌کننده برتر ایردراپ (براساس مجموع توکن‌ها)*:\n\n"
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text += f"{idx}. آیدی: `{uid}` — 🎁 توکن کل: *{total_t:,} PRS* (دعوت: {r_cnt})\n"
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_main_reply_markup())
        return
    elif text == "🔄 به‌روزرسانی پنل کاربری":
        show_main_menu(chat_id, user_id)
        return
    elif text == "📝 ارسال / ویرایش آدرس ولت":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        submitted = user_data[1] if user_data else 0
        
        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")
        if submitted >= 2:
            errors.append("⚠️ شما سهمیه ثبت‌نام و تنها ویرایش مجاز خود را استفاده کرده‌اید و دیگر امکان تغییر ولت وجود ندارد.")
            
        if errors:
            bot.send_message(chat_id, "⚠️ **امکان ثبت/ویرایش ولت وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.", parse_mode="Markdown")
            return
        
        if submitted == 1:
            bot.send_message(chat_id, "✏️ **حالت ویرایش ولت:**\nشما قبلاً ولت خود را ثبت کرده بودید. اکنون می‌توانید آدرس ولت شبکه اسمارت‌چین (BNB Smart Chain / BEP20) خود را ارسال کنید:")
        else:
            bot.send_message(chat_id, "لطفاً آدرس ولت شبکه اسمارت‌چین (BNB Smart Chain / شروع شده با 0x) خود را ارسال کنید:")
        return
    elif text == "📢 کانال تلگرام":
        bot.send_message(chat_id, f"📢 کانال رسمی: {CHANNEL_ID}")
        return
    elif text == "🐦 توییتر (ایکس)":
        bot.send_message(chat_id, f"🐦 صفحه توییتر: {TWITTER_URL}")
        return
    elif text == "📸 اینستاگرام":
        bot.send_message(chat_id, f"📸 صفحه اینستاگرام: {INSTAGRAM_URL}")
        return

    user_doc = users_col.find_one({"user_id": user_id})
    submitted_status = user_doc.get("submitted", 0) if user_doc else 0

    if submitted_status < 2 or len(text) > 10:
        if submitted_status >= 2:
            bot.send_message(chat_id, "⚠️ شما سهمیه ویرایش خود را به اتمام رسانده‌اید.")
            return
            
        save_submission(user_id, text, submitted_status)
        
        if submitted_status == 0:
            bot.send_message(chat_id, "✅ آدرس ولت شبکه اسمارت‌چین شما با موفقیت ثبت شد.")
        else:
            bot.send_message(chat_id, "✅ آدرس ولت شما با موفقیت **ویرایش و به‌روزرسانی شد**.")
        
        show_main_menu(chat_id, user_id)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if is_bot_globally_disabled() and user_id != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "🛑 ربات در حال حاضر توسط مدیریت خاموش است.", show_alert=True)
        return

    if is_airdrop_finished() and user_id != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "🛑 ایردراپ به اتمام رسید.", show_alert=True)
        return

    if call.data.startswith("check_join_"):
        referrer_id = int(call.data.split("_")[2])
        
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)
            return

        bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد!")
        register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        
        show_main_menu(chat_id, user_id)
        return

    if call.data.startswith("admin_pay_"):
        if user_id != ADMIN_CHAT_ID:
            return
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
        if user_id != ADMIN_CHAT_ID:
            return
        offset = int(call.data.split("_")[2])
        bot.answer_callback_query(call.id)
        send_paginated_wallets(call.message, offset=offset, edit=True)
        return

    if call.data == "refresh_menu":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            ask_to_join(chat_id, 0)
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
        
        link_text = (
            f"🔥 بزرگترین ایردراپ توکن هواداری پرسپولیس (PRS) 🔥\n\n"
            f"🏆 فرصت استثنایی برای دریافت توکن رایگان و ورود به اکوسیستم دیجیتال پرسپولیس!\n"
            f"🎁 همین الان با لینک زیر وارد ربات شو و پاداش ورودت رو بگیر:\n\n"
            f"{ref_link}\n\n"
            f"این پیام رو برای دوستان خود ارسال کنید"
        )
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
            bot.answer_callback_query(call.id, f"⚠️ پاداش روزانه قفل است!", show_alert=True)
            return
            
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        
        if current_time - last_daily < 86400:
            bot.answer_callback_query(call.id, f"⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!", show_alert=True)
        else:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"last_daily": current_time}, "$inc": {"daily_count": 1}}
            )
            bot.answer_callback_query(call.id, f"🎁 تبریک! پاداش روزانه اضافه شد.", show_alert=True)
            show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
    elif call.data == "wallet_guide":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        guide_text = (
            f"📖 *راهنمای کامل و گام‌به‌گام نصب کیف پول و اضافه کردن توکن پرسپولیس (PRS):*\n\n"
            f"🔹 **مقدمه:** توکن هواداری پرسپولیس روی شبکه قدرتمند **BNB Smart Chain (BSC / BEP20)** راه‌اندازی شده است. برای دریافت و نگهداری آن، بهترین پیشنهاد استفاده از اپلیکیشن امن **Trust Wallet (تراست ولت)** است.\n\n"
            f"📱 **مرحله اول: نصب و ساخت کیف پول**\n"
            f"• برنامه Trust Wallet را از گوگل‌پلی یا اپ‌استور دانلود کنید.\n"
            f"• یک کیف پول جدید بسازید و **۱۲ کلمه بازیابی (Seed Phrase)** خود را حتماً روی کاغذ یادداشت کنید و در جای امن نگه دارید.\n\n"
            f"📋 **مرحله دوم: کپی کردن آدرس ولت (برای ارسال به ربات)**\n"
            f"• در صفحه اصلی تراست ولت، روی ارز **BNB** (یا شبکه اسمارت چین / Smart Chain) بزنید.\n"
            f"• روی گزینه **Receive** (دریافت) بزنید.\n"
            f"• آدرس کیف پول خود (متن طولانی شروع شده با `0x`) را کپی کرده و در بخش **«ارسال / ویرایش آدرس ولت»** در همین ربات بفرستید.\n\n"
            f"🪙 **مرحله سوم: چطور توکن پرسپولیس (PRS) را در تراست ولت نمایش دهیم؟**\n"
            f"چون این توکن جدید است، ممکن است به صورت خودکار در لیست ارزهای شما دیده نشود. برای اضافه کردن دستی (Custom Token):\n"
            f"1. وارد تراست ولت شوید و روی **علامت مثبت (+)** یا آیکون تنظیمات در بالای صفحه بزنید.\n"
            f"2. شبکه (Network) را روی حالت **BNB Smart Chain** قرار دهید.\n"
            f"3. آدرس قرارداد (Contract Address) توکن پرسپولیس را در کادر مربوطه وارد کنید تا نام و مشخصات توکن ظاهر شود.\n"
            f"4. روی گزینه **Save** یا **Add Token** بزنید تا توکن پرسپولیس به لیست کیف پول شما اضافه شود و پس از واریز، موجودی خود را ببینید."
        )
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
        
        text = "🏆 *۱۰ شرکت‌کننده برتر ایردراپ*:\n\n"
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text += f"{idx}. آیدی: `{uid}` — 🎁 توکن کل: *{total_t:,} PRS* (دعوت: {r_cnt})\n"
        bot.send_message(chat_id, text, parse_mode="Markdown")
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
        wallet = user_data[6] if user_data and len(user_data) > 6 and user_data[6] else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"🆔 آیدی عددی شما: `{user_id}`\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 کل توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"💳 توکن پرداخت شده: `{paid_amt:,} PRS`\n"
            f"💰 موجودی باقی‌مانده: `{remaining_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"👝 آدرس ولت فعلی: `{wallet}`"
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
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است.")
        if submitted >= 2:
            errors.append("⚠️ شما سهمیه ثبت‌نام و تنها ویرایش مجاز خود را استفاده کرده‌اید.")

        if errors:
            bot.answer_callback_query(call.id, "⚠️ شرایط لازم را ندارید!", show_alert=True)
            bot.send_message(
                chat_id,
                "⚠️ **امکان ثبت/ویرایش ولت وجود ندارد:**\n\n" + "\n".join(errors),
                parse_mode="Markdown"
            )
            return

        bot.answer_callback_query(call.id)
        if submitted == 1:
            bot.send_message(chat_id, "✏️ **حالت ویرایش ولت:** آدرس شبکه اسمارت‌چین جدید خود را ارسال کنید:")
        else:
            bot.send_message(chat_id, "لطفاً آدرس ولت شبکه اسمارت‌چین (BNB Smart Chain) خود را ارسال کنید:")

if __name__ == "__main__":
    print("Bot is starting with MongoDB...")
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
