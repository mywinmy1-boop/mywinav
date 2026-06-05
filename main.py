import os
import json
import asyncio
import tempfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from telethon import TelegramClient, events
from telethon.sessions import StringSession


CONFIG_FILE = Path("config.json")

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
DEFAULT_DESTINATION = os.getenv("DESTINATION", "@mywinav2")

CAPTION = """🎰 MYWIN 是你最值得信赖的线上娱乐平台
🎁 RM4,880 新人优惠等你来领取

🇲🇾 MYWIN Malaysia's Most Trusted Online Casino
💰 RM4,880 Welcome Bonus

👉 PLAY NOW () | BACKUP CHANNEL (https://t.me/mywinmain)"""


bot_album_buffer = {}
bot_album_tasks = {}

telethon_album_buffer = {}
telethon_album_tasks = {}


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    data = {
        "destination": DEFAULT_DESTINATION,
        "sources": []
    }
    save_config(data)
    return data


def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clean_tg_link(value):
    value = value.strip()
    value = value.replace("https://t.me/", "@")
    value = value.replace("http://t.me/", "@")
    return value


def is_admin(update: Update):
    user = update.effective_user
    return user and user.id == ADMIN_USER_ID


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Retrieve Message", callback_data="retrieve")],
        [InlineKeyboardButton("🔄 Change Destination Group Link", callback_data="change_dest")],
        [InlineKeyboardButton("➕ Set Source Groups", callback_data="set_sources")],
        [InlineKeyboardButton("📋 Show Current Settings", callback_data="settings")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text(
        "MYWIN Media Forwarder Bot\n\nChoose an option:",
        reply_markup=menu()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_USER_ID:
        await query.edit_message_text("Unauthorized.")
        return

    config = load_config()

    if query.data == "retrieve":
        await query.edit_message_text("Retrieving latest photos/videos from source groups...")
        await retrieve_latest_media()
        await query.message.reply_text("Done.", reply_markup=menu())

    elif query.data == "change_dest":
        context.user_data["mode"] = "change_dest"
        await query.edit_message_text(
            "Send the new destination group/channel link.\n\nExample:\n@mywinav2\nor\nhttps://t.me/mywinav2"
        )

    elif query.data == "set_sources":
        context.user_data["mode"] = "set_sources"
        await query.edit_message_text(
            "Send source group links/usernames.\n\nOne per line or separated by commas."
        )

    elif query.data == "settings":
        sources = "\n".join(config["sources"]) if config["sources"] else "None"
        await query.edit_message_text(
            f"Current Settings\n\nDestination:\n{config['destination']}\n\nSources:\n{sources}",
            reply_markup=menu()
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    mode = context.user_data.get("mode")
    config = load_config()
    text = update.message.text.strip()

    if mode == "change_dest":
        config["destination"] = clean_tg_link(text)
        save_config(config)
        context.user_data["mode"] = None
        await update.message.reply_text("Destination updated.", reply_markup=menu())

    elif mode == "set_sources":
        sources = []
        for item in text.replace(",", "\n").splitlines():
            item = item.strip()
            if item:
                sources.append(clean_tg_link(item))

        config["sources"] = sources
        save_config(config)
        context.user_data["mode"] = None

        await update.message.reply_text(
            f"Source groups updated.\n\nTotal sources: {len(sources)}",
            reply_markup=menu()
        )


async def bot_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    msg = update.message

    if not msg.photo and not msg.video:
        await msg.reply_text("Only photos and videos are supported.")
        return

    if msg.media_group_id:
        key = msg.media_group_id
        bot_album_buffer.setdefault(key, []).append(msg)

        if key not in bot_album_tasks:
            bot_album_tasks[key] = asyncio.create_task(
                process_bot_album_later(key, context)
            )
    else:
        await send_single_bot_media(msg, context)


async def send_single_bot_media(msg, context):
    config = load_config()
    destination = config["destination"]

    try:
        if msg.photo:
            await context.bot.send_photo(
                chat_id=destination,
                photo=msg.photo[-1].file_id,
                caption=CAPTION
            )

        elif msg.video:
            await context.bot.send_video(
                chat_id=destination,
                video=msg.video.file_id,
                caption=CAPTION
            )

        await msg.reply_text("Media copied and sent with MYWIN caption.")

    except Exception as e:
        await msg.reply_text(f"Send failed: {e}")


async def process_bot_album_later(key, context):
    await asyncio.sleep(3)

    messages = bot_album_buffer.pop(key, [])
    bot_album_tasks.pop(key, None)

    if not messages:
        return

    messages = sorted(messages, key=lambda m: m.message_id)
    destination = load_config()["destination"]

    media_group = []

    for index, msg in enumerate(messages[:10]):
        caption = CAPTION if index == 0 else None

        if msg.photo:
            media_group.append(
                InputMediaPhoto(
                    media=msg.photo[-1].file_id,
                    caption=caption
                )
            )

        elif msg.video:
            media_group.append(
                InputMediaVideo(
                    media=msg.video.file_id,
                    caption=caption
                )
            )

    if media_group:
        try:
            await context.bot.send_media_group(
                chat_id=destination,
                media=media_group
            )
            await messages[0].reply_text("Grouped media copied and sent with MYWIN caption.")
        except Exception as e:
            await messages[0].reply_text(f"Grouped send failed: {e}")


telethon_client = TelegramClient(
    StringSession(STRING_SESSION),
    API_ID,
    API_HASH
)


async def send_single_telethon_media(message):
    destination = load_config()["destination"]

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = await message.download_media(file=tmpdir)

        if not file_path:
            return

        await telethon_client.send_file(
            destination,
            file_path,
            caption=CAPTION,
            force_document=False
        )


async def send_telethon_album(messages):
    destination = load_config()["destination"]

    messages = sorted(messages, key=lambda m: m.id)

    with tempfile.TemporaryDirectory() as tmpdir:
        files = []

        for msg in messages[:10]:
            if msg.photo or msg.video:
                file_path = await msg.download_media(file=tmpdir)
                if file_path:
                    files.append(file_path)

        if files:
            await telethon_client.send_file(
                destination,
                files,
                caption=CAPTION,
                force_document=False
            )


async def process_telethon_album_later(key):
    await asyncio.sleep(3)

    messages = telethon_album_buffer.pop(key, [])
    telethon_album_tasks.pop(key, None)

    if messages:
        await send_telethon_album(messages)


@telethon_client.on(events.NewMessage)
async def telethon_new_message_handler(event):
    config = load_config()
    sources = config.get("sources", [])

    if not sources:
        return

    try:
        chat = await event.get_chat()
        username = getattr(chat, "username", None)

        if not username:
            return

        current_chat = f"@{username}"

        if current_chat.lower() not in [s.lower() for s in sources]:
            return

        message = event.message

        if not message.photo and not message.video:
            return

        if message.grouped_id:
            key = f"{current_chat}_{message.grouped_id}"
            telethon_album_buffer.setdefault(key, []).append(message)

            if key not in telethon_album_tasks:
                telethon_album_tasks[key] = asyncio.create_task(
                    process_telethon_album_later(key)
                )
        else:
            await send_single_telethon_media(message)

    except Exception as e:
        print("Telethon forward error:", e)


async def retrieve_latest_media(limit_per_group=20):
    config = load_config()
    sources = config.get("sources", [])

    for source in sources:
        try:
            grouped_messages = {}

            async for message in telethon_client.iter_messages(source, limit=limit_per_group):
                if not message.photo and not message.video:
                    continue

                if message.grouped_id:
                    grouped_messages.setdefault(message.grouped_id, []).append(message)
                else:
                    await send_single_telethon_media(message)

            for album in grouped_messages.values():
                await send_telethon_album(album)

        except Exception as e:
            print(f"Retrieve failed for {source}: {e}")


async def main():
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, bot_media_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    await telethon_client.start()

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    print("MYWIN grouped media forwarder is running.")

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
