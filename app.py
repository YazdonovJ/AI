# app.py — Telegram bot (group-only replies), works with python-telegram-bot v20+
import os
import logging
from typing import Optional

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── ENV ────────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
XAI_API_KEY    = os.getenv("XAI_API_KEY", "").strip()
XAI_MODEL      = os.getenv("XAI_MODEL", "grok-3-mini").strip()

# DMs policy: "ignore" (default) or "warn"
DM_POLICY      = os.getenv("DM_POLICY", "ignore").strip().lower()  # ignore | warn

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in your environment.")

# ── LOGGING ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for n in ("httpx", "httpcore", "telegram", "telegram.ext", "telegram.request"):
    logging.getLogger(n).setLevel(logging.WARNING)
log = logging.getLogger("group-only-bot")

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}

# ── UTIL: group-only decorator ────────────────────────────────────────────────
def group_only(handler_func):
    """Allow handler to run only in group/supergroup. For DMs: ignore or warn."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        ctype = getattr(chat, "type", None)
        if ctype in GROUP_TYPES:
            return await handler_func(update, context)

        # Private (DM) path
        if DM_POLICY == "warn" and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "I only work in group chats. Add me to a group and mention me there. 😊"
                )
            except Exception as e:
                log.debug(f"Failed to send DM warning: {e}")
        # If DM_POLICY == "ignore" → do nothing
        return
    return wrapper

# ── (Optional) LLM call stub ──────────────────────────────────────────────────
# Keep as a stub; plug in your Grok/xAI client here if you want AI replies.
async def call_xai(prompt: str) -> str:
    """
    Replace this stub with your actual xAI/Grok API call.
    Return a short response string for the group message.
    """
    # Example (pseudo):
    # import httpx
    # headers = {"Authorization": f"Bearer {XAI_API_KEY}"}
    # payload = {"model": XAI_MODEL, "messages": [{"role":"user","content":prompt}]}
    # async with httpx.AsyncClient(timeout=30) as client:
    #     r = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload)
    #     r.raise_for_status()
    #     return r.json()["choices"][0]["message"]["content"]
    return f"Echo: {prompt[:400]}"  # safe fallback so the bot is functional

# ── HANDLERS ──────────────────────────────────────────────────────────────────
@group_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello, group! I’m alive and will only respond in groups. 🚀\n"
        "Use /help to see what I can do."
    )

@group_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — check bot status\n"
        "/ping — quick health check\n"
        "Just @mention me or talk in the thread; I’ll reply here (not in DMs)."
    )

@group_only
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong ✅")

@group_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    # If you want to require @mention in large groups, uncomment:
    # if update.message.entities and not any(e.type == "mention" for e in update.message.entities):
    #     return
    reply = await call_xai(text)
    if reply:
        await update.message.reply_text(reply)

async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)

# Optional: react when bot is added to a group
async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = update.my_chat_member.new_chat_member
        if getattr(member, "status", "") in ("member", "administrator"):
            chat = update.effective_chat
            if chat and chat.type in GROUP_TYPES:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="Thanks for adding me! I respond only in this group. Type /help to begin."
                )
    except Exception:
        pass

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("ping",  cmd_ping))

    # Messages (text only)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Membership changes (bot added to group)
    app.add_handler(MessageHandler(filters.StatusUpdate.MY_CHAT_MEMBER, on_my_chat_member))

    # Errors
    app.add_error_handler(error_handler)

    # Optional: set bot commands (shown in Telegram UI)
    async def _post_init(app_: Application):
        try:
            await app_.bot.set_my_commands([
                ("start", "Check bot status (group-only)"),
                ("help",  "Show help"),
                ("ping",  "Health check"),
            ])
        except Exception as e:
            log.warning(f"Failed to set commands: {e}")
    app.post_init = _post_init

    log.info("Bot starting (group-only mode).")
    app.run_polling()

if __name__ == "__main__":
    main()
