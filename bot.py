import logging, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import config
import database as db

# جلوگیری از double payment
_paying_users: set = set()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNELS = ["@safeserverr"]  # کانال پیش‌فرض

def get_active_channels():
    db_chs = db.get_forced_channels()
    return db_chs if db_chs else CHANNELS

PLAN_LABELS = {
    # V2ray
    "1gb": "اشتراک ۱ گیگ",
    "2gb": "اشتراک ۲ گیگ",
    "3gb": "اشتراک ۳ گیگ",
    "5gb": "اشتراک ۵ گیگ",
    "10gb": "اشتراک ۱۰ گیگ",
    # OpenVPN
    "ovpn_unlimited_1": "OpenVPN نامحدود تک‌کاربر",
    "ovpn_unlimited_2": "OpenVPN نامحدود دو کاربر",
    "ovpn_30gb": "OpenVPN حجمی ۳۰ گیگ",
    "ovpn_50gb": "OpenVPN حجمی ۵۰ گیگ",
    "ovpn_100gb": "OpenVPN حجمی ۱۰۰ گیگ",
    # WireGuard
    "wg_unlimited_1": "WireGuard نامحدود تک‌کاربر",
    # Gaming
    "gaming_1gb": "Gaming اشتراک ۱ گیگ",
    "gaming_2gb": "Gaming اشتراک ۲ گیگ",
    "gaming_3gb": "Gaming اشتراک ۳ گیگ",
    "gaming_5gb": "Gaming اشتراک ۵ گیگ",
    "gaming_10gb": "Gaming اشتراک ۱۰ گیگ",
    # تست و رفرال
    "20mb": "تست ۲۰ مگ رایگان",
    "500mb_referral": "رفرال ۵۰۰ مگ",
    "100mb_referral": "رفرال ۱۰۰ مگ",
    "referral": "رفرال",
}

# ── Helpers ───────────────────────────────────────────────

def is_admin(uid): return uid in config.ADMIN_IDS or uid in db.get_admin_ids()
def all_admins(): return list(set(config.ADMIN_IDS + db.get_admin_ids()))
def fmt(p): return f"{p:,} تومان"
def flag(key, default="1"): return db.get_setting(key, default) != "0"

def card(): return db.get_setting("card_number") or config.CARD_NUMBER
def cardholder(): return db.get_setting("card_holder") or config.CARD_HOLDER

def price(key):
    db_val = db.get_setting(f"price_{key}")
    if db_val:
        return int(db_val)
    for plans in [config.PLANS, config.TEST_PLANS, config.OPENVPN_PLANS, config.WIREGUARD_PLANS]:
        if key in plans:
            return plans[key].get("price", 0)
    return 0

def get_plan(key):
    for plans in [config.PLANS, config.GAMING_PLANS, config.TEST_PLANS, config.OPENVPN_PLANS, config.WIREGUARD_PLANS]:
        if key in plans:
            return plans[key]
    return None

def vip_discount(uid, plan_price=None):
    if not flag("vip_open"):
        return 0
    u = db.get_user(uid)
    if not u:
        return 0
    vip_balance = u.get("vip_balance", 0)
    if vip_balance <= 0:
        return 0
    if plan_price is not None and vip_balance < plan_price:
        return 0
    return db.get_vip_discount()

def price_for_user(key, uid):
    p = price(key)
    disc = vip_discount(uid, plan_price=p)
    if disc > 0:
        return int(p * (100 - disc) / 100)
    return p

def crypto_rate(coin):
    val = db.get_setting(f"crypto_rate_{coin}")
    return int(val) if val else 0

def crypto_wallet(coin):
    val = db.get_setting(f"crypto_wallet_{coin}")
    if val: return val
    return config.CRYPTO_WALLETS.get(coin, {}).get("address", "")

def escape_md(text: str) -> str:
    if not text:
        return text
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text

def uinfo(u):
    un = f"@{escape_md(u['username'])}" if u.get("username") else "ندارد"
    full_name = escape_md(u['full_name'])
    return f"👤 {full_name}\n🔗 {un}\n🆔 `{u['user_id']}`"

def is_file_plan(key):
    """پلن‌هایی که با فایل ارسال میشن"""
    return key in config.OPENVPN_PLANS or key in config.WIREGUARD_PLANS

async def is_member(bot, user_id):
    for ch in get_active_channels():
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True

def main_kb(uid=None):
    rows = [
        [KeyboardButton("🛒 خرید اشتراک"), KeyboardButton("🧪 اکانت تست")],
        [KeyboardButton("👥 زیرمجموعه‌گیری"), KeyboardButton("🎧 پشتیبانی")],
        [KeyboardButton("👤 حساب من"), KeyboardButton("💳 افزایش موجودی")],
        [KeyboardButton("📋 اشتراک‌های من"), KeyboardButton("👑 نمایندگی VIP")],
        [KeyboardButton("📚 راهنمای استفاده")],
    ]
    if uid and is_admin(uid):
        rows.append([KeyboardButton("🔧 پنل ادمین")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def join_kb():
    chs = get_active_channels()
    buttons = []
    for ch in chs:
        name = ch.lstrip("@")
        buttons.append([InlineKeyboardButton(f"📢 {name}", url=f"https://t.me/{name}")])
    buttons.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")])
    return InlineKeyboardMarkup(buttons)

def admin_kb():
    s_sales  = "🟢 فروش باز"  if flag("sales_open")  else "🔴 فروش بسته"
    s_card   = "🟢 کارت باز"  if flag("card_open")   else "🔴 کارت بسته"
    s_topup  = "🟢 شارژ باز"  if flag("topup_open")  else "🔴 شارژ بسته"
    s_crypto = "🟢 ارز باز"   if flag("crypto_open") else "🔴 ارز بسته"
    s_test   = "🟢 تست باز"   if flag("test_open")   else "🔴 تست بسته"
    s_ref    = "🟢 رفرال باز"  if flag("referral_open") else "🔴 رفرال بسته"
    disc = db.get_vip_discount()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 کاربران", callback_data="a_users"),
         InlineKeyboardButton("💰 پرداخت‌های در انتظار", callback_data="a_pays")],
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="a_search_user"),
         InlineKeyboardButton("📦 مدیریت کانفیگ‌ها", callback_data="a_configs")],
        [InlineKeyboardButton("📁 مدیریت فایل‌ها", callback_data="a_file_configs")],
        [InlineKeyboardButton("📚 مدیریت آموزش‌ها", callback_data="a_tutorials")],
        [InlineKeyboardButton("💲 قیمت‌ها", callback_data="a_prices"),
         InlineKeyboardButton("💳 اطلاعات کارت", callback_data="a_card_menu")],
        [InlineKeyboardButton("💎 تنظیمات ارز دیجیتال", callback_data="a_crypto")],
        [InlineKeyboardButton("👤 مدیریت ادمین‌ها", callback_data="a_admins")],
        [InlineKeyboardButton("💰 موجودی کاربر", callback_data="a_balance"),
         InlineKeyboardButton("📢 پیام همگانی", callback_data="a_broadcast")],
        [InlineKeyboardButton("✉️ پیام به کاربر", callback_data="a_msg_user"),
         InlineKeyboardButton("🚫 بن کاربر", callback_data="a_ban_user")],
        [InlineKeyboardButton("📋 اشتراک‌های من (کاربر)", callback_data="a_user_subs"),
         InlineKeyboardButton(f"📢 کانال‌های اجباری", callback_data="a_channels")],
        [InlineKeyboardButton(f"🏷 تخفیف VIP: {disc}٪ ← تغییر", callback_data="a_set_vip_discount")],
        [InlineKeyboardButton(f"{s_sales} ← تغییر", callback_data="a_toggle_sales")],
        [InlineKeyboardButton(f"{s_card} ← تغییر", callback_data="a_toggle_card"),
         InlineKeyboardButton(f"{s_topup} ← تغییر", callback_data="a_toggle_topup")],
        [InlineKeyboardButton(f"{s_crypto} ← تغییر", callback_data="a_toggle_crypto")],
        [InlineKeyboardButton(f"{s_test} ← تغییر", callback_data="a_toggle_test")],
        [InlineKeyboardButton(f"{s_ref} ← تغییر", callback_data="a_toggle_referral")],
        [InlineKeyboardButton(f"{'🟢 VIP باز' if flag('vip_open') else '🔴 VIP بسته'} ← تغییر", callback_data="a_toggle_vip"),
         InlineKeyboardButton("👑 نمایندگی VIP", callback_data="a_vip_panel")],
        [InlineKeyboardButton("🕐 ۱۰ خرید اخیر", callback_data="a_last_purchases")],
        [InlineKeyboardButton("📊 گزارش فروش", callback_data="a_sales_report")],
    ])

def back_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")]])

# ── State ─────────────────────────────────────────────────

def gs(uid): return db.load_state(uid)
def ss(uid, state): db.save_state(uid, state)
def cs(uid): db.clear_state(uid)

# ── Payment timeout ───────────────────────────────────────

async def pay_timeout(bot, pay_id, user_id, chat_id, secs):
    await asyncio.sleep(secs)
    pay = db.get_payment(pay_id)
    if pay and pay["status"] == "pending":
        db.cancel_payment(pay_id)
        cs(user_id)
        try:
            await bot.send_message(chat_id, "⏰ زمان پرداخت تمام شد و سفارش لغو شد.", reply_markup=main_kb(user_id))
        except Exception: pass

# ── Channel check ─────────────────────────────────────────

async def require_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if is_admin(uid): return True
    if not await is_member(context.bot, uid):
        text = "⛔️ برای استفاده از ربات باید عضو کانال ما باشید:"
        kb = join_kb()
        if update.message:
            await update.message.reply_text(text, reply_markup=kb)
        elif update.callback_query:
            await update.callback_query.answer("ابتدا عضو کانال شوید", show_alert=True)
        return False
    return True

# ── /start ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cs(user.id)

    ref = None
    if context.args:
        ru = db.get_user_by_referral(context.args[0])
        if ru and ru["user_id"] != user.id:
            ref = ru["user_id"]

    db_user = db.get_or_create_user(user.id, user.username or "", user.full_name or "", ref)

    if ref and db_user["_is_new"]:
        ref_owner = db.get_user(ref)
        if ref_owner:
            try:
                await context.bot.send_message(
                    ref,
                    f"🎉 دعوت شما موفق بود!\n"
                    f"👤 {db_user['full_name']} عضو شد.\n"
                    f"💰 هر بار که این کاربر خرید کند، ۱۰٪ کمیسیون به کیف پول شما اضافه می‌شود."
                )
            except Exception: pass

    if not await is_member(context.bot, user.id) and not is_admin(user.id):
        await update.message.reply_text(
            f"سلام {user.first_name} عزیز! 👋\n\nبرای استفاده از ربات ابتدا باید عضو کانال ما شوید:",
            reply_markup=join_kb()
        )
        return

    await update.message.reply_text(
        f"سلام {user.first_name} عزیز! 👋\nبه ربات Safe-Server خوش آمدید.",
        reply_markup=main_kb(user.id)
    )

# ── Message router ────────────────────────────────────────

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tg = update.effective_user
    if db.is_banned(uid) and not is_admin(uid):
        await update.message.reply_text("⛔️ شما از ربات مسدود شده‌اید.")
        return
    if not db.get_user(uid):
        db.get_or_create_user(uid, tg.username or "", tg.full_name or "")
    text = update.message.text or ""
    state = gs(uid)
    w = state.get("w")

    if w:
        if w == "receipt":              await recv_receipt(update, context); return
        if w == "topup_receipt":        await recv_topup_receipt(update, context); return
        if w == "crypto_receipt":       await recv_crypto_receipt(update, context); return
        if w == "crypto_topup_receipt": await recv_crypto_topup_receipt(update, context); return
        if w == "topup_crypto_amount":  await recv_topup_crypto_amount(update, context); return
        if w == "support":              await recv_support(update, context); return
        if w == "topup_amount":         await recv_topup_amount(update, context); return
        if w == "a_bal_uid":            await a_recv_bal_uid(update, context); return
        if w == "a_bal_amt":            await a_recv_bal_amt(update, context); return
        if w == "a_price":              await a_recv_price(update, context); return
        if w == "a_configs":            await a_recv_configs(update, context); return
        if w == "a_del_cfg_count":      await a_recv_del_cfg_count(update, context); return
        if w == "a_broadcast":          await a_recv_broadcast(update, context); return
        if w == "a_add_admin":          await a_recv_add_admin(update, context); return
        if w == "a_del_admin":          await a_recv_del_admin(update, context); return
        if w == "a_card":               await a_recv_card(update, context); return
        if w == "a_cardholder":         await a_recv_cardholder(update, context); return
        if w == "a_send_cfg":           await a_recv_send_cfg(update, context); return
        if w == "a_crypto_rate":        await a_recv_crypto_rate(update, context); return
        if w == "a_crypto_wallet":      await a_recv_crypto_wallet(update, context); return
        if w == "a_msg_user_id":        await a_recv_msg_user_id(update, context); return
        if w == "a_msg_user_text":      await a_recv_msg_user_text(update, context); return
        if w == "a_ban_uid":            await a_recv_ban_uid(update, context); return
        if w == "a_unban_uid":          await a_recv_unban_uid(update, context); return
        if w == "a_user_subs_uid":      await a_recv_user_subs_uid(update, context); return
        if w == "a_add_channel":        await a_recv_add_channel(update, context); return
        if w == "a_vip_discount":       await a_recv_vip_discount(update, context); return
        if w == "a_search_uid":         await a_recv_search_uid(update, context); return
        if w == "a_del_file_cfg_count": await a_recv_del_file_cfg_count(update, context); return
        cs(uid)

    if not await require_member(update, context): return

    if text == "🛒 خرید اشتراک":          await show_purchase_menu(update, context)
    elif text == "🧪 اکانت تست":          await show_test(update, context)
    elif text == "👥 زیرمجموعه‌گیری":     await show_referral(update, context)
    elif text == "🎧 پشتیبانی":           await start_support(update, context)
    elif text == "👤 حساب من":            await show_account(update, context)
    elif text == "💳 افزایش موجودی":      await start_topup(update, context)
    elif text == "📋 اشتراک‌های من":       await show_my_subs(update, context)
    elif text == "👑 نمایندگی VIP":        await show_vip_info(update, context)
    elif text == "📚 راهنمای استفاده":    await show_tutorials(update, context)
    elif text == "🔧 پنل ادمین" and is_admin(uid): await show_admin(update, context)

