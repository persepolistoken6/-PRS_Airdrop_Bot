import os
from dataclasses import dataclass
from urllib.parse import urlsplit

# Existing campaign economics: keep these identical for the bot and website.
REQUIRED_REFERRALS = 3
BASE_REWARD = 2000
EXTRA_REWARD = 5000
DAILY_REWARD = 1000
MAX_TOTAL_TOKENS_LIMIT = 300_000_000
DEFAULT_ADMINS = (6661478622, 84460885)


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
    timezone: str = "Asia/Baghdad"
    login_ttl: int = 300
    session_ttl: int = 28800

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
            bot_token=os.getenv("BOT_TOKEN", ""), bot_username=os.getenv("BOT_USERNAME", "PRS_Airdrop_Bot"),
            channel=os.getenv("CHANNEL_ID", "@persepolisToken6"), base_url=base_url,
            admins=admins, demo=demo, enabled=os.getenv("PORTAL_ENABLED", "0") == "1",
            timezone=os.getenv("PORTAL_TIMEZONE", "Asia/Baghdad"),
        )
