# app.py - Main application file for the Telegram Bot
import os
import logging
from collections import defaultdict
from functools import wraps

# Third-party libraries
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Local imports
from grok_client import GrokClient, GrokError

# ── SETUP ──────────────────────────────────────────────────────────────────────
# Load environment variables from .env file
load_dotenv()

# Basic logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
XAI_API_KEY = os.getenv("XAI_API_KEY")
ALLOWED_USERS = [int(user_id) for user_id in os.getenv("ALLOWED_USERS", "").split(",") if user_id]

if not TELEGRAM_TOKEN or not XAI_API_KEY:
    raise ValueError("TELEGRAM_TOKEN and XAI_API_KEY must be set in the environment.")

# Initialize Grok Client
grok_client = GrokClient(api_key=XAI_API_KEY)

# In-memory conversation history
conversation_history = defaultdict(list)

# ── HELPERS & DECORATORS ───────────────────────────────────────────────────────
def load_instruction(filename: str) -> str:
    """Loads instruction text from a file."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        LOGGER.warning("Instruction file not found: %s", filename)
        return ""

# Load system instructions from files
INST_PRIVATE = load_instruction("inst_private.txt")
INST_GROUP = load_instruction("inst_group.txt")
INST_DEFAULT = load_instruction("inst_default.txt")

def user_is_allowed(func):
    """Decorator to restrict access to allowed users only."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.message.reply_text(" you are not authorized to use this bot.")
            LOGGER.warning("Unauthorized access attempt by user_id: %s", user_id)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ── COMMAND HANDLERS ───────────────────────────────────────────────────────────
@user_is_allowed
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text("Hello! I'm a bot powered by Grok. Talk to me!")

@user_is_allowed
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Start the conversation\n"
        "/new - Clear conversation history\n"
        "/help - Show this help message"
    )

@user_is_allowed
async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /new command to clear conversation history."""
    chat_id = update.effective_chat.id
    if chat_id in conversation_history:
        del conversation_history[chat_id]
        await update.message.reply_text("Conversation history cleared.")
    else:
        await update.message.reply_text("No active conversation to clear.")

# ── MESSAGE HANDLER ────────────────────────────────────────────────────────────
@user_is_allowed
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all non-command text messages."""
    chat_id = update.effective_chat.id
    user_message = update.message.text

    # Determine which system instruction to use
    is_private_chat = update.effective_chat.type == constants.ChatType.PRIVATE
    if is_private_chat:
        system_prompt = INST_PRIVATE or INST_DEFAULT
    else: # Group chat
        system_prompt = INST_GROUP or INST_DEFAULT

    # Add user message to history
    conversation_history[chat_id].append({"role": "user", "content": user_message})

    # Show a "typing..." status to the user
    await context.bot.send_chat_action(
        chat_id=chat_id, action=constants.ChatAction.TYPING
    )

    try:
        # Get response from Grok
        response_text = await grok_client.generate(
            system_prompt=system_prompt,
            messages=conversation_history[chat_id]
        )

        # Add assistant's response to history
        conversation_history[chat_id].append({"role": "assistant", "content": response_text})

        # Send the response back to the user
        await update.message.reply_text(response_text)

    except GrokError as e:
        LOGGER.error("Grok API Error: %s", e)
        await update.message.reply_text(f"Sorry, I encountered an error with the AI model: {e}")
    except Exception as e:
        LOGGER.error("An unexpected error occurred: %s", e, exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later.")


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    """Starts the bot."""
    LOGGER.info("Starting bot...")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("new", new_command))

    # Register message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    LOGGER.info("Bot is polling for updates.")
    app.run_polling()

if __name__ == "__main__":
    main()
