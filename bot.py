import pyrogram.errors
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    pyrogram.errors.GroupcallForbidden
import os
import asyncio
from collections import defaultdict, deque
from aiohttp import web


from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")

if not BOT_TOKEN or not API_ID or not API_HASH:
    raise RuntimeError("Set BOT_TOKEN, API_ID and API_HASH environment variables.")

if not SESSION_STRING:
    print("WARNING: SESSION_STRING is empty.")

app = Client(
    "raunak_music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

user_client = None
if SESSION_STRING:
    user_client = Client(
        "raunak_music_user",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        in_memory=True,
    )

call = None
queues = defaultdict(deque)
current = {}

WELCOME = (
    "🎵 **Raunak Yadav × Music Bot**\n\n"
    "Play audio in a Telegram group voice chat.\n\n"
    "• `/play <direct-audio-url>`\n"
    "• `/pause` `/resume` `/skip` `/stop`\n"
    "• `/queue` `/nowplaying`\n"
    "• `/setchannel` `/channel`\n\n"
    "⚠️ Use audio you have permission to stream."
)

async def health(request):
    return web.Response(text="Raunak Yadav Music Bot: OK")

async def start_web():
    webapp = web.Application()
    webapp.router.add_get("/", health)
    runner = web.AppRunner(webapp)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Health server listening on {port}")

async def ensure_vc(chat_id: int):
    if not call:
        raise RuntimeError("SESSION_STRING is not configured.")
    await call.play(chat_id, MediaStream(current[chat_id]["source"]))

async def play_next(chat_id: int):
    if not queues[chat_id]:
        current.pop(chat_id, None)
        return

    item = queues[chat_id].popleft()
    current[chat_id] = item

    try:
        await ensure_vc(chat_id)
    except Exception as e:
        await app.send_message(
            chat_id,
            f"❌ Could not start playback: `{e}`"
        )
        current.pop(chat_id, None)

@app.on_message(filters.command("start") & filters.private)
async def start(_, m):
    buttons = []

    if CHANNEL_USERNAME:
        buttons.append([
            InlineKeyboardButton(
                "📢 Join Channel",
                url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🎵 Commands",
            callback_data="commands"
        )
    ])

    await m.reply_text(
        WELCOME,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex("^commands$"))
async def commands(_, q):
    await q.answer()

    await q.message.edit_text(
        "🎵 **Commands**\n\n"
        "`/play <direct-audio-url>` - add/play audio\n"
        "`/pause` - pause\n"
        "`/resume` - resume\n"
        "`/skip` - next track\n"
        "`/stop` - stop and clear queue\n"
        "`/queue` - show queue\n"
        "`/nowplaying` - current track\n"
        "`/setchannel @username` - channel\n"
        "`/channel` - show channel"
    )

@app.on_message(filters.command("play") & filters.group)
async def play(_, m):
    chat_id = m.chat.id

    parts = m.text.split(maxsplit=1) if m.text else []

    if len(parts) != 2:
        await m.reply_text(
            "Usage: `/play https://example.com/song.mp3`"
        )
        return

    source = parts[1].strip()

    if not source.startswith(("http://", "https://")):
        await m.reply_text(
            "Please provide a direct HTTP(S) audio URL."
        )
        return

    queues[chat_id].append({
        "source": source,
        "title": "Audio",
        "requested_by": (
            m.from_user.mention
            if m.from_user
            else "user"
        )
    })

    if chat_id not in current:
        await play_next(chat_id)
        await m.reply_text("🎵 Starting playback.")
    else:
        await m.reply_text("➕ Added to queue.")

@app.on_message(filters.command("skip") & filters.group)
async def skip(_, m):
    chat_id = m.chat.id

    if not call:
        return await m.reply_text(
            "❌ Configure SESSION_STRING first."
        )

    try:
        await call.leave_call(chat_id)
    except Exception:
        pass

    current.pop(chat_id, None)
    await play_next(chat_id)

    await m.reply_text("⏭️ Skipped.")

@app.on_message(filters.command("stop") & filters.group)
async def stop(_, m):
    chat_id = m.chat.id

    queues[chat_id].clear()
    current.pop(chat_id, None)

    if call:
        try:
            await call.leave_call(chat_id)
        except Exception:
            pass

    await m.reply_text(
        "⏹️ Stopped and queue cleared."
    )

@app.on_message(filters.command("pause") & filters.group)
async def pause(_, m):
    if not call:
        return await m.reply_text(
            "❌ Configure SESSION_STRING first."
        )

    try:
        await call.pause(m.chat.id)
        await m.reply_text("⏸️ Paused.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")

@app.on_message(filters.command("resume") & filters.group)
async def resume(_, m):
    if not call:
        return await m.reply_text(
            "❌ Configure SESSION_STRING first."
        )

    try:
        await call.resume(m.chat.id)
        await m.reply_text("▶️ Resumed.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")

@app.on_message(filters.command("queue") & filters.group)
async def queue_cmd(_, m):
    q = queues[m.chat.id]

    if not q:
        return await m.reply_text(
            "📭 Queue is empty."
        )

    lines = ["📜 **Queue**"]

    for i, item in enumerate(q, 1):
        lines.append(
            f"{i}. {item['title']}"
        )

    await m.reply_text(
        "\n".join(lines)
    )


@app.on_message(filters.command("nowplaying") & filters.group)
async def nowplaying(_, m):
    item = current.get(m.chat.id)

    if not item:
        return await m.reply_text(
            "🎵 Nothing is playing."
        )

    await m.reply_text(
        f"🎶 **Now playing:** {item['title']}\n"
        f"Requested by {item['requested_by']}"
    )


@app.on_message(filters.command("setchannel") & filters.group)
async def setchannel(_, m):
    await m.reply_text(
        "📢 Channel is configured through "
        "the CHANNEL_USERNAME environment variable."
    )


@app.on_message(filters.command("channel"))
async def channel(_, m):
    if not CHANNEL_USERNAME:
        return await m.reply_text(
            "📢 No channel configured yet."
        )

    username = CHANNEL_USERNAME.lstrip("@")

    await m.reply_text(
        f"📢 **Channel:** @{username}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Open Channel",
                    url=f"https://t.me/{username}"
                )
            ]
        ])
    )


async def main():
    global call

    await app.start()

    if user_client:
        await user_client.start()
        call = PyTgCalls(user_client)
        await call.start()

    await start_web()

    print("Raunak Yadav × Music Bot is online.")

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
