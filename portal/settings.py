import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Existing campaign economics: keep these identical for the bot and website.
REQUIRED_REFERRALS = 3
# Each user's first referrals (in the order they were credited) stay counted even if
# they later leave the channel. Leaves are deducted only from referral 4 onward.
PROTECTED_REFERRALS = 3
BASE_REWARD = 2000
EXTRA_REWARD = 5000
DAILY_REWARD = 1000
MAX_TOTAL_TOKENS_LIMIT = 300_000_000
DEFAULT_ADMINS = (6661478622, 84460885)
CAMPAIGN_TIMEZONE = "Asia/Tehran"
MINING_SECONDS = 8 * 3600
# Registration captcha: wrong answers allowed before a temporary lock.
CAPTCHA_MAX_ATTEMPTS = 5
CAPTCHA_LOCK_SECONDS = 600
MINING_DEFAULT_BUDGET = 135_000_000
_TME = re.compile(r"^(?:https?://)?(?:www\.)?t(?:elegram)?\.me/", re.I)


def clean_bot_username(value, default="PRS_Airdrop_Bot"):
    """BOT_USERNAME as Telegram links need it: no @ and no t.me/ prefix."""
    value = _TME.sub("", (value or "").strip()).strip().lstrip("@").strip().split("?")[0].strip("/")
    return value or default


def clean_channel(value, default="@persepolisToken6"):
    """CHANNEL_ID as Telegram's API needs it: @name, or a numeric chat ID such as -100..."""
    value = _TME.sub("", (value or "").strip()).strip().split("?")[0].strip("/")
    if re.fullmatch(r"-?[0-9]+", value):
        return value
    value = value.lstrip("@").strip()
    return "@" + value if value else default


TIERS = (
    {"id": "bronze", "name": "برنز", "name_en": "Bronze", "referrals": 0, "balance": 0, "reward": 500},
    {"id": "silver", "name": "نقره", "name_en": "Silver", "referrals": 3, "balance": 10_000, "reward": 550},
    {"id": "gold", "name": "طلا", "name_en": "Gold", "referrals": 10, "balance": 50_000, "reward": 600},
    {"id": "platinum", "name": "پلاتینیوم", "name_en": "Platinum", "referrals": 25, "balance": 150_000, "reward": 675},
    {"id": "diamond", "name": "الماس", "name_en": "Diamond", "referrals": 50, "balance": 500_000, "reward": 750},
)


@dataclass(frozen=True)
class Settings:
    mongo_url: str = ""
    database: str = "persepolis_db"
    bot_token: str = ""
    bot_username: str = "PRS_Airdrop_Bot"
    channel: str = "@persepolisToken6"
    base_url: str = ""
    admins: tuple = DEFAULT_ADMINS
    demo: bool = False
    enabled: bool = False
    timezone: str = CAMPAIGN_TIMEZONE
    login_ttl: int = 300
    session_ttl: int = 86400
    bsc_rpc_url: str = ""
    payout_wallet_address: str = ""
    prs_token_address: str = "0x1f67eB3e7487b7D70C69264Ab907Dd074ef1d39f"
    prs_token_decimals: int = 18

    @classmethod
    def from_env(cls):
        demo = os.getenv("PORTAL_DEMO", "0") == "1"
        base_url = os.getenv("WEB_BASE_URL", "").strip().rstrip("/")
        if base_url:
            parsed = urlsplit(base_url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                raise ValueError("WEB_BASE_URL must be an origin without a path, query or credentials")
            if parsed.scheme != "https" and not (demo and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
                raise ValueError("WEB_BASE_URL must use HTTPS outside a local demo")
            if not parsed.hostname:
                raise ValueError("WEB_BASE_URL requires a hostname")
        if demo and (os.getenv("BOT_TOKEN") or os.getenv("MONGO_URL")):
            raise ValueError("Demo mode must never receive production credentials")
        admins = tuple(int(x.strip()) for x in os.getenv("PORTAL_ADMIN_IDS", ",".join(map(str, DEFAULT_ADMINS))).split(",") if x.strip())
        return cls(
            mongo_url=os.getenv("MONGO_URL", ""), database=os.getenv("MONGO_DB", "persepolis_db"),
            bot_token=os.getenv("BOT_TOKEN", "").strip(), bot_username=clean_bot_username(os.getenv("BOT_USERNAME")),
            channel=clean_channel(os.getenv("CHANNEL_ID")), base_url=base_url,
            admins=admins, demo=demo, enabled=os.getenv("PORTAL_ENABLED", "0") == "1",
            # Phase two uses Tehran even when an older deployment still has
            # PORTAL_TIMEZONE=Asia/Baghdad configured.
            timezone=CAMPAIGN_TIMEZONE,
            bsc_rpc_url=os.getenv("BSC_RPC_URL", "").strip(),
            payout_wallet_address=os.getenv("PAYOUT_WALLET_ADDRESS", "").strip(),
            prs_token_address=os.getenv("PRS_TOKEN_ADDRESS", "0x1f67eB3e7487b7D70C69264Ab907Dd074ef1d39f").strip(),
            prs_token_decimals=int(os.getenv("PRS_TOKEN_DECIMALS", "18")),
        )