async def on_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.effective_user.id
    msg = update.message
    has_photo = bool(msg.photo)
    has_doc   = bool(msg.document)
    has_text  = bool(msg.text)
    has_video = bool(msg.video)
    logger.info(f"on_any_message: uid={uid}, photo={has_photo}, doc={has_doc}, text={has_text}, video={has_video}")

    state = gs(uid)
    w = state.get("w")
    logger.info(f"on_any_message: state_w={w}")

    # ادمین داره ویدیوی آموزشی آپلود می‌کنه
    if is_admin(uid) and w == "a_upload_tutorial" and (has_video or has_photo or has_doc):
        await a_recv_tutorial_video(update, context)
        return

    # ادمین داره فایل کانفیگ آپلود می‌کنه
    if is_admin(uid) and (has_photo or has_doc) and w == "a_upload_file_cfg":
        await a_recv_file_config(update, context)
        return

    if (has_photo or has_doc) and w in ("receipt", "topup_receipt", "crypto_receipt", "crypto_topup_receipt"):
        if w == "receipt":
            await recv_receipt(update, context)
        elif w == "topup_receipt":
            await recv_topup_receipt(update, context)
        elif w == "crypto_topup_receipt":
            await recv_crypto_topup_receipt(update, context)
        else:
            await recv_crypto_receipt(update, context)
        return

    if has_text:
        await on_message(update, context)

# ── Purchase Menu ─────────────────────────────────────────

