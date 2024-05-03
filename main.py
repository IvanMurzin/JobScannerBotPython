import os

from telethon import TelegramClient, events, functions
from telethon.tl.types import PeerChannel, PeerUser
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
phone_number = os.getenv('PHONE_NUMBER')
folder_name = os.getenv('FOLDER_NAME')
peer_user_id = int(os.getenv('PEER_USER_ID'))
peer_channel_id = int(os.getenv('PEER_CHANNEL_ID'))

peer_user = PeerUser(peer_user_id)
peer_channel = PeerChannel(peer_channel_id)

client = TelegramClient('my_session', api_id, api_hash)


async def get_chats_from_folder(folder):
    chat_ids = []
    request = await client(functions.messages.GetDialogFiltersRequest())
    for dialog_filter in request.filters:
        dialog_filter_dict = dialog_filter.to_dict()
        if dialog_filter_dict.get("title", "").lower() == folder.lower():
            for peer in dialog_filter.include_peers + dialog_filter.pinned_peers:
                peer_dict = peer.to_dict()
                chat_id = peer_dict.get("chat_id", peer_dict.get("channel_id", ""))
                if chat_id != "":
                    chat_ids.append(chat_id)
            break
    return chat_ids


@client.on(events.NewMessage())
async def handler(event):
    try:
        event_id = event.message.chat.id
        if event_id == peer_channel.channel_id:
            return
        if event_id in tracked_chat_ids:
            message_text = event.message.text
            keywords = ['mobile', 'android', 'flutter']
            if any(keyword in message_text.lower() for keyword in keywords):
                await client.forward_messages(peer_channel, event.message)
                await client(functions.messages.MarkDialogUnreadRequest(
                    peer=peer_channel,
                    unread=True
                ))
    except Exception as e:
        print(f"Handle error: {e}")


async def main():
    await client.start(phone_number)
    global tracked_chat_ids
    tracked_chat_ids = await get_chats_from_folder(folder_name)
    for chat_id in tracked_chat_ids:
        try:
            chat_entity = await client.get_entity(PeerChannel(chat_id))
            print(f"Name: {chat_entity.title}")
        except Exception as e:
            print(f"Failed to get chat name for ID {chat_id}: {e}")
    await client.run_until_disconnected()


client.loop.run_until_complete(main())
