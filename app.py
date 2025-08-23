# app.py — Simple Telegram bot (DMs + groups), PTB v20+
import os
import logging
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Optional Grok client import (safe fallback) ────────────────────────────────
try:
    from grok_client import GrokClient, GrokError  # your existing client
    _GROK_AVAILABLE = True
except Exception:
    _GROK_AVAILABLE = False

    class GrokError(Exception):
        pass

    class GrokClient:  # harmless stub so the bot still runs
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key
        async def generate(self, system_prompt: str, messages: list[dict]) -> str:
            # fallback: just echo last user message
            last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            return f"Echo: {last_user[:400]}"

# ── Setup ─────────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
LOG = logging.getLogger("bot")

TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
XAI_API_KEY    = (os.getenv("XAI_API_KEY") or "").strip()

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in environment or .env")

# Load optional instruction files (gracefully if missing)
def _load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

INST_PRIVATE = _load_text("inst_private.txt")
INST_GROUP   = _load_text("inst_group.txt")
INST_DEFAULT = _load_text("inst_default.txt") or "You are a helpful assistant."

# Init Grok (real or stub)
grok_client = GrokClient(api_key=XAI_API_KEY if XAI_API_KEY else None)

# In‑memory per‑chat history (simple & enough)
history: dict[int, list[dict]] = defaultdict(list)

# ── Handlers ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I’m alive. I can chat in DMs and groups.\n"
        "Use /new to reset history, /help for info."
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — check I’m running\n"
        "/new   — clear conversation history for this chat\n"
        "/help  — show this message"
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

    # Pick system prompt by chat type (DM vs group); all are allowed
    if chat.type == constants.ChatType.PRIVATE:
        system_prompt = INST_PRIVATE or INST_DEFAULT
    else:
        system_prompt = INST_GROUP or INST_DEFAULT

    # Append user message
    history[chat_id].append({"role": "user", "content": text})

    # Typing indicator (nice UX)
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    try:
        reply = await grok_client.generate(system_prompt=system_prompt, messages=history[chat_id])
        history[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except GrokError as e:
        LOG.error("Grok error: %s", e)
        await update.message.reply_text("Sorry, the AI backend had an issue. Try again in a moment.")
    except Exception as e:
        LOG.exception("Unexpected error")
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

    # Make sure we are not in webhook mode & clear pending updates (prevents conflicts)
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
