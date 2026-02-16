from telethon import TelegramClient
from telethon.sessions import StringSession
from config import Config


def create_client(cfg: Config) -> TelegramClient:
    return TelegramClient(StringSession(cfg.session), cfg.api_id, cfg.api_hash)