async def show_purchase_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی خرید — ۴ نوع سرویس"""
    if not flag("sales_open"):
        await update.message.reply_text("🔴 فروش در حال حاضر بسته است.")
        return
    await update.message.reply_text(
        "🛒 *خرید اشتراک — Safe-Server*\n\nنوع سرویس را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 V2ray-Happ", callback_data="cat_v2ray")],
            [InlineKeyboardButton("🎮 Gaming", callback_data="cat_gaming")],
            [InlineKeyboardButton("🔐 WireGuard", callback_data="cat_wireguard")],
            [InlineKeyboardButton("🛡 Open VPN", callback_data="cat_openvpn")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ])
    )

async def show_category_plans(q, uid, category):
    """نمایش پلن‌های یک دسته"""
    if not flag("sales_open"):
        await q.edit_message_text("🔴 فروش در حال حاضر بسته است.")
        return

    disc = vip_discount(uid)

    if category == "v2ray":
        title = "🌐 *پلن‌های V2ray-Happ*"
        plans = config.PLANS
        icon = "🌐"
    elif category == "gaming":
        title = "🎮 *پلن‌های Gaming*"
        plans = config.GAMING_PLANS
        icon = "🎮"
    elif category == "wireguard":
        title = "🔐 *پلن‌های WireGuard*"
        plans = config.WIREGUARD_PLANS
        icon = "🔐"
    elif category == "openvpn":
        title = "🛡 *پلن‌های Open VPN*"
        plans = config.OPENVPN_PLANS
        icon = "🛡"
    else:
        return

    kb = []
    for key, plan in plans.items():
        p = price_for_user(key, uid)
        label = f"{icon} {plan['name']} — {fmt(p)}"
        if disc > 0:
            label += f" (🏷 {disc}٪ VIP)"
        kb.append([InlineKeyboardButton(label, callback_data=f"plan_{category}_{key}")])

    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_cats")])
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

    header = f"{title}\n\n"
    if disc > 0:
        header += "👑 تخفیف VIP فعال است\n\n"
    header += "پلن مورد نظر را انتخاب کنید:"

    await q.edit_message_text(header, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ── Callbacks ─────────────────────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id

    if d == "check_join":
        if await is_member(context.bot, uid):
            await q.edit_message_text("✅ عضویت تایید شد!", reply_markup=None)
            await context.bot.send_message(uid, "به ربات Safe-Server خوش آمدید! 👋", reply_markup=main_kb(uid))
        else:
            await q.answer("هنوز عضو نشدید! ابتدا عضو کانال شوید.", show_alert=True)
        return

    if not is_admin(uid) and not d.startswith("a_"):
        if not await is_member(context.bot, uid):
            await q.answer("ابتدا عضو کانال شوید", show_alert=True)
            return

    # ── دسته‌بندی خرید
    if d == "cat_v2ray":
        await show_category_plans(q, uid, "v2ray")
        return
    elif d == "cat_gaming":
        await show_category_plans(q, uid, "gaming")
        return
    elif d == "cat_wireguard":
        await show_category_plans(q, uid, "wireguard")
        return
    elif d == "cat_openvpn":
        await show_category_plans(q, uid, "openvpn")
        return
    elif d == "back_to_cats":
        await q.edit_message_text(
            "🛒 *خرید اشتراک — Safe-Server*\n\nنوع سرویس را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 V2ray-Happ", callback_data="cat_v2ray")],
                [InlineKeyboardButton("🎮 Gaming", callback_data="cat_gaming")],
                [InlineKeyboardButton("🔐 WireGuard", callback_data="cat_wireguard")],
                [InlineKeyboardButton("🛡 Open VPN", callback_data="cat_openvpn")],
                [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
            ])
        )
        return

    # ── انتخاب پلن (فرمت: plan_<category>_<key>)
    if d.startswith("plan_"):
        rest = d[5:]  # category_key
        parts = rest.split("_", 1)
        if len(parts) < 2: return
        category = parts[0]
        plan_key = parts[1]

        if not flag("sales_open"):
            await q.edit_message_text("🔴 فروش در حال حاضر بسته است.")
            return
        plan = get_plan(plan_key)
        if not plan: return
        p = dict(plan)
        p["price"] = price(plan_key)
        await show_invoice(q, uid, p, plan_key, f"sub_{category}")
        return

    elif d == "get_free_test":
        await do_free_test(q, uid, context)

    elif d.startswith("pay_card_"):
        key = d[9:]
        await do_card_payment(q, uid, key, context)

    elif d.startswith("pay_wallet_"):
        key = d[11:]
        await do_wallet_payment(q, uid, key, context)

    elif d.startswith("pay_crypto_"):
        rest = d[11:]
        coin, key = rest.split("_", 1)
        await do_crypto_payment(q, uid, coin, key, context)

    elif d == "cancel":
        cs(uid)
        await q.edit_message_text("❌ عملیات لغو شد.")

    # ── آموزش
    elif d == "tut_back":
        await q.edit_message_text(
            "📚 *راهنمای استفاده — Safe-Server*\n\nنوع سرویس خود را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 آموزش V2ray", callback_data="tut_v2ray")],
                [InlineKeyboardButton("🔐 آموزش WireGuard", callback_data="tut_wireguard")],
                [InlineKeyboardButton("🛡 آموزش OpenVPN", callback_data="tut_openvpn")],
            ])
        )
    elif d in ("tut_v2ray", "tut_wireguard", "tut_openvpn"):
        category = d[4:]
        await send_tutorial(q, category, context)

    # ── آپلود آموزش از ادمین
    elif d.startswith("a_set_tutorial_"):
        category = d[15:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_upload_tutorial", "category": category})
        labels = {"v2ray": "V2ray", "wireguard": "WireGuard", "openvpn": "OpenVPN"}
        await q.edit_message_text(
            f"📹 *آپلود آموزش {labels.get(category, category)}*\n\nویدیو را با کپشن دلخواه ارسال کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="a_back")]])
        )
    elif d.startswith("a_del_tutorial_"):
        category = d[15:]
        if not is_admin(uid): return
        db.delete_tutorial(category)
        await a_show_tutorials(q, uid)

    elif d == "vip_join":
        await start_vip_topup(q, uid, context)
    elif d == "topup_card_vip":
        ss(uid, {"w": "topup_amount", "vip": True})
        await q.edit_message_text(
            "👑 *شارژ VIP — کارت به کارت*\n\nحداقل ۵,۰۰۰,۰۰۰ تومان وارد کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    elif d.startswith("topup_crypto_vip_"):
        coin = d[17:]
        rate = crypto_rate(coin)
        if rate <= 0:
            await q.answer("نرخ این ارز تنظیم نشده است.", show_alert=True); return
        cinfo = config.CRYPTO_WALLETS.get(coin, {})
        wallet_addr = crypto_wallet(coin)
        ss(uid, {"w": "topup_crypto_amount", "coin": coin, "vip": True})
        await q.edit_message_text(
            f"{cinfo.get('emoji','💎')} *شارژ VIP با {cinfo.get('name', coin)}*\n\n"
            f"💱 نرخ فعلی: {rate:,} تومان / {cinfo.get('symbol', coin)}\n"
            f"📬 آدرس کیف پول:\n`{wallet_addr}`\n\n"
            f"حداقل معادل ۵,۰۰۰,۰۰۰ تومان وارد کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    elif d == "topup_card":
        ss(uid, {"w": "topup_amount"})
        await q.edit_message_text(
            "💳 مبلغ شارژ را وارد کنید (50,000 تا 10,000,000 تومان):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    elif d.startswith("topup_crypto_"):
        coin = d[13:]
        rate = crypto_rate(coin)
        if rate <= 0:
            await q.answer("نرخ این ارز تنظیم نشده است.", show_alert=True); return
        cinfo = config.CRYPTO_WALLETS.get(coin, {})
        wallet_addr = crypto_wallet(coin)
        ss(uid, {"w": "topup_crypto_amount", "coin": coin})
        await q.edit_message_text(
            f"{cinfo.get('emoji','💎')} *شارژ با {cinfo.get('name', coin)} — Safe-Server*\n\n"
            f"💱 نرخ فعلی: {rate:,} تومان / {cinfo.get('symbol', coin)}\n"
            f"📬 آدرس کیف پول:\n`{wallet_addr}`\n\n"
            f"مبلغ مورد نظر را به تومان وارد کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))

    elif d.startswith("ac_"):
        pay_id = int(d[3:])
        await admin_confirm(q, pay_id, context)
    elif d.startswith("ar_"):
        pay_id = int(d[3:])
        await admin_reject(q, pay_id, context)
    elif d.startswith("am_"):
        target = int(d[3:])
        if not is_admin(uid): return
        ss(uid, {"w": "a_send_cfg", "target": target, "mode": "msg"})
        await q.edit_message_text("✍️ پیام خود را بنویسید:")
    elif d.startswith("asc_"):
        pay_id = int(d[4:])
        if not is_admin(uid): return
        pay = db.get_payment(pay_id)
        if not pay: return
        ss(uid, {"w": "a_send_cfg", "target": pay["user_id"], "pay_id": pay_id, "mode": "cfg"})
        await q.edit_message_text(
            f"📦 کانفیگ را برای ارسال به کاربر `{pay['user_id']}` وارد کنید:",
            parse_mode="Markdown"
        )

    elif d == "a_last_purchases":
        if not is_admin(uid): return
        await a_show_last_purchases(q, uid, context)
    elif d == "a_sales_report":
        if not is_admin(uid): return
        await a_show_sales_report(q, uid, "daily")
    elif d == "a_sales_daily":
        if not is_admin(uid): return
        await a_show_sales_report(q, uid, "daily")
    elif d == "a_sales_weekly":
        if not is_admin(uid): return
        await a_show_sales_report(q, uid, "weekly")
    elif d == "a_sales_monthly":
        if not is_admin(uid): return
        await a_show_sales_report(q, uid, "monthly")

    # ── پنل ادمین
    elif d == "a_back":
        await q.edit_message_text("🔧 *پنل مدیریت*", parse_mode="Markdown", reply_markup=admin_kb())
    elif d == "a_users":   await a_show_users(q)
    elif d == "a_pays":    await a_show_pays(q)
    elif d == "a_configs": await a_show_configs(q, uid)
    elif d == "a_file_configs": await a_show_file_configs(q, uid)
    elif d == "a_tutorials": await a_show_tutorials(q, uid)
    elif d == "a_prices":  await a_show_prices(q, uid)
    elif d == "a_crypto":  await a_show_crypto(q, uid)
    elif d == "a_card_menu":
        if not is_admin(uid): return
        await q.edit_message_text(
            f"💳 *اطلاعات کارت فعلی*\n\nشماره: `{card()}`\nبه نام: {cardholder()}\n\nچه چیزی را تغییر می‌دهید؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔢 شماره کارت", callback_data="a_card"),
                 InlineKeyboardButton("👤 نام دارنده", callback_data="a_cardholder")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")],
            ])
        )
    elif d == "a_card":
        if not is_admin(uid): return
        ss(uid, {"w": "a_card"})
        await q.edit_message_text(f"💳 شماره کارت فعلی: `{card()}`\n\nشماره جدید را وارد کنید:", parse_mode="Markdown")
    elif d == "a_cardholder":
        if not is_admin(uid): return
        ss(uid, {"w": "a_cardholder"})
        await q.edit_message_text(f"👤 نام دارنده فعلی: {cardholder()}\n\nنام جدید را وارد کنید:")
    elif d == "a_admins":  await a_show_admins(q, uid)
    elif d == "a_add_admin":
        if not is_admin(uid): return
        ss(uid, {"w": "a_add_admin"})
        await q.edit_message_text("آیدی عددی کاربر جدید را وارد کنید:")
    elif d == "a_del_admin":
        if not is_admin(uid): return
        ss(uid, {"w": "a_del_admin"})
        await q.edit_message_text("آیدی عددی ادمین را برای حذف وارد کنید:")
    elif d == "a_balance":
        if not is_admin(uid): return
        ss(uid, {"w": "a_bal_uid"})
        await q.edit_message_text("آیدی عددی کاربر را وارد کنید:")
    elif d == "a_broadcast":
        if not is_admin(uid): return
        ss(uid, {"w": "a_broadcast"})
        await q.edit_message_text("📢 متن پیام همگانی را بنویسید:")
    elif d == "a_toggle_sales":
        if not is_admin(uid): return
        v = flag("sales_open"); db.set_setting("sales_open", "0" if v else "1")
        await q.edit_message_text(f"✅ فروش {'بسته' if v else 'باز'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_card":
        if not is_admin(uid): return
        v = flag("card_open"); db.set_setting("card_open", "0" if v else "1")
        await q.edit_message_text(f"✅ پرداخت کارت {'بسته' if v else 'باز'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_topup":
        if not is_admin(uid): return
        v = flag("topup_open"); db.set_setting("topup_open", "0" if v else "1")
        await q.edit_message_text(f"✅ افزایش موجودی {'بسته' if v else 'باز'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_crypto":
        if not is_admin(uid): return
        v = flag("crypto_open"); db.set_setting("crypto_open", "0" if v else "1")
        await q.edit_message_text(f"✅ پرداخت ارزی {'بسته' if v else 'باز'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_test":
        if not is_admin(uid): return
        v = flag("test_open"); db.set_setting("test_open", "0" if v else "1")
        await q.edit_message_text(f"✅ اکانت تست {'بسته' if v else 'باز'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_referral":
        if not is_admin(uid): return
        v = flag("referral_open"); db.set_setting("referral_open", "0" if v else "1")
        await q.edit_message_text(f"✅ سیستم رفرال {'غیرفعال' if v else 'فعال'} شد.", reply_markup=back_kb())
    elif d == "a_toggle_vip":
        if not is_admin(uid): return
        v = flag("vip_open"); db.set_setting("vip_open", "0" if v else "1")
        await q.edit_message_text(f"✅ سیستم VIP {'غیرفعال' if v else 'فعال'} شد.", reply_markup=back_kb())
    elif d == "a_vip_panel":
        if not is_admin(uid): return
        await a_show_vip_panel(q, uid)

    elif d == "a_search_user":
        if not is_admin(uid): return
        ss(uid, {"w": "a_search_uid"})
        await q.edit_message_text("🔍 آیدی عددی کاربر را وارد کنید:")

    elif d.startswith("su_ban_"):
        tid = int(d[7:])
        if not is_admin(uid): return
        if tid in config.ADMIN_IDS or tid in db.get_admin_ids():
            await q.answer("نمی‌توانید ادمین را بن کنید.", show_alert=True); return
        db.ban_user(tid)
        await q.answer("✅ کاربر بن شد.")
        try: await context.bot.send_message(tid, "⛔️ دسترسی شما به ربات مسدود شده است.")
        except: pass
        ss(uid, {"w": "a_search_uid"})
        await q.edit_message_text(f"✅ کاربر `{tid}` بن شد.\n\nبرای جستجوی دیگری آیدی بفرستید:", parse_mode="Markdown")

    elif d.startswith("su_unban_"):
        tid = int(d[9:])
        if not is_admin(uid): return
        db.unban_user(tid)
        await q.answer("✅ بن برداشته شد.")
        try: await context.bot.send_message(tid, "✅ مسدودیت شما از ربات برداشته شد.")
        except: pass
        ss(uid, {"w": "a_search_uid"})
        await q.edit_message_text(f"✅ بن کاربر `{tid}` برداشته شد.\n\nبرای جستجوی دیگری آیدی بفرستید:", parse_mode="Markdown")

    elif d.startswith("su_bal_"):
        tid = int(d[7:])
        if not is_admin(uid): return
        t = db.get_user(tid)
        ss(uid, {"w": "a_bal_amt", "tid": tid})
        await q.edit_message_text(f"💰 موجودی فعلی کاربر `{tid}`: {fmt(t['balance'])}\n\nمقدار تغییر را وارد کنید (مثبت یا منفی):", parse_mode="Markdown")

    elif d.startswith("su_msg_"):
        tid = int(d[7:])
        if not is_admin(uid): return
        ss(uid, {"w": "a_msg_user_text", "tid": tid})
        await q.edit_message_text(f"✍️ پیام خود را برای کاربر `{tid}` بنویسید:", parse_mode="Markdown")

    elif d.startswith("su_subs_"):
        tid = int(d[8:])
        if not is_admin(uid): return
        subs = db.get_user_subscriptions(tid)
        t = db.get_user(tid)
        name = escape_md(t["full_name"]) if t else str(tid)
        if not subs:
            await q.edit_message_text(f"📋 کاربر {name} هیچ اشتراکی ندارد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")]]))
            return
        text = f"📋 *اشتراک‌های {name}*\n\n"
        for s in subs:
            has_cfg = "✅" if s.get("config_sent") else "⏳"
            text += f"{has_cfg} {s['plan_name']} — {s['created_at'][:10]}\n"
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")]]))

    elif d == "a_msg_user":
        if not is_admin(uid): return
        ss(uid, {"w": "a_msg_user_id"})
        await q.edit_message_text("✉️ آیدی عددی کاربر را وارد کنید:")

    elif d == "a_ban_user":
        if not is_admin(uid): return
        await q.edit_message_text(
            "🚫 *مدیریت بن*\n\nعملیات مورد نظر را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 بن کردن با آیدی", callback_data="a_do_ban")],
                [InlineKeyboardButton("✅ رفع بن با آیدی", callback_data="a_do_unban")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")],
            ])
        )
    elif d == "a_do_ban":
        if not is_admin(uid): return
        ss(uid, {"w": "a_ban_uid"})
        await q.edit_message_text("🚫 آیدی عددی کاربر را برای بن وارد کنید:")
    elif d == "a_do_unban":
        if not is_admin(uid): return
        ss(uid, {"w": "a_unban_uid"})
        await q.edit_message_text("✅ آیدی عددی کاربر را برای رفع بن وارد کنید:")

    elif d == "a_user_subs":
        if not is_admin(uid): return
        ss(uid, {"w": "a_user_subs_uid"})
        await q.edit_message_text("📋 آیدی عددی کاربر را وارد کنید:")

    elif d == "a_channels":
        if not is_admin(uid): return
        await a_show_channels(q, uid)
    elif d == "a_add_channel":
        if not is_admin(uid): return
        ss(uid, {"w": "a_add_channel"})
        await q.edit_message_text("📢 آیدی کانال را وارد کنید (مثال: @mychannel):")
    elif d.startswith("a_del_channel_"):
        ch = d[14:]
        if not is_admin(uid): return
        db.remove_forced_channel(ch)
        await a_show_channels(q, uid)

    elif d == "a_set_vip_discount":
        if not is_admin(uid): return
        cur = db.get_vip_discount()
        ss(uid, {"w": "a_vip_discount"})
        await q.edit_message_text(
            f"🏷 *تغییر درصد تخفیف VIP*\n\nمقدار فعلی: {cur}٪\n\nعدد جدید را وارد کنید (مثلاً 20):",
            parse_mode="Markdown"
        )

    # ── مدیریت کانفیگ‌های متنی
    elif d.startswith("a_addcfg_"):
        plan_key = d[9:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_configs", "plan_key": plan_key})
        await q.edit_message_text(
            f"📦 *افزودن کانفیگ — {PLAN_LABELS.get(plan_key, plan_key)}*\n\nهر کانفیگ را در یک خط جداگانه بنویسید:",
            parse_mode="Markdown"
        )
    elif d.startswith("a_delcfg_all_"):
        plan_key = d[13:]
        if not is_admin(uid): return
        deleted = db.delete_unused_configs(plan_key)
        await q.edit_message_text(
            f"✅ {deleted} کانفیگ از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شد.",
            reply_markup=back_kb()
        )
    elif d.startswith("a_delcfg_num_"):
        plan_key = d[13:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_del_cfg_count", "plan_key": plan_key})
        await q.edit_message_text(
            f"🔢 چند تا کانفیگ از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شود?\n\nعدد را بنویسید:"
        )
    elif d.startswith("a_delcfg_"):
        plan_key = d[9:]
        if not is_admin(uid): return
        cnt = db.get_config_count(plan_key)
        await q.edit_message_text(
            f"🗑 *پاک کردن کانفیگ — {PLAN_LABELS.get(plan_key, plan_key)}*\n\n"
            f"📊 موجودی فعلی: {cnt} عدد\n\nچند تا پاک شود؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 همه را پاک کن", callback_data=f"a_delcfg_all_{plan_key}")],
                [InlineKeyboardButton("🔢 تعداد دلخواه", callback_data=f"a_delcfg_num_{plan_key}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="a_configs")],
            ])
        )

    # ── مدیریت فایل‌های WireGuard / OpenVPN
    elif d.startswith("a_add_file_"):
        plan_key = d[11:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_upload_file_cfg", "plan_key": plan_key})
        plan_label = PLAN_LABELS.get(plan_key, plan_key)
        if plan_key.startswith("ovpn_"):
            hint = "\n\n📌 فایل را با کپشن یوزر:پسورد بفرستید."
        else:
            hint = "\n\n📌 فایل WireGuard را بفرستید (بدون کپشن یا با توضیح)."
        await q.edit_message_text(
            f"📁 *آپلود فایل — {plan_label}*{hint}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="a_file_configs")]])
        )
    elif d.startswith("a_del_file_all_"):
        plan_key = d[15:]
        if not is_admin(uid): return
        deleted = db.delete_unused_file_configs(plan_key)
        await q.edit_message_text(
            f"✅ {deleted} فایل از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شد.",
            reply_markup=back_kb()
        )
    elif d.startswith("a_del_file_num_"):
        plan_key = d[15:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_del_file_cfg_count", "plan_key": plan_key})
        await q.edit_message_text(
            f"🔢 چند تا فایل از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شود?\n\nعدد را بنویسید:"
        )
    elif d.startswith("a_del_file_"):
        plan_key = d[11:]
        if not is_admin(uid): return
        cnt = db.get_file_config_count(plan_key)
        await q.edit_message_text(
            f"🗑 *پاک کردن فایل — {PLAN_LABELS.get(plan_key, plan_key)}*\n\n"
            f"📊 موجودی فعلی: {cnt} عدد",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 همه را پاک کن", callback_data=f"a_del_file_all_{plan_key}")],
                [InlineKeyboardButton("🔢 تعداد دلخواه", callback_data=f"a_del_file_num_{plan_key}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="a_file_configs")],
            ])
        )

    elif d.startswith("a_pay_detail_"):
        pay_id = int(d[13:])
        if not is_admin(uid): return
        pay = db.get_payment(pay_id)
        if not pay:
            await q.edit_message_text("⚠️ پرداخت یافت نشد.", reply_markup=back_kb()); return
        method = pay.get("pay_method", "card")
        method_label = {"card": "💳 کارت", "wallet": "💰 موجودی", "crypto": f"💎 ارز ({pay.get('crypto_coin','')})"}.get(method, "💳")
        text = (
            f"🧾 *جزئیات پرداخت*\n\n"
            f"🔖 فاکتور: `{pay['invoice_code']}`\n"
            f"👤 کاربر ID: `{pay['user_id']}`\n"
            f"📦 پلن: {pay.get('plan_name','—')}\n"
            f"💵 مبلغ: {fmt(pay['amount'])}\n"
            f"💳 روش: {method_label}\n"
            f"🕐 تاریخ: {pay['created_at'][:16]}"
        )
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تایید + ارسال کانفیگ", callback_data=f"ac_{pay_id}"),
                 InlineKeyboardButton("❌ رد", callback_data=f"ar_{pay_id}")],
                [InlineKeyboardButton("📤 تایید + کانفیگ دستی", callback_data=f"asc_{pay_id}")],
                [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{pay['user_id']}")],
                [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="a_pays")],
            ])
        )

    elif d.startswith("a_setprice_"):
        key = d[11:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_price", "key": key})
        cur = price(key)
        await q.edit_message_text(f"قیمت فعلی «{PLAN_LABELS.get(key,key)}»: {fmt(cur)}\n\nقیمت جدید (تومان):")
    elif d.startswith("a_set_crypto_rate_"):
        coin = d[18:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_crypto_rate", "coin": coin})
        cur = crypto_rate(coin)
        cinfo = config.CRYPTO_WALLETS.get(coin, {})
        await q.edit_message_text(
            f"{cinfo.get('emoji','💎')} نرخ فعلی {cinfo.get('name', coin)}: {cur:,} تومان\n\n"
            f"نرخ جدید را وارد کنید:",
        )
    elif d.startswith("a_set_crypto_wallet_"):
        coin = d[20:]
        if not is_admin(uid): return
        ss(uid, {"w": "a_crypto_wallet", "coin": coin})
        cur = crypto_wallet(coin)
        cinfo = config.CRYPTO_WALLETS.get(coin, {})
        await q.edit_message_text(
            f"{cinfo.get('emoji','💎')} آدرس فعلی {cinfo.get('name', coin)}:\n`{cur}`\n\nآدرس جدید را وارد کنید:",
            parse_mode="Markdown"
        )

# ── Invoice / Payment ──────────────────────────────────────

async def show_invoice(q, uid, plan, plan_key, ptype):
    u = db.get_user(uid)
    bal = u["balance"] if u else 0
    original_p = plan["price"]
    disc = vip_discount(uid, plan_price=original_p)
    p = int(original_p * (100 - disc) / 100) if disc > 0 else original_p
    text = (
        f"🧾 *فاکتور خرید — Safe-Server*\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"📊 حجم: {plan['size']}\n"
    )
    if plan.get("duration"):
        text += f"⏱ مدت: {plan['duration']}\n"
    if plan.get("users") and plan["users"] != "—":
        text += f"👥 کاربران: {plan['users']}\n"
    if disc > 0:
        text += f"💵 قیمت اصلی: {fmt(original_p)}\n"
        text += f"🏷 تخفیف VIP ({disc}٪): -{fmt(original_p - p)}\n"
    text += f"💵 مبلغ نهایی: *{fmt(p)}*\n💰 موجودی شما: {fmt(bal)}\n\nروش پرداخت را انتخاب کنید:"

    key = f"{ptype}_{plan_key}"
    kb = [
        [InlineKeyboardButton("💳 پرداخت با کارت" + ("" if flag("card_open") else " (غیرفعال)"),
                              callback_data=f"pay_card_{key}")],
        [InlineKeyboardButton(f"💰 پرداخت با موجودی {'✅' if bal>=p else '(ناکافی)'}",
                              callback_data=f"pay_wallet_{key}")],
    ]
    if flag("crypto_open"):
        for coin, cinfo in config.CRYPTO_WALLETS.items():
            rate = crypto_rate(coin)
            if rate > 0:
                crypto_amount = round(p / rate, 4)
                kb.append([InlineKeyboardButton(
                    f"{cinfo['emoji']} پرداخت با {cinfo['symbol']} ({crypto_amount} {cinfo['symbol']})",
                    callback_data=f"pay_crypto_{coin}_{key}"
                )])
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def _parse_ptype_plankey(key):
    """جدا کردن ptype و plan_key از رشته ترکیبی
    فرمت: sub_<category>_<plan_key>  مثلاً sub_v2ray_1gb یا sub_openvpn_ovpn_unlimited_1
    """
    # key مثلاً: sub_v2ray_1gb
    parts = key.split("_", 2)  # ['sub', 'v2ray', '1gb']
    if len(parts) < 3:
        return None, None, None
    ptype = parts[0]  # 'sub'
    category = parts[1]  # 'v2ray'
    plan_key = parts[2]  # '1gb' یا 'ovpn_unlimited_1'
    return ptype, category, plan_key

async def do_card_payment(q, uid, key, context):
    if not flag("card_open"):
        await q.edit_message_text("🔴 پرداخت کارت به کارت غیرفعال است.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ بستن", callback_data="cancel")]]))
        return
    ptype, category, plan_key = _parse_ptype_plankey(key)
    if not plan_key: return
    plan = get_plan(plan_key)
    if not plan: return
    p = price(plan_key)
    pay_id, inv = db.create_payment(uid, p, ptype, plan_key, plan["name"], pay_method="card")
    ss(uid, {"w": "receipt", "pay_id": pay_id, "plan_key": plan_key, "plan_name": plan["name"], "ptype": ptype, "category": category})
    await q.edit_message_text(
        f"💳 *اطلاعات پرداخت — Safe-Server*\n\n"
        f"🔖 کد فاکتور: `{inv}`\n"
        f"📦 پلن: {plan['name']}\n"
        f"💵 مبلغ: *{fmt(p)}*\n\n"
        f"شماره کارت:\n`{card()}`\n"
        f"به نام: {cardholder()}\n\n"
        f"⏰ *{config.PAYMENT_TIMEOUT_MINUTES} دقیقه* فرصت دارید.\n"
        f"پس از واریز، تصویر رسید را ارسال کنید.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]])
    )
    asyncio.create_task(pay_timeout(context.bot, pay_id, uid, q.message.chat_id, config.PAYMENT_TIMEOUT_MINUTES * 60))

async def do_wallet_payment(q, uid, key, context):
    if uid in _paying_users:
        await q.answer("⏳ در حال پردازش...", show_alert=True)
        return
    _paying_users.add(uid)
    try:
        await _do_wallet_payment_inner(q, uid, key, context)
    finally:
        _paying_users.discard(uid)

async def _do_wallet_payment_inner(q, uid, key, context):
    ptype, category, plan_key = _parse_ptype_plankey(key)
    if not plan_key: return
    plan = get_plan(plan_key)
    if not plan: return
    p = price(plan_key)

    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ در حال پردازش...", callback_data="noop")]
        ]))
    except Exception:
        pass

    if not db.deduct_balance_if_enough(uid, p):
        await q.edit_message_text("❌ موجودی کافی نیست.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ بستن", callback_data="cancel")]]))
        return
    pay_id, inv = db.create_payment(uid, p, ptype, plan_key, plan["name"], pay_method="wallet")

    # برای پلن‌های فایلی — فایل assign کن
    if is_file_plan(plan_key):
        file_cfg = db.assign_file_config(plan_key, uid)
        cfg_text = f"[فایل ارسال شد]" if file_cfg else ""
    else:
        cfg_text = db.assign_config(plan_key, uid) or ""

    db.confirm_payment(pay_id, cfg_text)
    db.create_subscription(uid, pay_id, plan_key, plan["name"], plan["size"], p, cfg_text)

    # پرداخت کمیسیون رفرال ۱۰٪ برای پرداخت با موجودی
    buyer = db.get_user(uid)
    if buyer and buyer.get("referred_by") and p > 0:
        commission = int(p * 0.10)
        if commission > 0:
            db.update_balance(buyer["referred_by"], commission)
            try:
                await context.bot.send_message(
                    buyer["referred_by"],
                    f"💰 *کمیسیون رفرال دریافت شد!*\n\n"
                    f"👤 زیرمجموعه شما خرید کرد.\n"
                    f"💵 مبلغ خرید: {fmt(p)}\n"
                    f"🎁 کمیسیون شما (۱۰٪): {fmt(commission)}\n"
                    f"💼 موجودی کیف پول آپدیت شد.",
                    parse_mode="Markdown"
                )
            except Exception: pass

    u = db.get_user(uid)

    if is_file_plan(plan_key) and file_cfg:
        try:
            await _send_file_config_to_user(context.bot, uid, plan, inv, file_cfg)
        except Exception: pass
        msg_to_admin = (
            f"🛍 *خرید با موجودی — فایل ارسال شد*\n\n"
            f"{uinfo(u)}\n\n"
            f"🔖 فاکتور: `{inv}`\n📦 {plan['name']}\n💵 {fmt(p)}\n✅ فایل ارسال شد"
        )
    elif not is_file_plan(plan_key) and cfg_text:
        try:
            await context.bot.send_message(uid,
                f"✅ اشتراک شما با موفقیت ساخته شد.\n"
                f"🔖 فاکتور: {inv}\n"
                f"📦 پلن: {plan['name']}\n\n"
                "🔗 VPN خاموش کنید، وارد لینک بشید و کانفیگ را در برنامه وارد کنید.\n\n"
                "📱 لینک اشتراک:"
            )
            await context.bot.send_message(uid, cfg_text)
        except Exception: pass
        msg_to_admin = (
            f"🛍 *خرید با موجودی — کانفیگ ارسال شد*\n\n"
            f"{uinfo(u)}\n\n"
            f"🔖 فاکتور: `{inv}`\n📦 {plan['name']}\n💵 {fmt(p)}\n✅ کانفیگ ارسال شد"
        )
    else:
        try:
            await context.bot.send_message(uid,
                f"✅ پرداخت شما دریافت شد.\n🔖 فاکتور: `{inv}`\n\nکانفیگ شما به زودی ارسال خواهد شد.",
                parse_mode="Markdown")
        except Exception: pass
        msg_to_admin = (
            f"🛍 *خرید با موجودی — نیاز به ارسال کانفیگ*\n\n"
            f"{uinfo(u)}\n\n"
            f"🔖 فاکتور: `{inv}`\n📦 {plan['name']}\n💵 {fmt(p)}\n⚠️ کانفیگ موجود نبود"
        )

    for aid in all_admins():
        try:
            await context.bot.send_message(aid, msg_to_admin, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 ارسال کانفیگ دستی", callback_data=f"asc_{pay_id}")],
                    [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{uid}")],
                ]))
        except Exception: pass

    await q.edit_message_text(
        f"✅ پرداخت انجام شد.\n🔖 فاکتور: `{inv}`\n{'کانفیگ/فایل در پیام بعدی ارسال شد.' if (cfg_text or (is_file_plan(plan_key) and file_cfg)) else 'کانفیگ شما به زودی ارسال می‌شود.'}",
        parse_mode="Markdown"
    )

async def do_crypto_payment(q, uid, coin, key, context):
    if not flag("crypto_open"):
        await q.edit_message_text("🔴 پرداخت ارزی در حال حاضر غیرفعال است.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ بستن", callback_data="cancel")]]))
        return
    rate = crypto_rate(coin)
    if rate <= 0:
        await q.edit_message_text("⚠️ نرخ این ارز تنظیم نشده است.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ بستن", callback_data="cancel")]]))
        return
    ptype, category, plan_key = _parse_ptype_plankey(key)
    if not plan_key: return
    plan = get_plan(plan_key)
    if not plan: return
    p = price(plan_key)
    crypto_amount = round(p / rate, 4)
    cinfo = config.CRYPTO_WALLETS.get(coin, {})
    wallet_addr = crypto_wallet(coin)

    pay_id, inv = db.create_payment(uid, p, ptype, plan_key, plan["name"], pay_method="crypto", crypto_coin=coin)
    ss(uid, {"w": "crypto_receipt", "pay_id": pay_id, "plan_key": plan_key, "plan_name": plan["name"], "ptype": ptype, "category": category, "coin": coin})

    await q.edit_message_text(
        f"{cinfo.get('emoji','💎')} *پرداخت با {cinfo.get('name', coin)} — Safe-Server*\n\n"
        f"🔖 کد فاکتور: `{inv}`\n"
        f"📦 پلن: {plan['name']}\n"
        f"💵 معادل تومانی: {fmt(p)}\n"
        f"💱 مبلغ ارزی: *{crypto_amount} {cinfo.get('symbol', coin)}*\n\n"
        f"📬 آدرس کیف پول:\n`{wallet_addr}`\n\n"
        f"⚠️ دقیقاً همین مقدار را واریز کنید.\n"
        f"⏰ *{config.PAYMENT_TIMEOUT_MINUTES} دقیقه* فرصت دارید.\n"
        f"پس از واریز، اسکرین‌شات یا هش تراکنش را ارسال کنید.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]])
    )
    asyncio.create_task(pay_timeout(context.bot, pay_id, uid, q.message.chat_id, config.PAYMENT_TIMEOUT_MINUTES * 60))

# ── Send file config to user ──────────────────────────────

async def _send_file_config_to_user(bot, user_id, plan, invoice_code, file_cfg):
    """ارسال فایل کانفیگ (WireGuard/OpenVPN) به کاربر"""
    intro = (
        f"✅ اشتراک شما آماده است!\n"
        f"🔖 فاکتور: {invoice_code}\n"
        f"📦 پلن: {plan['name']}\n\n"
        f"📁 فایل کانفیگ شما:"
    )
    await bot.send_message(user_id, intro)

    caption = file_cfg.get("caption", "") or ""
    file_id = file_cfg["file_id"]
    is_photo = file_cfg.get("is_photo", 0)

    if is_photo:
        await bot.send_photo(user_id, photo=file_id, caption=caption or None)
    else:
        await bot.send_document(user_id, document=file_id, caption=caption or None)

# ── Receipt handlers ──────────────────────────────────────

async def recv_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    pay_id = state.get("pay_id")
    if not pay_id: return

    pay = db.get_payment(pay_id)
    if not pay or pay["status"] in ("cancelled", "confirmed"):
        cs(uid)
        await update.message.reply_text("⚠️ این سفارش منقضی یا لغو شده است.", reply_markup=main_kb(uid))
        return

    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id; is_photo = True
    elif msg.document:
        file_id = msg.document.file_id; is_photo = False
    else:
        await msg.reply_text("لطفاً تصویر رسید را به صورت عکس یا فایل ارسال کنید.")
        return

    db.set_receipt(pay_id, file_id, is_photo)
    plan_key = state.get("plan_key", "")
    plan_name = state.get("plan_name", "")
    u = db.get_user(uid)
    cs(uid)

    await msg.reply_text("✅ رسید شما دریافت شد.\nپس از تایید، کانفیگ برایتان ارسال می‌شود.", reply_markup=main_kb(uid))

    caption = (
        f"🧾 *رسید پرداخت جدید — Safe-Server*\n\n"
        f"{uinfo(u)}\n\n"
        f"🔖 فاکتور: `{pay['invoice_code']}`\n"
        f"📦 پلن: {plan_name}\n"
        f"💵 مبلغ: {fmt(pay['amount'])}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید + ارسال کانفیگ", callback_data=f"ac_{pay_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"ar_{pay_id}")],
        [InlineKeyboardButton("📤 تایید + کانفیگ دستی", callback_data=f"asc_{pay_id}")],
        [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{uid}")],
    ])
    for aid in all_admins():
        try:
            if is_photo:
                await context.bot.send_photo(aid, photo=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
            else:
                await context.bot.send_document(aid, document=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"send to admin {aid} failed: {e}")

async def recv_crypto_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    pay_id = state.get("pay_id")
    if not pay_id: return

    pay = db.get_payment(pay_id)
    if not pay or pay["status"] in ("cancelled", "confirmed"):
        cs(uid)
        await update.message.reply_text("⚠️ این سفارش منقضی یا لغو شده است.", reply_markup=main_kb(uid))
        return

    msg = update.message
    coin = state.get("coin", "")
    cinfo = config.CRYPTO_WALLETS.get(coin, {})

    file_id = None
    is_photo = False
    tx_hash = ""

    if msg.photo:
        file_id = msg.photo[-1].file_id; is_photo = True
    elif msg.document:
        file_id = msg.document.file_id; is_photo = False
    elif msg.text and len(msg.text.strip()) > 10:
        tx_hash = msg.text.strip()
    else:
        await msg.reply_text("لطفاً اسکرین‌شات یا هش تراکنش را ارسال کنید."); return

    if file_id:
        db.set_receipt(pay_id, file_id, is_photo)

    plan_name = state.get("plan_name", "")
    u = db.get_user(uid)
    cs(uid)

    await msg.reply_text(
        f"✅ رسید پرداخت {cinfo.get('name', coin)} دریافت شد.\nپس از تایید، کانفیگ برایتان ارسال می‌شود.",
        reply_markup=main_kb(uid)
    )

    rate = crypto_rate(coin)
    crypto_amount = round(pay['amount'] / rate, 4) if rate > 0 else "?"
    caption = (
        f"💎 *رسید پرداخت ارزی — Safe-Server*\n\n"
        f"{uinfo(u)}\n\n"
        f"🔖 فاکتور: `{pay['invoice_code']}`\n"
        f"📦 پلن: {plan_name}\n"
        f"💵 معادل تومانی: {fmt(pay['amount'])}\n"
        f"{cinfo.get('emoji','💎')} مبلغ ارزی: {crypto_amount} {cinfo.get('symbol', coin)}\n"
        f"🪙 ارز: {cinfo.get('name', coin)}"
    )
    if tx_hash:
        caption += f"\n🔗 تراکنش: {tx_hash}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید + ارسال کانفیگ", callback_data=f"ac_{pay_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"ar_{pay_id}")],
        [InlineKeyboardButton("📤 تایید + کانفیگ دستی", callback_data=f"asc_{pay_id}")],
        [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{uid}")],
    ])
    for aid in all_admins():
        try:
            if file_id:
                if is_photo:
                    await context.bot.send_photo(aid, photo=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
                else:
                    await context.bot.send_document(aid, document=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
            else:
                await context.bot.send_message(aid, caption, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"send crypto receipt to admin {aid} failed: {e}")

# ── Admin Confirm / Reject ─────────────────────────────────

async def admin_confirm(q, pay_id, context):
    if not is_admin(q.from_user.id): return
    pay = db.get_payment(pay_id)
    if not pay:
        try: await q.edit_message_caption("⚠️ پرداخت یافت نشد.")
        except: await q.edit_message_text("⚠️ پرداخت یافت نشد.")
        return

    if pay["purpose"] == "topup":
        db.update_balance(pay["user_id"], pay["amount"])
        if flag("vip_open") and pay["amount"] >= 5000000:
            db.set_vip_balance(pay["user_id"], pay["amount"])
            try:
                await context.bot.send_message(pay["user_id"],
                    f"👑 *تبریک! شما نماینده VIP Safe-Server شدید!*\n\n"
                    f"💰 اعتبار VIP: {fmt(pay['amount'])}\n"
                    f"🏷 ۱۵٪ تخفیف روی تمام خریدها تا اتمام اعتبار VIP",
                    parse_mode="Markdown")
            except Exception: pass
        db.confirm_payment(pay_id)
        try:
            await context.bot.send_message(pay["user_id"],
                f"✅ موجودی کیف پول شما {fmt(pay['amount'])} افزایش یافت.")
        except Exception: pass
        try: await q.edit_message_caption(f"✅ شارژ `{pay['invoice_code']}` تایید شد.", parse_mode="Markdown")
        except: await q.edit_message_text(f"✅ شارژ `{pay['invoice_code']}` تایید شد.", parse_mode="Markdown")
        return

    plan_key = pay["plan_key"]

    # پرداخت کمیسیون رفرال ۱۰٪ به دعوت‌کننده
    if pay["purpose"].startswith("sub") and pay["amount"] > 0:
        buyer = db.get_user(pay["user_id"])
        if buyer and buyer.get("referred_by"):
            commission = int(pay["amount"] * 0.10)
            if commission > 0:
                db.update_balance(buyer["referred_by"], commission)
                try:
                    await context.bot.send_message(
                        buyer["referred_by"],
                        f"💰 *کمیسیون رفرال دریافت شد!*\n\n"
                        f"👤 زیرمجموعه شما خرید کرد.\n"
                        f"💵 مبلغ خرید: {fmt(pay['amount'])}\n"
                        f"🎁 کمیسیون شما (۱۰٪): {fmt(commission)}\n"
                        f"💼 موجودی کیف پول آپدیت شد.",
                        parse_mode="Markdown"
                    )
                except Exception: pass

    # پلن فایلی
    if is_file_plan(plan_key):
        file_cfg = db.assign_file_config(plan_key, pay["user_id"])
        db.confirm_payment(pay_id, "[فایل]" if file_cfg else "")
        db.create_subscription(pay["user_id"], pay_id, plan_key, pay["plan_name"], "", pay["amount"], "[فایل]" if file_cfg else "")
        if flag("vip_open"):
            db.deduct_vip_balance(pay["user_id"], pay["amount"])

        plan = get_plan(plan_key)
        if file_cfg and plan:
            try:
                await _send_file_config_to_user(context.bot, pay["user_id"], plan, pay["invoice_code"], file_cfg)
            except Exception: pass
            result_text = f"✅ تایید شد — فایل ارسال شد\nفاکتور: `{pay['invoice_code']}`"
        else:
            try:
                await context.bot.send_message(pay["user_id"],
                    f"✅ پرداخت تایید شد.\n🔖 فاکتور: `{pay['invoice_code']}`\nفایل شما به زودی ارسال می‌شود.",
                    parse_mode="Markdown")
            except Exception: pass
            result_text = f"✅ تایید شد — ⚠️ فایل موجود نبود\nفاکتور: `{pay['invoice_code']}`"
    else:
        # پلن لینکی (V2ray/Gaming)
        cfg = db.assign_config(plan_key, pay["user_id"])
        db.confirm_payment(pay_id, cfg or "")
        db.create_subscription(pay["user_id"], pay_id, plan_key, pay["plan_name"], "", pay["amount"], cfg or "")
        if flag("vip_open"):
            db.deduct_vip_balance(pay["user_id"], pay["amount"])

        if cfg:
            try:
                await context.bot.send_message(pay["user_id"],
                    f"✅ اشتراک شما با موفقیت ساخته شد.\n"
                    f"🔖 فاکتور: {pay['invoice_code']}\n"
                    f"📦 پلن: {pay['plan_name']}\n\n"
                    "🔗 VPN خاموش کنید، وارد لینک بشید و کانفیگ را در برنامه وارد کنید.\n\n"
                    "📱 لینک اشتراک:"
                )
                await context.bot.send_message(pay["user_id"], cfg)
            except Exception: pass
            result_text = f"✅ تایید شد — کانفیگ ارسال شد\nفاکتور: `{pay['invoice_code']}`"
        else:
            try:
                await context.bot.send_message(pay["user_id"],
                    f"✅ پرداخت تایید شد.\n🔖 فاکتور: `{pay['invoice_code']}`\nکانفیگ شما به زودی ارسال می‌شود.",
                    parse_mode="Markdown")
            except Exception: pass
            result_text = f"✅ تایید شد — ⚠️ کانفیگ موجود نبود\nفاکتور: `{pay['invoice_code']}`"

    try: await q.edit_message_caption(result_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 ارسال دستی", callback_data=f"asc_{pay_id}")]]))
    except: await q.edit_message_text(result_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 ارسال دستی", callback_data=f"asc_{pay_id}")]]))

async def admin_reject(q, pay_id, context):
    if not is_admin(q.from_user.id): return
    pay = db.get_payment(pay_id)
    db.cancel_payment(pay_id)
    if pay:
        try:
            await context.bot.send_message(pay["user_id"],
                f"❌ پرداخت شما (فاکتور `{pay['invoice_code']}`) تایید نشد.\nلطفاً با پشتیبانی تماس بگیرید.",
                parse_mode="Markdown")
        except Exception: pass
    try: await q.edit_message_caption(f"❌ رد شد — فاکتور `{pay['invoice_code']}`", parse_mode="Markdown")
    except: await q.edit_message_text(f"❌ رد شد — فاکتور `{pay['invoice_code']}`", parse_mode="Markdown")

# ── Admin send config manually ────────────────────────────

async def a_recv_send_cfg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    target = state.get("target")
    mode = state.get("mode")
    pay_id = state.get("pay_id")
    text = update.message.text.strip()
    cs(uid)

    if mode == "cfg":
        try:
            pay_info = db.get_payment(pay_id) if pay_id else None
            inv_line = f"🔖 فاکتور: {pay_info['invoice_code']}\n" if pay_info else ""
            plan_line = f"📦 پلن: {pay_info['plan_name']}\n" if pay_info and pay_info.get("plan_name") else ""
            await context.bot.send_message(target,
                f"✅ اشتراک شما با موفقیت ساخته شد.\n"
                f"{inv_line}"
                f"{plan_line}\n"
                "📱 کانفیگ/لینک اشتراک:"
            )
            await context.bot.send_message(target, text)
        except Exception:
            await update.message.reply_text("❌ ارسال ناموفق بود.", reply_markup=main_kb(uid))
            return
        if pay_id:
            db.confirm_payment(pay_id, text)
        await update.message.reply_text("✅ کانفیگ با موفقیت ارسال شد.", reply_markup=main_kb(uid))
    else:
        try:
            await context.bot.send_message(target, f"📨 *پیام از پشتیبانی Safe-Server:*\n\n{text}", parse_mode="Markdown")
            await update.message.reply_text("✅ پیام ارسال شد.", reply_markup=main_kb(uid))
        except Exception:
            await update.message.reply_text("❌ ارسال ناموفق.", reply_markup=main_kb(uid))

# ── Admin: File config upload ──────────────────────────────

async def a_recv_file_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ادمین فایل WireGuard یا OpenVPN آپلود می‌کنه"""
    uid = update.effective_user.id
    state = gs(uid)
    plan_key = state.get("plan_key", "")
    msg = update.message

    caption = msg.caption or msg.text or ""

    if msg.document:
        file_id = msg.document.file_id
        is_photo = False
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        is_photo = True
    else:
        await msg.reply_text("⚠️ فایل یا عکسی دریافت نشد.")
        return

    db.add_file_config(plan_key, file_id, is_photo, caption)
    cnt = db.get_file_config_count(plan_key)
    plan_label = PLAN_LABELS.get(plan_key, plan_key)
    await msg.reply_text(
        f"✅ فایل برای «{plan_label}» ذخیره شد.\n"
        f"{'📎 کپشن: ' + caption if caption else '📎 بدون کپشن'}\n"
        f"📊 موجودی: {cnt} فایل\n\n"
        f"می‌توانید فایل بعدی را بفرستید یا از منوی ادمین خارج شوید.",
        reply_markup=main_kb(uid)
    )
    # state رو نگه دار تا بتونه ادامه بده (batch upload)

