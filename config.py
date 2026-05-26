import os

# Bot Token
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8771638420:AAHz3QpNQzThb00brJMiSd4oYITV1OdojuA")

# آیدی ادمین (عددی)
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "2083913926").split(",") if x.strip()]

# شماره کارت برای پرداخت
CARD_NUMBER = os.environ.get("CARD_NUMBER", "0000-0000-0000-0000")
CARD_HOLDER = os.environ.get("CARD_HOLDER", "اسماعیلی")

# آدرس‌های کیف پول ارزی
CRYPTO_WALLETS = {
    "ton": {
        "name": "تون (TON)",
        "symbol": "TON",
        "address": os.environ.get("WALLET_TON", "WALLET_ADDRESS_HERE"),
        "emoji": "💎",
    },
    "trx": {
        "name": "ترون (TRX)",
        "symbol": "TRX",
        "address": os.environ.get("WALLET_TRX", "WALLET_ADDRESS_HERE"),
        "emoji": "🔴",
    },
    "usdt": {
        "name": "تتر (USDT/TON)",
        "symbol": "USDT",
        "address": os.environ.get("WALLET_USDT", "WALLET_ADDRESS_HERE"),
        "emoji": "💵",
    },
}

# زمان انقضای پرداخت (دقیقه)
PAYMENT_TIMEOUT_MINUTES = 20

# پلن‌های V2ray و Gaming (لینک اشتراک)
PLANS = {
    "1gb": {
        "name": "اشتراک ۱ گیگ",
        "size": "۱ گیگابایت",
        "duration": "نامحدود",
        "price": int(os.environ.get("PRICE_1GB", "290000")),
        "type": "v2ray",
    },
    "2gb": {
        "name": "اشتراک ۲ گیگ",
        "size": "۲ گیگابایت",
        "duration": "نامحدود",
        "price": int(os.environ.get("PRICE_2GB", "540000")),
        "type": "v2ray",
    },
    "3gb": {
        "name": "اشتراک ۳ گیگ",
        "size": "۳ گیگابایت",
        "duration": "نامحدود",
        "price": int(os.environ.get("PRICE_3GB", "750000")),
        "type": "v2ray",
    },
    "5gb": {
        "name": "اشتراک ۵ گیگ",
        "size": "۵ گیگابایت",
        "duration": "نامحدود",
        "price": int(os.environ.get("PRICE_5GB", "1150000")),
        "type": "v2ray",
    },
    "10gb": {
        "name": "اشتراک ۱۰ گیگ",
        "size": "۱۰ گیگابایت",
        "duration": "نامحدود",
        "price": int(os.environ.get("PRICE_10GB", "2100000")),
        "type": "v2ray",
    },
}

# پلن‌های OpenVPN (فایل + یوزر/پسورد)
OPENVPN_PLANS = {
    "ovpn_unlimited_1": {
        "name": "OpenVPN نامحدود تک‌کاربر",
        "size": "نامحدود",
        "duration": "۱ ماهه",
        "users": "۱ کاربر",
        "price": int(os.environ.get("PRICE_OVPN_UNLIMITED_1", "500000")),
        "type": "openvpn",
    },
    "ovpn_unlimited_2": {
        "name": "OpenVPN نامحدود دو کاربر",
        "size": "نامحدود",
        "duration": "۱ ماهه",
        "users": "۲ کاربر",
        "price": int(os.environ.get("PRICE_OVPN_UNLIMITED_2", "900000")),
        "type": "openvpn",
    },
    "ovpn_30gb": {
        "name": "OpenVPN حجمی ۳۰ گیگ",
        "size": "۳۰ گیگابایت",
        "duration": "۱ ماهه",
        "users": "—",
        "price": int(os.environ.get("PRICE_OVPN_30GB", "200000")),
        "type": "openvpn",
    },
    "ovpn_50gb": {
        "name": "OpenVPN حجمی ۵۰ گیگ",
        "size": "۵۰ گیگابایت",
        "duration": "۱ ماهه",
        "users": "—",
        "price": int(os.environ.get("PRICE_OVPN_50GB", "300000")),
        "type": "openvpn",
    },
    "ovpn_100gb": {
        "name": "OpenVPN حجمی ۱۰۰ گیگ",
        "size": "۱۰۰ گیگابایت",
        "duration": "۱ ماهه",
        "users": "—",
        "price": int(os.environ.get("PRICE_OVPN_100GB", "600000")),
        "type": "openvpn",
    },
}

# پلن‌های WireGuard (فایل)
WIREGUARD_PLANS = {
    "wg_unlimited_1": {
        "name": "WireGuard نامحدود تک‌کاربر",
        "size": "نامحدود",
        "duration": "۱ ماهه",
        "users": "۱ کاربر",
        "price": int(os.environ.get("PRICE_WG_UNLIMITED_1", "500000")),
        "type": "wireguard",
    },
}

# اکانت تست — رایگان، ۲۰ مگابایت
TEST_PLANS = {
    "20mb": {
        "name": "۲۰ مگابایت تست رایگان",
        "size": "۲۰ مگابایت",
        "price": 0,
        "type": "v2ray",
    },
}

# تعداد دعوت برای دریافت اشتراک رایگان رفرال
REFERRAL_THRESHOLD = 5
# پلن رفرال (۱۰۰ مگ)
REFERRAL_PLAN_KEY = "100mb_referral"
REFERRAL_PLAN_NAME = "۱۰۰ مگابایت رایگان (رفرال)"
REFERRAL_PLAN_SIZE = "۱۰۰ مگابایت"
