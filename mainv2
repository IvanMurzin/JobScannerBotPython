import asyncio
import os
import re
import json
import traceback
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events, functions
from telethon.errors import FloodWaitError
from telethon.tl.types import PeerChannel

# ==============================
# CONFIG
# ==============================

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE_NUMBER", "")
TARGET_CHANNEL_ID = int(os.getenv("PEER_CHANNEL_ID", "0"))
FORWARD_MODE = os.getenv("FORWARD_MODE", "forward").lower()

users_config = json.loads(os.getenv("USERS_CONFIG", "[]"))

if not (API_ID and API_HASH and PHONE and TARGET_CHANNEL_ID and users_config):
    raise SystemExit("[FATAL] Missing env vars or empty USERS_CONFIG")

client = TelegramClient("job_scanner_session", API_ID, API_HASH)
target_channel = PeerChannel(TARGET_CHANNEL_ID)


# ==============================
# UTILS
# ==============================

async def log(msg: str, level: str = "info", err: Exception = None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level.upper()}] {msg}"
    print(line)
    if level in ("info", "error"):
        try:
            await client.send_message(target_channel, f"{'❌' if level=='error' else 'ℹ️'} {msg}")
        except Exception:
            pass


async def safe_send(func, *args, **kwargs):
    while True:
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            await log(f"FloodWait: жду {e.seconds} сек", "error", e)
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            await log(f"Ошибка при отправке: {e}", "error", e)
            return None


async def get_chat_ids_from_folder(folder_name: str) -> list[int]:
    chat_ids = []
    resp = await client(functions.messages.GetDialogFiltersRequest())
    for f in resp.filters or []:
        if f.title.lower() == folder_name.lower():
            peers = (f.include_peers or []) + (f.pinned_peers or [])
            for p in peers:
                pd = p.to_dict()
                cid = pd.get("chat_id", pd.get("channel_id"))
                if cid:
                    chat_ids.append(int(cid))
            break
    return chat_ids


# ==============================
# FILTER
# ==============================

def make_filter(keywords, exclude):
    keyword_re = re.compile("|".join(map(re.escape, keywords)), re.I) if keywords else None
    exclude_re = re.compile("|".join(map(re.escape, exclude)), re.I) if exclude else None

    def _filter(text: str) -> bool:
        if not text:
            return False
        if keyword_re and not keyword_re.search(text):
            return False
        if exclude_re and exclude_re.search(text):
            return False
        return True

    return _filter


# ==============================
# MAIN
# ==============================

async def main():
    await client.start(PHONE)

    # Словарь: chat_id -> user_cfg
    handlers = {}

    for user in users_config:
        tag = user["tag"]
        folder = user["folder"]
        keywords = user.get("keywords", [])
        exclude = user.get("exclude", [])
        flt = make_filter(keywords, exclude)

        chat_ids = await get_chat_ids_from_folder(folder)
        if not chat_ids:
            await log(f"Папка '{folder}' для {tag} пуста", "error")
            continue

        await log(f"{tag}: {len(chat_ids)} чатов, ключи={keywords}, исключ={exclude}")

        for cid in chat_ids:
            handlers[cid] = (tag, flt)

    @client.on(events.NewMessage(chats=list(handlers.keys())))
    async def handler(event):
        tag, flt = handlers.get(event.chat_id, (None, None))
        if not tag:
            return
        if event.chat_id == TARGET_CHANNEL_ID:
            return

        text = event.raw_text or ""
        if not flt(text):
            return

        try:
            if FORWARD_MODE == "copy":
                src = (await event.get_chat()).title or str(event.chat_id)
                out = f"[{tag}] 📌 {src}\n\n{text}"
                await safe_send(client.send_message, target_channel, out)
            else:
                await safe_send(client.forward_messages, target_channel, event.message)

            await client(functions.messages.MarkDialogUnreadRequest(peer=target_channel, unread=True))
        except Exception as e:
            await log(f"Ошибка при обработке ({tag}): {e}", "error", e)

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
