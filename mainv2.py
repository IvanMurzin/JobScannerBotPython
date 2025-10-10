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
from telethon.utils import get_peer_id

# ==============================
# CONFIG
# ==============================

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE_NUMBER", "")
TARGET_CHANNEL_ID = int(os.getenv("PEER_CHANNEL_ID", "0"))
FORWARD_MODE = os.getenv("FORWARD_MODE", "forward").lower()  # forward | copy
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()
DEBUG = LOG_LEVEL in ("debug", "trace")

users_config = json.loads(os.getenv("USERS_CONFIG", "[]"))

if not (API_ID and API_HASH and PHONE and TARGET_CHANNEL_ID and users_config):
    raise SystemExit("[FATAL] Missing env vars or empty USERS_CONFIG")

client = TelegramClient("job_scanner_session", API_ID, API_HASH)
target_channel = PeerChannel(TARGET_CHANNEL_ID)

# ==============================
# LOGGING
# ==============================

def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _print(level: str, msg: str):
    print(f"[{_ts()}] [{level.upper()}] {msg}")

async def clog(msg: str):
    """Только в консоль (DEBUG)."""
    if DEBUG:
        _print("debug", msg)

async def log(msg: str, level: str = "info", err: Exception | None = None):
    """В консоль всегда; в канал — только INFO/ERROR (кратко)."""
    if level == "error" and err:
        _print(level, f"{msg}\n{traceback.format_exc()}")
    else:
        _print(level, msg)
    if level in ("info", "error"):
        try:
            icon = "❌" if level == "error" else "ℹ️"
            await client.send_message(target_channel, f"{icon} {msg}")
        except Exception:
            pass

async def safe_send(callable_, *args, **kwargs):
    while True:
        try:
            return await callable_(*args, **kwargs)
        except FloodWaitError as e:
            await log(f"FloodWait: жду {e.seconds} сек", "error", e)
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            await log(f"Ошибка при отправке: {e}", "error", e)
            return None

# ==============================
# FOLDER → PEER IDS
# ==============================

async def get_chat_peer_ids_from_folder(folder_name: str) -> list[int]:
    """
    Возвращает список peer id (совместимый с event.chat_id) для папки.
    Критично: используем telethon.utils.get_peer_id, а не raw channel_id.
    """
    peer_ids: list[int] = []
    resp = await client(functions.messages.GetDialogFiltersRequest())
    for f in resp.filters or []:
        # У DialogFilterDefault нет title; пропускаем
        if not hasattr(f, "title"):
            continue
        if (f.title or "").strip().lower() == folder_name.strip().lower():
            peers = (f.include_peers or []) + (f.pinned_peers or [])
            for p in peers:
                try:
                    pid = get_peer_id(p)
                    peer_ids.append(pid)
                except Exception as e:
                    await clog(f"get_peer_id failed for {p}: {e}")
            break
    return peer_ids

# ==============================
# FILTERS
# ==============================

def make_filter(keywords: list[str], exclude: list[str]):
    kw_re = re.compile("|".join(map(re.escape, keywords)), re.I) if keywords else None
    ex_re = re.compile("|".join(map(re.escape, exclude)), re.I) if exclude else None

    def _f(text: str) -> bool:
        if not text:
            return False
        if kw_re and not kw_re.search(text):
            return False
        if ex_re and ex_re.search(text):
            return False
        return True

    return _f

# ==============================
# MAIN
# ==============================

async def main():
    await client.start(PHONE)

    # chat_id (peer id) -> (tag, filter_fn)
    handlers: dict[int, tuple[str, callable]] = {}
    all_peer_ids: list[int] = []

    for user in users_config:
        tag = user["tag"]
        folder = user["folder"]
        keywords = user.get("keywords", [])
        exclude = user.get("exclude", [])
        flt = make_filter(keywords, exclude)

        peer_ids = await get_chat_peer_ids_from_folder(folder)
        await log(f"{tag}: {len(peer_ids)} чатов, ключи={keywords}, исключ={exclude}")

        if not peer_ids:
            await log(f"Папка '{folder}' не найдена или пуста ({tag})", "error")
            continue

        for pid in peer_ids:
            handlers[pid] = (tag, flt)
        all_peer_ids.extend(peer_ids)

    if not handlers:
        await log("Нет ни одного чата для отслеживания. Проверь USERS_CONFIG и названия папок.", "error")
        return

    await clog(f"Итого peers: {len(all_peer_ids)}; пример: {all_peer_ids[:5]}")

    @client.on(events.NewMessage(chats=all_peer_ids))
    async def handler(event):
        try:
            # нормализованный ключ — это уже peer id
            h = handlers.get(event.chat_id)
            if not h:
                await clog(f"Событие из неотслеживаемого chat_id={event.chat_id}, пропуск")
                return

            tag, flt = h

            if event.chat_id == TARGET_CHANNEL_ID:
                await clog("Игнор: сообщение из целевого канала")
                return

            # Берём текст/подпись
            text = event.raw_text or (getattr(event.message, "message", "") or "")
            if not text:
                await clog(f"[{tag}] Пустой текст/подпись, пропуск. chat_id={event.chat_id}")
                return

            if not flt(text):
                await clog(f"[{tag}] Не прошло фильтр. chat_id={event.chat_id}")
                return

            if FORWARD_MODE == "copy":
                chat = await event.get_chat()
                src = getattr(chat, "title", None) or getattr(chat, "username", None) or str(event.chat_id)
                out = f"[{tag}] 📌 {src}\n\n{text}"
                await safe_send(client.send_message, target_channel, out)
                await clog(f"[{tag}] COPY → канал. chat_id={event.chat_id}")
            else:
                await safe_send(client.forward_messages, target_channel, event.message)
                await clog(f"[{tag}] FORWARD → канал. chat_id={event.chat_id}")

            try:
                await client(functions.messages.MarkDialogUnreadRequest(peer=target_channel, unread=True))
            except Exception as e:
                await clog(f"MarkDialogUnreadRequest failed: {e}")

        except Exception as e:
            await log(f"Ошибка в handler: {e}", "error", e)

    await log(f"JobScannerBot запущен. Отслеживаю {len(all_peer_ids)} чатов. LOG_LEVEL={LOG_LEVEL}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
