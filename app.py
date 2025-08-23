# app.py — Telegram bot (group-only + mention/reply gating), PTB v20+
import os
import logging
from typing import Optional

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, filters
)

# ── ENV ────────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
XAI_API_KEY    = os.getenv("XAI_API_KEY", "").strip()
XAI_MODEL      = os.getenv("XAI_MODEL", "grok-3-mini").strip()

# DMs policy: "ignore" (default) or "warn"
DM_POLICY      = os.getenv("DM_POLICY", "ignore").strip().lower()  # ignore | warn
# Reply gating inside groups: reply_or_mention | mention | all
REPLY_MODE     = os.getenv("REPLY_MODE", "reply_or_mention").strip().lower()

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
        return
    return wrapper

# ── HELPERS ───────────────────────────────────────────────────────────────────
def _mentioned(bot_username: str, update: Update) -> bool:
    """True if message mentions @bot_username (entity or text_mention)."""
    msg = update.effective_message
    if not msg or not msg.text:
        return False

    # entity-based mention
    for e in (msg.entities or []):
        if e.type == "mention":
            if msg.parse_entity(e).lstrip("@").lower() == bot_username.lower():
                return True
        elif e.type == "text_mention":
            if getattr(e.user, "username", "").lower() == bot_username.lower():
                return True

    # fallback substring check
    return f"@{bot_username.lower()}" in msg.text.lower()

# ── (Optional) LLM call stub ──────────────────────────────────────────────────
async def call_xai(prompt: str) -> str:
    """Replace with real xAI/Grok call if desired."""
    return f"Echo: {prompt[:400]}"

# ── HANDLERS ──────────────────────────────────────────────────────────────────
@group_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello, group! I respond only in groups.\n"
        "Default: I answer when you reply to me or @mention me.\n"
        "Try /help for commands."
    )

@group_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — check bot status\n"
        "/ping — quick health check\n"
        "Talk to me by replying to my message or @mentioning my username."
    )

@group_only
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong ✅")

@group_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not (msg.text or "").strip():
        return

    # ignore other bots / self
    if msg.from_user and msg.from_user.is_bot:
        return

    # decide if we should reply
    should_reply = False
    mode = REPLY_MODE
    me = await context.bot.get_me()
    bot_username = me.username or ""

    if mode == "all":
        should_reply = True
    elif mode == "mention":
        should_reply = _mentioned(bot_username, update)
    else:  # reply_or_mention (default)
        replied_to_bot = (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == context.bot.id
        )
        should_reply = replied_to_bot or _mentioned(bot_username, update)

    if not should_reply:
        return  # stay silent

    text = msg.text.strip()
    reply = await call_xai(text)
    if reply:
        await msg.reply_text(reply)

async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)

# Fires when the bot is added/removed (my_chat_member update)
async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cmu = update.my_chat_member  # ChatMemberUpdated
    try:
        new = cmu.new_chat_member
        if new.status in ("member", "administrator"):
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

    # Membership changes (bot added/removed → my_chat_member)
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Errors
    app.add_error_handler(error_handler)

    # Optional: set bot commands in UI
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

    log.info(f"Bot starting (group-only, REPLY_MODE={REPLY_MODE}, DM_POLICY={DM_POLICY}).")
    app.run_polling()

if __name__ == "__main__":
    main()