# ── Admin Panels ──────────────────────────────────────────

async def show_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("🔧 *پنل مدیریت Safe-Server*", parse_mode="Markdown", reply_markup=admin_kb())

async def a_show_users(q):
    users = db.get_all_users()
    text = f"👥 *کاربران ({len(users)} نفر)*\n\n"
    for u in users[:20]:
        un = f"@{escape_md(u['username'])}" if u.get("username") else "—"
        text += f"• {escape_md(u['full_name'])} | {un} | {fmt(u['balance'])}\n"
    if len(users) > 20: text += f"\n... و {len(users)-20} نفر دیگر"
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())

async def a_show_pays(q):
    pays = db.get_pending_payments()
    if not pays:
        await q.edit_message_text("✅ پرداخت در انتظاری وجود ندارد.", reply_markup=back_kb()); return
    text = f"💰 *در انتظار تایید ({len(pays)})*\n\nیکی را انتخاب کنید:"
    kb = []
    for p in pays:
        method = p.get("pay_method", "card")
        method_label = {"card": "💳", "wallet": "💰", "crypto": "💎"}.get(method, "💳")
        label = f"{method_label} {p['invoice_code']} | {p['full_name']} | {fmt(p['amount'])}"
        kb.append([InlineKeyboardButton(label, callback_data=f"a_pay_detail_{p['id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_configs(q, uid):
    """مدیریت کانفیگ‌های متنی (V2ray / Gaming / رفرال)"""
    summary = db.get_configs_summary()
    counts = {r["plan_key"]: r["available"] for r in summary}
    text_plans = list(config.PLANS.keys()) + list(config.GAMING_PLANS.keys()) + list(config.TEST_PLANS.keys()) + ["100mb_referral"]
    text = "📦 *موجودی کانفیگ‌های متنی (V2ray/Gaming/رفرال)*\n\n"
    for k in text_plans:
        text += f"• {PLAN_LABELS.get(k,k)}: {counts.get(k,0)} عدد\n"
    kb = []
    for k in text_plans:
        kb.append([
            InlineKeyboardButton(f"➕ {PLAN_LABELS.get(k,k)}", callback_data=f"a_addcfg_{k}"),
            InlineKeyboardButton(f"🗑", callback_data=f"a_delcfg_{k}"),
        ])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_file_configs(q, uid):
    """مدیریت فایل‌های WireGuard و OpenVPN"""
    file_plans = list(config.WIREGUARD_PLANS.keys()) + list(config.OPENVPN_PLANS.keys())
    text = "📁 *موجودی فایل‌های WireGuard و OpenVPN*\n\n"
    kb = []
    for k in file_plans:
        cnt = db.get_file_config_count(k)
        text += f"• {PLAN_LABELS.get(k,k)}: {cnt} فایل\n"

    # دکمه‌های آپلود WireGuard
    text += "\n🔐 *WireGuard:*"
    for k in config.WIREGUARD_PLANS.keys():
        kb.append([
            InlineKeyboardButton(f"➕ افزودن کانفیگ WireGuard ({PLAN_LABELS.get(k,k)})", callback_data=f"a_add_file_{k}"),
            InlineKeyboardButton(f"🗑", callback_data=f"a_del_file_{k}"),
        ])

    # دکمه‌های آپلود OpenVPN
    text += "\n\n🛡 *OpenVPN:*"
    for k in config.OPENVPN_PLANS.keys():
        kb.append([
            InlineKeyboardButton(f"➕ افزودن کانفیگ Open VPN ({PLAN_LABELS.get(k,k)})", callback_data=f"a_add_file_{k}"),
            InlineKeyboardButton(f"🗑", callback_data=f"a_del_file_{k}"),
        ])

    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_prices(q, uid):
    """همه پلن‌ها با دکمه تغییر قیمت"""
    all_plans = {
        **config.PLANS,
        **config.GAMING_PLANS,
        **config.OPENVPN_PLANS,
        **config.WIREGUARD_PLANS,
        **config.TEST_PLANS,
    }
    text = "💲 *قیمت‌های فعلی — Safe-Server*\n\n"
    text += "🌐 *V2ray & Gaming:*\n"
    for k in config.PLANS:
        text += f"• {config.PLANS[k]['name']}: {fmt(price(k))}\n"
    text += "\n🎮 *Gaming:*\n"
    for k in config.GAMING_PLANS:
        text += f"• {config.GAMING_PLANS[k]['name']}: {fmt(price(k))}\n"
    text += "\n🛡 *OpenVPN:*\n"
    for k in config.OPENVPN_PLANS:
        text += f"• {config.OPENVPN_PLANS[k]['name']}: {fmt(price(k))}\n"
    text += "\n🔐 *WireGuard:*\n"
    for k in config.WIREGUARD_PLANS:
        text += f"• {config.WIREGUARD_PLANS[k]['name']}: {fmt(price(k))}\n"
    text += "\n🧪 *تست:*\n"
    for k in config.TEST_PLANS:
        text += f"• {config.TEST_PLANS[k]['name']}: {fmt(price(k))}\n"

    kb = []
    for k, plan in all_plans.items():
        kb.append([InlineKeyboardButton(f"✏️ {plan['name']}", callback_data=f"a_setprice_{k}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_crypto(q, uid):
    if not is_admin(uid): return
    text = "💎 *تنظیمات ارز دیجیتال — Safe-Server*\n\n"
    kb = []
    for coin, cinfo in config.CRYPTO_WALLETS.items():
        rate = crypto_rate(coin)
        wallet_addr = crypto_wallet(coin)
        short_addr = wallet_addr[:12] + "..." if len(wallet_addr) > 12 else wallet_addr
        text += (
            f"{cinfo['emoji']} *{cinfo['name']}*\n"
            f"   نرخ: {rate:,} تومان / {cinfo['symbol']}\n"
            f"   آدرس: `{short_addr}`\n\n"
        )
        kb.append([
            InlineKeyboardButton(f"💱 نرخ {cinfo['symbol']}", callback_data=f"a_set_crypto_rate_{coin}"),
            InlineKeyboardButton(f"📬 آدرس {cinfo['symbol']}", callback_data=f"a_set_crypto_wallet_{coin}"),
        ])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_admins(q, uid):
    aids = db.get_admin_ids()
    text = "👤 *ادمین‌ها*\n\n" + "\n".join([f"• `{a}`" for a in aids]) if aids else "👤 *ادمین‌ها*\n\nهیچ ادمینی ثبت نشده"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن", callback_data="a_add_admin"),
         InlineKeyboardButton("➖ حذف", callback_data="a_del_admin")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

async def a_show_vip_panel(q, uid):
    users = db.get_all_users()
    vip_users = [u for u in users if u.get("vip_balance", 0) > 0]
    status = "🟢 فعال" if flag("vip_open") else "🔴 غیرفعال"
    text = (
        f"👑 *پنل نمایندگی VIP — Safe-Server*\n\n"
        f"وضعیت: {status}\n"
        f"🏷 تخفیف: {db.get_vip_discount()}٪\n"
        f"💰 حداقل شارژ VIP: ۵,۰۰۰,۰۰۰ تومان\n\n"
        f"👥 نمایندگان فعال: {len(vip_users)} نفر\n\n"
    )
    for u in vip_users[:10]:
        un = f"@{u['username']}" if u.get("username") else str(u["user_id"])
        text += f"• {escape_md(u['full_name'])} | {un} | اعتبار: {fmt(u['vip_balance'])}\n"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")]]))

async def a_show_channels(q, uid):
    chs = db.get_forced_channels()
    text = "📢 *کانال‌های اجباری — Safe-Server*\n\n"
    if chs:
        for ch in chs:
            text += f"• {ch}\n"
    else:
        text += "هیچ کانالی تنظیم نشده\n"
    kb = []
    for ch in chs:
        kb.append([InlineKeyboardButton(f"🗑 حذف {ch}", callback_data=f"a_del_channel_{ch}")])
    kb.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="a_add_channel")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def a_show_last_purchases(q, uid, context):
    pays = db.get_last_confirmed_purchases(10)
    if not pays:
        await q.edit_message_text("⚠️ هیچ خریدی یافت نشد.", reply_markup=back_kb())
        return
    await q.edit_message_text(
        f"🕐 *۱۰ خرید اخیر تایید\u200cشده*\n\nدر حال بارگذاری...",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    for pay in pays:
        un = f"@{pay['username']}" if pay.get("username") else "ندارد"
        method_label = {"card": "💳 کارت", "wallet": "💰 موجودی", "crypto": f"💎 ارز"}.get(pay.get("pay_method", "card"), "💳")
        caption = (
            f"🧾 *خرید تایید\u200cشده*\n\n"
            f"🆔 آیدی: `{pay['user_id']}`\n"
            f"👤 نام: {escape_md(pay['full_name'])}\n"
            f"🔗 یوزرنیم: {un}\n"
            f"📦 پلن: {pay['plan_name']}\n"
            f"💵 مبلغ: {fmt(pay['amount'])}\n"
            f"💳 روش: {method_label}\n"
            f"🔖 فاکتور: `{pay['invoice_code']}`\n"
            f"🕐 تایید: {pay['confirmed_at'][:16]}"
        )
        try:
            if pay.get("receipt_file_id"):
                if pay.get("is_photo"):
                    await context.bot.send_photo(uid, photo=pay["receipt_file_id"], caption=caption, parse_mode="Markdown")
                else:
                    await context.bot.send_document(uid, document=pay["receipt_file_id"], caption=caption, parse_mode="Markdown")
            else:
                await context.bot.send_message(uid, caption, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"last_purchases send error: {e}")

# ── User Sections ──────────────────────────────────────────

async def show_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await require_member(update, context): return
    if not flag("test_open"):
        await update.message.reply_text("🔴 اکانت تست در حال حاضر غیرفعال است.")
        return
    u = db.get_user(uid)
    if u and u.get("test_used"):
        await update.message.reply_text("⚠️ شما قبلاً از اکانت تست استفاده کرده‌اید.")
        return
    cnt = db.get_config_count("20mb")
    if cnt == 0:
        await update.message.reply_text("⚠️ در حال حاضر اکانت تست موجود نیست.")
        return
    await update.message.reply_text(
        "🧪 *اکانت تست رایگان*\n\n✅ ۲۰ مگابایت حجم رایگان\n⚠️ هر کاربر فقط یک بار مجاز است\n\nآیا می‌خواهید اکانت تست دریافت کنید؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ دریافت اکانت تست", callback_data="get_free_test")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
        ])
    )

async def do_free_test(q, uid, context):
    u = db.get_user(uid)
    if u and u.get("test_used"):
        await q.edit_message_text("⚠️ شما قبلاً از اکانت تست استفاده کرده‌اید.")
        return
    cfg = db.assign_config("20mb", uid)
    if not cfg:
        await q.edit_message_text("⚠️ در حال حاضر اکانت تست موجود نیست.")
        return
    db.mark_test_used(uid)
    try:
        await context.bot.send_message(uid, f"🎁 *اکانت تست رایگان Safe-Server*\n\n📊 حجم: ۲۰ مگابایت", parse_mode="Markdown")
        await context.bot.send_message(uid, cfg)
    except Exception: pass
    await q.edit_message_text("✅ اکانت تست برای شما ارسال شد!")
    u2 = db.get_user(uid)
    for aid in all_admins():
        try:
            await context.bot.send_message(aid,
                f"🧪 *اکانت تست ارسال شد*\n\n{uinfo(u2)}\n\n🔑 {cfg}", parse_mode="Markdown")
        except Exception: pass

async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u: return
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={u['referral_code']}"
    earnings = db.get_referral_earnings(uid)
    await update.message.reply_text(
        f"👥 *زیرمجموعه‌گیری — Safe-Server*\n\n"
        f"🔗 لینک اختصاصی:\n`{link}`\n\n"
        f"👫 تعداد دعوت‌شدگان: {u['referral_count']}\n"
        f"💰 کمیسیون دریافتی: {fmt(earnings)}\n\n"
        f"📌 به ازای هر خرید زیرمجموعه، *۱۰٪* مبلغ فاکتور به کیف پول شما اضافه می‌شود.",
        parse_mode="Markdown"
    )

async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ss(uid, {"w": "support"})
    await update.message.reply_text("🎧 پیام خود را بنویسید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))

async def recv_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = db.get_user(uid)
    msg = update.message.text
    cs(uid)
    await update.message.reply_text("✅ پیام شما ارسال شد.", reply_markup=main_kb(uid))
    for aid in all_admins():
        try:
            await context.bot.send_message(aid,
                f"📩 *پشتیبانی — Safe-Server*\n\n{uinfo(u)}\n\n💬 {escape_md(msg)}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ پاسخ", callback_data=f"am_{uid}")]]))
        except Exception: pass

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        tg = update.effective_user
        u = db.get_or_create_user(uid, tg.username or "", tg.full_name or "")
    username = f"@{escape_md(u['username'])}" if u.get("username") else "ندارد"
    subs = db.get_user_subscriptions(uid)
    sub_text = ""
    for s in subs[:10]:
        if s.get("config_sent"):
            sub_text += f"\n\n📦 {s['plan_name']} — {s['created_at'][:10]}"
        else:
            sub_text += f"\n\n📦 {s['plan_name']} — {s['created_at'][:10]}\n   ⏳ در انتظار ارسال"
    if not sub_text:
        sub_text = "\nاشتراکی یافت نشد."
    await update.message.reply_text(
        f"👤 *حساب من — Safe-Server*\n\n"
        f"📛 نام: {escape_md(u['full_name'])}\n"
        f"🆔 آیدی: `{uid}`\n"
        f"🔗 یوزرنیم: {username}\n"
        f"💰 موجودی: {u['balance']:,} تومان\n"
        f"👥 دعوت‌ها: {u['referral_count']}\n\n"
        f"📋 *اشتراک‌های من:*{sub_text}",
        parse_mode="Markdown"
    )

