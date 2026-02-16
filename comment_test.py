import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
TG_SESSION = os.environ["TG_SESSION"]
SOURCE = os.environ["TG_SOURCE"]

SCAN_POSTS = 50  # сколько последних постов просканировать

async def main():
    client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
    await client.start()

    channel = await client.get_entity(SOURCE)

    target_post = None
    async for p in client.iter_messages(channel, limit=SCAN_POSTS):
        # replies может быть None, если нет комментариев/не включены
        replies_cnt = getattr(getattr(p, "replies", None), "replies", 0) or 0
        if replies_cnt > 0:
            target_post = p
            print(f"Нашёл пост с комментами: post_id={p.id}, comments={replies_cnt}")
            break

    if not target_post:
        print(f"Не нашёл постов с комментариями в последних {SCAN_POSTS}.")
        print("Либо у канала нет комментариев, либо у тебя нет доступа к discussion-чату.")
        await client.disconnect()
        return

    # Берём 1 комментарий к этому посту
    comment = None
    async for c in client.iter_messages(channel, reply_to=target_post.id, limit=1, reverse=True):
        comment = c
        break

    if not comment:
        print("Комментарии заявлены, но не удалось получить ни одного (возможен доступ/настройки).")
        await client.disconnect()
        return

    sender = await comment.get_sender()  # кто написал
    username = getattr(sender, "username", None)
    first_name = getattr(sender, "first_name", None)
    last_name = getattr(sender, "last_name", None)

    print("---- Первый комментарий ----")
    print("comment_id:", comment.id)
    print("text:", comment.raw_text)  # только текст
    print("from:")
    print("  sender_id:", comment.sender_id)
    print("  username:", username)
    print("  name:", (first_name or "") + (" " + last_name if last_name else ""))

    await client.disconnect()

asyncio.run(main())
