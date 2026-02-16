from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session: str

    source: str
    dest: str

    last_seen_id: int
    overlap: int
    limit: int | None  # None = без лимита

    tmp_dir: Path
    cleanup: bool
    link_preview: bool
    force_document: bool

    sync_comments: bool
    comments_limit: int | None
    comments_include_author: bool

    log_level: str
    log_file: str | None

    dotenv_path: Path

    @staticmethod
    def load() -> "Config":
        dotenv_path = find_dotenv(usecwd=True)
        if not dotenv_path:
            raise RuntimeError("Не найден .env (положи .env рядом с проектом/скриптом).")

        load_dotenv(dotenv_path, override=True)

        raw_limit = os.getenv("TG_LIMIT", "0").strip()
        lim = int(raw_limit)
        limit = None if lim <= 0 else lim

        raw_comments_limit = os.getenv("TG_COMMENTS_LIMIT", "50").strip()
        c_lim = int(raw_comments_limit)
        comments_limit = None if c_lim <= 0 else c_lim

        return Config(
            api_id=int(os.environ["TG_API_ID"]),
            api_hash=os.environ["TG_API_HASH"],
            session=os.environ["TG_SESSION"],

            source=os.environ["TG_SOURCE"],
            dest=os.environ["TG_DEST"],

            last_seen_id=int(os.getenv("TG_LAST_SEEN_ID", "0")),
            overlap=int(os.getenv("TG_OVERLAP", "50")),
            limit=limit,

            tmp_dir=Path(os.getenv("TG_TMP_DIR", "tmp_media")),
            cleanup=_env_bool("TG_CLEANUP", "1"),
            link_preview=_env_bool("TG_LINK_PREVIEW", "1"),
            force_document=_env_bool("TG_FORCE_DOCUMENT", "0"),

            sync_comments=_env_bool("TG_SYNC_COMMENTS", "0"),
            comments_limit=comments_limit,
            comments_include_author=_env_bool("TG_COMMENTS_INCLUDE_AUTHOR", "1"),

            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "").strip() or None,

            dotenv_path=Path(dotenv_path),
        )