async def show_my_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subs = db.get_user_subscriptions(uid)
    if not subs:
        await update.message.reply_text("📋 شما هنوز اشتراکی خریداری نکرده‌اید.", reply_markup=main_kb(uid))
        return
    text = "📋 *اشتراک‌های من — Safe-Server*\n\n"
    for s in subs[:15]:
        has_cfg = "✅" if s.get("config_sent") else "⏳ در انتظار ارسال"
        text += f"{has_cfg} {s['plan_name']} — {s['created_at'][:10]}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_kb(uid))

async def show_vip_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await require_member(update, context): return
    if not flag("vip_open"):
        await update.message.reply_text("🔴 سیستم نمایندگی VIP در حال حاضر غیرفعال است.")
        return
    u = db.get_user(uid)
    vip_bal = u.get("vip_balance", 0) if u else 0
    if vip_bal > 0:
        text = (
            f"👑 *نمایندگی VIP — Safe-Server*\n\n"
            f"✅ شما نماینده VIP فعال هستید!\n\n"
            f"💰 اعتبار VIP باقی‌مانده: {fmt(vip_bal)}\n"
            f"🏷 تخفیف فعال: {db.get_vip_discount()}٪ روی تمام خریدها\n\n"
            f"⚠️ تخفیف فقط وقتی اعتبار VIP کافی باشه اعمال میشه."
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        text = (
            f"👑 *نمایندگی VIP — Safe-Server*\n\n"
            f"با یک شارژ بالای ۵,۰۰۰,۰۰۰ تومان نماینده VIP بشید:\n\n"
            f"🏷 *{db.get_vip_discount()}٪ تخفیف* روی تمام خریدها\n"
            f"💎 اعتبار VIP معادل مبلغ شارژ\n\n"
            f"آیا می‌خواهید نماینده VIP شوید؟"
        )
        await update.message.reply_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ بله، VIP می‌شوم", callback_data="vip_join")],
                [InlineKeyboardButton("❌ خیر", callback_data="cancel")],
            ]))

