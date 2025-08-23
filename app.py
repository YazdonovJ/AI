# app.py — Minimal, robust Telegram bot (PTB v20.7)
import os
import logging
from collections import defaultdict

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
XAI_API_KEY    = (os.getenv("XAI_API_KEY") or "").strip()   # optional
XAI_MODEL      = (os.getenv("XAI_MODEL") or "grok-3-mini").strip()

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in Railway → Variables (or env).")

# ── Optional system prompts (files are optional; safe defaults) ───────────────
def _load_text(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return default

INST_PRIVATE = _load_text("inst_private.txt", "You are a helpful assistant for 1:1 chats.")
INST_GROUP   = _load_text("inst_group.txt",   "You are concise and polite in group chats.")
INST_DEFAULT = _load_text("inst_default.txt", "You are a helpful assistant.")

# ── Simple in‑memory history per chat ─────────────────────────────────────────
history: dict[int, list[dict]] = defaultdict(list)

# ── (Optional) place to call an LLM later; safe Echo fallback for now ─────────
async def ai_generate(system_prompt: str, messages: list[dict]) -> str:
    """
    Replace this with a real API call if/when you want (e.g., xAI Grok).
    For now it just echoes the user's latest message so the bot never fails.
    """
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    # Example stubbed behavior:
    return f"Echo: {last_user[:400]}"

# ── Handlers ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I’m alive and can chat in DMs and groups.\n"
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
    chat_id = chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    # Choose prompt based on chat type
    if chat.type == constants.ChatType.PRIVATE:
        system_prompt = INST_PRIVATE or INST_DEFAULT
    else:
        system_prompt = INST_GROUP or INST_DEFAULT

    # Append user msg to per‑chat history
    history[chat_id].append({"role": "user", "content": text})

    # Typing indicator (nice UX)
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    try:
        reply = await ai_generate(system_prompt, history[chat_id])
        history[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        LOG.exception("Unexpected error in handle_text")
        await update.message.reply_text("Unexpected error. Please try again.")

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

    # Ensure no leftover webhook; drop queued updates to avoid conflicts
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
