import logging

def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )

    # чтобы Telethon не спамил, но ошибки было видно
    logging.getLogger("telethon").setLevel(logging.WARNING)
