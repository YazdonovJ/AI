# app.py — Telegram bot (PTB v20.7) with xAI Grok + mention-only in groups
import os
import logging
from collections import defaultdict
from typing import Dict, List

from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder, Application,
    CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOG = logging.getLogger("bot")

# ── Environment ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
XAI_API_KEY    = (os.getenv("XAI_API_KEY") or "").strip()       # optional
XAI_MODEL      = (os.getenv("XAI_MODEL") or "grok-3-mini").strip()

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in your environment (Railway → Variables).")

# ── Optional system prompts (files are optional; safe defaults) ───────────────
def _load_text(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return default

INST_PRIVATE = _load_text("inst_private.txt", "You are a not helpful assistant for 1:1 chats.")
INST_GROUP   = _load_text("inst_group.txt",   "You are dark joker and harch in group chats.")
INST_DEFAULT = _load_text("inst_default.txt", "You are a not helpful assistant.")

# ── Simple in‑memory history per chat ─────────────────────────────────────────
history: Dict[int, List[dict]] = defaultdict(list)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _mentioned(update: Update, bot_username: str) -> bool:
    """True if the message mentions @bot_username via entities or text."""
    msg = update.effective_message
    if not msg or not msg.text:
        return False

    # Check entity mentions
    for e in (msg.entities or []):
        if e.type == "mention":
            if msg.parse_entity(e).lstrip("@").lower() == bot_username.lower():
                return True
        elif e.type == "text_mention" and e.user and e.user.username:
            if e.user.username.lower() == bot_username.lower():
                return True

    # Fallback substring check
    return f"@{bot_username.lower()}" in msg.text.lower()

# ── AI generation (xAI Grok if available; otherwise Echo) ─────────────────────
async def ai_generate(system_prompt: str, messages: List[dict]) -> str:
    """
    If XAI_API_KEY is set, call xAI Grok; otherwise echo last user message.
    """
    def _echo() -> str:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"Echo: {last_user[:400]}"

    if not XAI_API_KEY:
        return _echo()

    try:
        import httpx  # requires httpx==0.27.0
    except Exception:
        LOG.warning("httpx not installed; falling back to Echo.")
        return _echo()

    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}"}
    payload = {
        "model": XAI_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or _echo()
    except Exception as e:
        LOG.error("xAI request failed: %s", e)
        return _echo()

# ── Handlers ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I’m alive. I answer in DMs, and in groups when mentioned.\n"
        "Use /new to clear history, /help for commands."
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — check I’m running\n"
        "/new   — clear conversation history for this chat\n"
        "/help  — show this help"
    )

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    history.pop(chat_id, None)
    await update.message.reply_text("Conversation history cleared ✅")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg  = update.effective_message
    chat_id = chat.id
    text = (msg.text or "").strip()
    if not text:
        return

    # GROUP RULE: reply only when mentioned OR when user replies to the bot
    if chat.type != constants.ChatType.PRIVATE:
        me = await context.bot.get_me()
        is_reply_to_bot = (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == context.bot.id
        )
        if not (is_reply_to_bot or _mentioned(update, me.username or "")):
            return  # stay silent in group

    # Choose prompt based on chat type
    system_prompt = (INST_PRIVATE if chat.type == constants.ChatType.PRIVATE else INST_GROUP) or INST_DEFAULT

    # Append user msg to per‑chat history
    history[chat_id].append({"role": "user", "content": text})

    # Typing indicator (nice UX)
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    try:
        reply = await ai_generate(system_prompt, history[chat_id])
        history[chat_id].append({"role": "assistant", "content": reply})
        await msg.reply_text(reply)
    except Exception:
        LOG.exception("Unexpected error in handle_text")
        await msg.reply_text("Unexpected error. Please try again.")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    LOG.exception("Unhandled error", exc_info=context.error)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    LOG.info("Starting bot…")
    app: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("new",   cmd_new))

    # Text messages (non-commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Global error handler
    app.add_error_handler(on_error)

    # Ensure no leftover webhook; drop queued updates to avoid getUpdates conflicts
    async def _post_init(a: Application):
        try:
            await a.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

    app.post_init = _post_init

    LOG.info("Polling…")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