async def start_vip_topup(q, uid, context):
    if not flag("topup_open"):
        await q.edit_message_text("🔴 افزایش موجودی در حال حاضر غیرفعال است.")
        return
    kb = [[InlineKeyboardButton("💳 کارت به کارت", callback_data="topup_card_vip")]]
    for coin, cinfo in config.CRYPTO_WALLETS.items():
        rate = crypto_rate(coin)
        if rate > 0:
            kb.append([InlineKeyboardButton(f"{cinfo['emoji']} {cinfo['name']}", callback_data=f"topup_crypto_vip_{coin}")])
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])
    await q.edit_message_text(
        "👑 *شارژ VIP — Safe-Server*\n\nحداقل مبلغ: ۵,۰۰۰,۰۰۰ تومان\n\nروش پرداخت را انتخاب کنید:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not flag("topup_open"):
        await update.message.reply_text("🔴 افزایش موجودی در حال حاضر غیرفعال است.")
        return
    kb = [[InlineKeyboardButton("💳 کارت به کارت", callback_data="topup_card")]]
    for coin, cinfo in config.CRYPTO_WALLETS.items():
        rate = crypto_rate(coin)
        if rate > 0:
            kb.append([InlineKeyboardButton(f"{cinfo['emoji']} {cinfo['name']}", callback_data=f"topup_crypto_{coin}")])
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])
    await update.message.reply_text(
        "💳 *افزایش موجودی — Safe-Server*\n\nنوع پرداخت را انتخاب کنید:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def recv_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    is_vip = state.get("vip", False)
    try:
        amount = int(update.message.text.replace(",", "").replace("،", "").strip())
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک عدد وارد کنید."); return
    if is_vip and amount < 5000000:
        await update.message.reply_text("⚠️ برای شارژ VIP حداقل ۵,۰۰۰,۰۰۰ تومان وارد کنید."); return
    if not is_vip and amount < 50000:
        await update.message.reply_text("⚠️ حداقل 50,000 تومان."); return
    if amount > 50000000:
        await update.message.reply_text("⚠️ حداکثر 50,000,000 تومان."); return
    pay_id, inv = db.create_payment(uid, amount, "topup", pay_method="card")
    ss(uid, {"w": "topup_receipt", "pay_id": pay_id})
    await update.message.reply_text(
        f"🧾 *فاکتور شارژ کیف پول — Safe-Server*\n\n"
        f"🔖 کد فاکتور: `{inv}`\n"
        f"💵 مبلغ: *{fmt(amount)}*\n\n"
        f"💳 شماره کارت:\n`{card()}`\nبه نام: {cardholder()}\n\n"
        f"⏰ {config.PAYMENT_TIMEOUT_MINUTES} دقیقه فرصت دارید.\nتصویر رسید را ارسال کنید.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    asyncio.create_task(pay_timeout(context.bot, pay_id, uid, update.effective_chat.id, config.PAYMENT_TIMEOUT_MINUTES * 60))

async def recv_topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    pay_id = state.get("pay_id")
    if not pay_id: return
    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id; is_photo = True
    elif msg.document:
        file_id = msg.document.file_id; is_photo = False
    else:
        await msg.reply_text("لطفاً تصویر رسید را ارسال کنید."); return

    db.set_receipt(pay_id, file_id, is_photo)
    pay = db.get_payment(pay_id)
    if not pay or pay["status"] in ("cancelled", "confirmed"):
        cs(uid)
        await update.message.reply_text("⚠️ این سفارش منقضی یا لغو شده است.", reply_markup=main_kb(uid))
        return
    u = db.get_user(uid)
    cs(uid)
    await msg.reply_text("✅ رسید دریافت شد. پس از تایید موجودی افزایش می‌یابد.", reply_markup=main_kb(uid))
    caption = (
        f"💳 *درخواست شارژ کیف پول — Safe-Server*\n\n"
        f"{uinfo(u)}\n\n"
        f"🔖 فاکتور: `{pay['invoice_code']}`\n"
        f"💵 مبلغ: {fmt(pay['amount'])}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=f"ac_{pay_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"ar_{pay_id}")],
        [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{uid}")],
    ])
    for aid in all_admins():
        try:
            if is_photo:
                await context.bot.send_photo(aid, photo=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
            else:
                await context.bot.send_document(aid, document=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"topup receipt to admin {aid}: {e}")

async def recv_topup_crypto_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    coin = state.get("coin")
    try:
        amount = int(update.message.text.replace(",", "").replace("،", "").strip())
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک عدد وارد کنید."); return
    if amount < 50000:
        await update.message.reply_text("⚠️ حداقل 50,000 تومان."); return
    rate = crypto_rate(coin)
    cinfo = config.CRYPTO_WALLETS.get(coin, {})
    wallet_addr = crypto_wallet(coin)
    crypto_amount = round(amount / rate, 4)
    pay_id, inv = db.create_payment(uid, amount, "topup", pay_method="crypto", crypto_coin=coin)
    ss(uid, {"w": "crypto_topup_receipt", "pay_id": pay_id, "coin": coin})
    await update.message.reply_text(
        f"{cinfo.get('emoji','💎')} *فاکتور شارژ با {cinfo.get('name', coin)} — Safe-Server*\n\n"
        f"🔖 کد فاکتور: `{inv}`\n"
        f"💵 مبلغ تومانی: {fmt(amount)}\n"
        f"💱 معادل ارزی: *{crypto_amount} {cinfo.get('symbol', coin)}*\n\n"
        f"📬 آدرس کیف پول:\n`{wallet_addr}`\n\n"
        f"پس از واریز، تصویر رسید یا هش تراکنش را ارسال کنید.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]))
    asyncio.create_task(pay_timeout(context.bot, pay_id, uid, update.effective_chat.id, config.PAYMENT_TIMEOUT_MINUTES * 60))

async def recv_crypto_topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = gs(uid)
    pay_id = state.get("pay_id")
    if not pay_id: return
    pay = db.get_payment(pay_id)
    if not pay or pay["status"] in ("cancelled", "confirmed"):
        cs(uid)
        await update.message.reply_text("⚠️ این سفارش منقضی یا لغو شده است.", reply_markup=main_kb(uid))
        return
    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id; is_photo = True
    elif msg.document:
        file_id = msg.document.file_id; is_photo = False
    else:
        await msg.reply_text("لطفاً تصویر رسید یا هش تراکنش را ارسال کنید."); return
    db.set_receipt(pay_id, file_id, is_photo)
    u = db.get_user(uid)
    cs(uid)
    await msg.reply_text("✅ رسید دریافت شد. پس از تایید موجودی افزایش می‌یابد.", reply_markup=main_kb(uid))
    coin = state.get("coin", "")
    cinfo = config.CRYPTO_WALLETS.get(coin, {})
    caption = (
        f"💎 *درخواست شارژ با ارز — Safe-Server*\n\n"
        f"{uinfo(u)}\n\n"
        f"🔖 فاکتور: `{pay['invoice_code']}`\n"
        f"💵 مبلغ تومانی: {fmt(pay['amount'])}\n"
        f"💱 ارز: {cinfo.get('name', coin)}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=f"ac_{pay_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"ar_{pay_id}")],
        [InlineKeyboardButton("✉️ پیام مستقیم", callback_data=f"am_{uid}")],
    ])
    for aid in all_admins():
        try:
            if is_photo:
                await context.bot.send_photo(aid, photo=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
            else:
                await context.bot.send_document(aid, document=file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"crypto topup receipt to admin {aid}: {e}")

# ── Admin input handlers ──────────────────────────────────

async def a_recv_bal_uid(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        t = db.get_user(tid)
        if not t: await update.message.reply_text("⚠️ کاربر یافت نشد."); return
        ss(uid, {"w": "a_bal_amt", "tid": tid})
        await update.message.reply_text(f"موجودی فعلی: {fmt(t['balance'])}\nمقدار تغییر (مثبت/منفی):")
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_bal_amt(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    tid = state.get("tid")
    try:
        delta = int(update.message.text.strip().replace(",", ""))
        db.update_balance(tid, delta)
        t = db.get_user(tid)
        cs(uid)
        await update.message.reply_text(f"✅ موجودی به‌روز شد: {fmt(t['balance'])}", reply_markup=main_kb(uid))
        try:
            await context.bot.send_message(tid, f"💰 موجودی کیف پول شما تغییر کرد.\nموجودی جدید: {fmt(t['balance'])}")
        except Exception: pass
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_del_cfg_count(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    plan_key = state.get("plan_key")
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            await update.message.reply_text("⚠️ عدد باید مثبت باشد."); return
        deleted = db.delete_unused_configs(plan_key, count)
        cs(uid)
        await update.message.reply_text(
            f"✅ {deleted} کانفیگ از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شد.",
            reply_markup=main_kb(uid)
        )
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_del_file_cfg_count(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    plan_key = state.get("plan_key")
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            await update.message.reply_text("⚠️ عدد باید مثبت باشد."); return
        deleted = db.delete_unused_file_configs(plan_key, count)
        cs(uid)
        await update.message.reply_text(
            f"✅ {deleted} فایل از «{PLAN_LABELS.get(plan_key, plan_key)}» پاک شد.",
            reply_markup=main_kb(uid)
        )
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_price(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    key = state.get("key")
    try:
        p = int(update.message.text.strip().replace(",", ""))
        db.set_setting(f"price_{key}", str(p))
        cs(uid)
        await update.message.reply_text(f"✅ قیمت {PLAN_LABELS.get(key,key)} → {fmt(p)}", reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_configs(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    plan_key = state.get("plan_key", "referral")
    lines = [l.strip() for l in update.message.text.strip().split("\n") if l.strip()]
    if not lines:
        await update.message.reply_text("⚠️ هیچ کانفیگی یافت نشد."); return
    db.add_configs(plan_key, lines)
    cs(uid)
    cnt = db.get_config_count(plan_key)
    await update.message.reply_text(
        f"✅ {len(lines)} کانفیگ برای «{PLAN_LABELS.get(plan_key,plan_key)}» اضافه شد.\n📊 موجودی: {cnt}",
        reply_markup=main_kb(uid))

async def a_recv_crypto_rate(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    coin = state.get("coin")
    try:
        rate = int(update.message.text.strip().replace(",", ""))
        db.set_setting(f"crypto_rate_{coin}", str(rate))
        cs(uid)
        cinfo = config.CRYPTO_WALLETS.get(coin, {})
        await update.message.reply_text(
            f"✅ نرخ {cinfo.get('name', coin)} → {rate:,} تومان / {cinfo.get('symbol', coin)}",
            reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_crypto_wallet(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    coin = state.get("coin")
    addr = update.message.text.strip()
    if len(addr) < 10:
        await update.message.reply_text("⚠️ آدرس معتبر نیست."); return
    db.set_setting(f"crypto_wallet_{coin}", addr)
    cs(uid)
    cinfo = config.CRYPTO_WALLETS.get(coin, {})
    await update.message.reply_text(
        f"✅ آدرس {cinfo.get('name', coin)} به‌روز شد:\n`{addr}`",
        parse_mode="Markdown", reply_markup=main_kb(uid))

async def a_recv_card(update, context):
    uid = update.effective_user.id
    c_num = update.message.text.strip()
    db.set_setting("card_number", c_num)
    cs(uid)
    await update.message.reply_text(f"✅ شماره کارت به‌روز شد:\n`{c_num}`", parse_mode="Markdown", reply_markup=main_kb(uid))

async def a_recv_cardholder(update, context):
    uid = update.effective_user.id
    name = update.message.text.strip()
    db.set_setting("card_holder", name)
    cs(uid)
    await update.message.reply_text(f"✅ نام دارنده کارت به‌روز شد:\n{name}", reply_markup=main_kb(uid))

async def a_recv_broadcast(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()
    cs(uid)
    ids = db.get_all_user_ids()
    await update.message.reply_text(f"📢 ارسال به {len(ids)} کاربر شروع شد.")
    asyncio.create_task(do_broadcast(context.bot, ids, text, uid))

async def do_broadcast(bot, ids, text, admin_id):
    ok = fail = 0
    for i in ids:
        try:
            await bot.send_message(i, f"📢 *پیام مدیریت Safe-Server:*\n\n{text}", parse_mode="Markdown")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.3)
        if ok % 100 == 0 and ok > 0:
            await asyncio.sleep(2)
    try:
        await bot.send_message(admin_id, f"📢 ارسال تموم شد.\n✅ {ok} موفق | ❌ {fail} ناموفق")
    except Exception:
        pass

async def a_recv_add_admin(update, context):
    uid = update.effective_user.id
    try:
        nid = int(update.message.text.strip())
        db.add_admin(nid)
        cs(uid)
        await update.message.reply_text(f"✅ ادمین {nid} اضافه شد.", reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_del_admin(update, context):
    uid = update.effective_user.id
    try:
        rid = int(update.message.text.strip())
        if rid in config.ADMIN_IDS:
            await update.message.reply_text("⚠️ ادمین اصلی قابل حذف نیست."); return
        db.remove_admin(rid)
        cs(uid)
        await update.message.reply_text(f"✅ ادمین {rid} حذف شد.", reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_msg_user_id(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        ss(uid, {"w": "a_msg_user_text", "tid": tid})
        t = db.get_user(tid)
        name = t["full_name"] if t else str(tid)
        await update.message.reply_text(f"✍️ پیام خود را برای کاربر {escape_md(name)} (`{tid}`) بنویسید:", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_msg_user_text(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    tid = state.get("tid")
    text = update.message.text.strip()
    cs(uid)
    try:
        await context.bot.send_message(tid, f"📨 *پیام از پشتیبانی Safe-Server:*\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ پیام با موفقیت ارسال شد.", reply_markup=main_kb(uid))
    except Exception:
        await update.message.reply_text("❌ ارسال ناموفق بود.", reply_markup=main_kb(uid))

async def a_recv_ban_uid(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        if tid in config.ADMIN_IDS or tid in db.get_admin_ids():
            await update.message.reply_text("⚠️ نمی‌توانید ادمین را بن کنید."); return
        db.ban_user(tid)
        cs(uid)
        await update.message.reply_text(f"✅ کاربر `{tid}` بن شد.", parse_mode="Markdown", reply_markup=main_kb(uid))
        try:
            await context.bot.send_message(tid, "⛔️ دسترسی شما به ربات مسدود شده است.")
        except Exception: pass
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_unban_uid(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        db.unban_user(tid)
        cs(uid)
        await update.message.reply_text(f"✅ کاربر `{tid}` از بن خارج شد.", parse_mode="Markdown", reply_markup=main_kb(uid))
        try:
            await context.bot.send_message(tid, "✅ مسدودیت شما از ربات برداشته شد.")
        except Exception: pass
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_user_subs_uid(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        cs(uid)
        subs = db.get_user_subscriptions(tid)
        t = db.get_user(tid)
        name = escape_md(t["full_name"]) if t else str(tid)
        if not subs:
            await update.message.reply_text(f"📋 کاربر `{tid}` هیچ اشتراکی ندارد.", parse_mode="Markdown", reply_markup=main_kb(uid))
            return
        text = f"📋 *اشتراک‌های کاربر {name} (`{tid}`)*\n\n"
        for s in subs:
            has_cfg = "✅" if s.get("config_sent") else "⏳"
            text += f"{has_cfg} {s['plan_name']} — {s['created_at'][:10]}\n"
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

async def a_recv_add_channel(update, context):
    uid = update.effective_user.id
    ch = update.message.text.strip()
    cs(uid)
    if not ch.startswith("@") and not ch.startswith("-"):
        ch = "@" + ch
    db.add_forced_channel(ch)
    await update.message.reply_text(f"✅ کانال {ch} اضافه شد.", reply_markup=main_kb(uid))

async def a_recv_vip_discount(update, context):
    uid = update.effective_user.id
    try:
        val = int(update.message.text.strip())
        if not (1 <= val <= 99):
            await update.message.reply_text("⚠️ عدد باید بین ۱ تا ۹۹ باشد."); return
        db.set_vip_discount(val)
        cs(uid)
        await update.message.reply_text(f"✅ تخفیف VIP به {val}٪ تغییر یافت.", reply_markup=main_kb(uid))
    except ValueError:
        await update.message.reply_text("⚠️ عدد وارد کنید.")

async def a_recv_search_uid(update, context):
    uid = update.effective_user.id
    try:
        tid = int(update.message.text.strip())
        cs(uid)
        t = db.get_user(tid)
        if not t:
            await update.message.reply_text(f"⚠️ کاربری با آیدی `{tid}` یافت نشد.", parse_mode="Markdown", reply_markup=main_kb(uid))
            return
        subs = db.get_user_subscriptions(tid)
        banned = db.is_banned(tid)
        un = f"@{escape_md(t['username'])}" if t.get("username") else "ندارد"
        text = (
            f"🔍 *اطلاعات کاربر*\n\n"
            f"👤 نام: {escape_md(t['full_name'])}\n"
            f"🆔 آیدی: `{tid}`\n"
            f"🔗 یوزرنیم: {un}\n"
            f"💰 موجودی: {fmt(t['balance'])}\n"
            f"👑 اعتبار VIP: {fmt(t.get('vip_balance', 0))}\n"
            f"👥 دعوت‌ها: {t['referral_count']}\n"
            f"🚫 بن: {'بله ❌' if banned else 'خیر ✅'}\n"
            f"📋 تعداد خرید: {len(subs)}\n"
        )
        if subs:
            text += "\n*آخرین اشتراک‌ها:*\n"
            for s in subs[:5]:
                has_cfg = "✅" if s.get("config_sent") else "⏳"
                text += f"{has_cfg} {s['plan_name']} — {s['created_at'][:10]}\n"
        ban_btn = InlineKeyboardButton("✅ رفع بن", callback_data=f"su_unban_{tid}") if banned else InlineKeyboardButton("🚫 بن کن", callback_data=f"su_ban_{tid}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 تغییر موجودی", callback_data=f"su_bal_{tid}"), ban_btn],
            [InlineKeyboardButton("✉️ پیام بفرست", callback_data=f"su_msg_{tid}"),
             InlineKeyboardButton("📋 همه اشتراک‌ها", callback_data=f"su_subs_{tid}")],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="a_back")],
        ])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    except ValueError:
        await update.message.reply_text("⚠️ آیدی باید عدد باشد.")

# ── Commands ──────────────────────────────────────────────

async def cmd_admin(update, context):
    if is_admin(update.effective_user.id):
        await show_admin(update, context)

async def cmd_setbalance(update, context):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("استفاده: /setbalance <uid> <amount>"); return
    try:
        db.set_balance(int(context.args[0]), int(context.args[1]))
        await update.message.reply_text("✅ موجودی تنظیم شد.")
    except ValueError:
        await update.message.reply_text("⚠️ مقادیر نامعتبر.")

# ── Main ──────────────────────────────────────────────────

def main():
    db.init_db()
    for aid in config.ADMIN_IDS:
        db.add_admin(aid)

    # کانال فورس جوین پیش‌فرض
    existing = db.get_forced_channels()
    if not existing:
        db.add_forced_channel("@safeserverr")

    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("setbalance", cmd_setbalance))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_any_message))

    logger.info("Bot Safe-Server started.")
    app.run_polling(
        drop_pending_updates=False,
        allowed_updates=["message", "callback_query", "channel_post", "edited_message"]
    )





async def send_tutorial(q, category, context):
    labels = {"v2ray": "🌐 V2ray", "wireguard": "🔐 WireGuard", "openvpn": "🛡 OpenVPN"}
    label = labels.get(category, category)
    tut = db.get_tutorial(category)
    if not tut:
        await q.edit_message_text(
            f"⚠️ هنوز آموزش {label} آپلود نشده.\nبه زودی اضافه می\u200cشود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="tut_back")]])
        )
        return
    try:
        await q.edit_message_text(f"📹 در حال ارسال آموزش {label}...")
    except Exception:
        pass
    try:
        await context.bot.send_video(
            q.from_user.id,
            video=tut["file_id"],
            caption=tut.get("caption") or f"📚 آموزش {label} — Safe-Server",
        )
    except Exception:
        try:
            await context.bot.send_document(
                q.from_user.id,
                document=tut["file_id"],
                caption=tut.get("caption") or f"📚 آموزش {label} — Safe-Server",
            )
        except Exception as e:
            await context.bot.send_message(q.from_user.id, f"❌ خطا در ارسال: {e}")

async def show_tutorials(update, context):
    if not await require_member(update, context): return
    await update.message.reply_text(
        "📚 *راهنمای استفاده — Safe-Server*\n\nنوع سرویس خود را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 آموزش V2ray", callback_data="tut_v2ray")],
            [InlineKeyboardButton("🔐 آموزش WireGuard", callback_data="tut_wireguard")],
            [InlineKeyboardButton("🛡 آموزش OpenVPN", callback_data="tut_openvpn")],
        ])
    )

async def a_show_sales_report(q, uid, period):
    if not is_admin(uid): return
    labels = {"daily": "📅 امروز", "weekly": "📆 ۷ روز اخیر", "monthly": "🗓 ۳۰ روز اخیر"}
    summary, rows = db.get_sales_report(period)
    total = summary.get("total", 0)
    count = summary.get("count", 0)
    text = f"📊 *گزارش فروش — {labels[period]}*\n\n"
    text += f"✅ تعداد فروش: {count} عدد\n"
    text += f"💰 مجموع درآمد: {fmt(total)}\n\n"
    if rows:
        text += "📦 *جزئیات پلن\u200cها:*\n"
        for r in rows:
            if r.get("plan_name"):
                text += f"• {r['plan_name']}: {r['plan_count']} فروش\n"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 امروز", callback_data="a_sales_daily"),
            InlineKeyboardButton("📆 هفتگی", callback_data="a_sales_weekly"),
            InlineKeyboardButton("🗓 ماهانه", callback_data="a_sales_monthly"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

async def a_recv_tutorial_video(update, context):
    uid = update.effective_user.id
    state = gs(uid)
    category = state.get("category", "")
    msg = update.message
    caption = msg.caption or ""

    if msg.video:
        file_id = msg.video.file_id
    elif msg.document:
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        await msg.reply_text("⚠️ ویدیو یا فایل ارسال کنید.")
        return

    db.set_tutorial(category, file_id, caption)
    cs(uid)
    labels = {"v2ray": "V2ray", "wireguard": "WireGuard", "openvpn": "OpenVPN"}
    await msg.reply_text(
        f"✅ آموزش {labels.get(category, category)} ذخیره شد.",
        reply_markup=main_kb(uid)
    )

async def a_show_tutorials(q, uid):
    if not is_admin(uid): return
    cats = {"v2ray": "🌐 V2ray", "wireguard": "🔐 WireGuard", "openvpn": "🛡 OpenVPN"}
    text = "📚 *مدیریت آموزش\u200cها — Safe-Server*\n\n"
    for cat, label in cats.items():
        tut = db.get_tutorial(cat)
        status = "✅ آپلود شده" if tut else "❌ آپلود نشده"
        text += f"{label}: {status}\n"
    kb = []
    for cat, label in cats.items():
        kb.append([
            InlineKeyboardButton(f"📹 آپلود {label}", callback_data=f"a_set_tutorial_{cat}"),
            InlineKeyboardButton(f"🗑 حذف", callback_data=f"a_del_tutorial_{cat}"),
        ])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="a_back")])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    main()
