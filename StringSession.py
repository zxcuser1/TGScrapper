import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
PHONE = os.environ["TG_PHONE"]  # в формате +7..., +46..., и т.д.
TWO_FA = os.getenv("TG_2FA_PASSWORD") #если нет то убираем


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    await client.send_code_request(PHONE)
    code = input("Code from Telegram: ").strip()

    try:
        await client.sign_in(PHONE, code)
    except SessionPasswordNeededError:
        if not TWO_FA:
            pwd = input("2FA password: ")
        else:
            pwd = TWO_FA
        await client.sign_in(password=pwd)

    print("\nTG_SESSION=" + client.session.save() + "\n")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
