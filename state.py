from __future__ import annotations
import os
import logging
from dotenv import set_key
from pathlib import Path

log = logging.getLogger("tg_sync.state")

class EnvStateStore:
    def __init__(self, dotenv_path: Path):
        self.dotenv_path = dotenv_path

    def update_last_seen(self, value: int) -> None:
        set_key(str(self.dotenv_path), "TG_LAST_SEEN_ID", str(value))
        os.environ["TG_LAST_SEEN_ID"] = str(value)
        log.info("state: TG_LAST_SEEN_ID=%s (saved to .env)", value)
