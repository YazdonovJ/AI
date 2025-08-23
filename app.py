import os, io, time, logging, random
from collections import defaultdict, deque
from PIL import Image

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

import google.generativeai as genai

# ================== BASIC BOT INFO ==================
BOT_NAME = "James"
BOT_SURNAME = "Makonian"
BOT_LORD = "Jamoliddin Yazdonov"  # shown as "my lord" in public texts
BOT_ROLE = "SAT tutor at SAT Makon"
BOT_TRAITS = "smart, humorous, supportive, and witty"

# ================== SYSTEM INSTRUCTIONS LOADING ==================
DEFAULT_SYSTEM_PERSONA = (
    f"You are {BOT_NAME} {BOT_SURNAME}, an AI assistant and {BOT_ROLE}. "
    f"Your lord is {BOT_LORD} (SAT teacher). "
    f"You are {BOT_TRAITS}. "
    "Be clear, friendly, a bit funny, but focused on SAT learning. "
    "Explain step-by-step in simple English and end with a 1-line takeaway. "
    "In groups: only respond if addressed (name/@mention/reply/command); otherwise output SKIP."
)

SYSTEM_FILE = os.getenv("SYSTEM_FILE", "system_instructions.txt")
PRIVATE_PROMPT_FILES = os.getenv("PRIVATE_PROMPT_FILES", "inst_private.txt")
GROUP_PROMPT_FILES   = os.getenv("GROUP_PROMPT_FILES",   "inst_group.txt")
VISION_PROMPT_FILES  = os.getenv("VISION_PROMPT_FILES",  "inst_vision.txt")

def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def load_base_persona() -> str:
    env_persona = os.getenv("SYSTEM_PROMPT")
    if env_persona and env_persona.strip():
        return env_persona.strip()
    file_persona = _read_file(SYSTEM_FILE)
    return file_persona if file_persona else DEFAULT_SYSTEM_PERSONA

def load_stack(csv_names: str) -> str:
    if not csv_names:
        return ""
    pieces = []
    for name in [x.strip() for x in csv_names.split(",") if x.strip()]:
        t = _read_file(name)
        if t:
            pieces.append(t)
    return ("\n\n".join(pieces)).strip()

def persona_for(update: Update, is_photo: bool) -> str:
    base = load_base_persona()
    chat_type = update.effective_chat.type if update.effective_chat else ""
    extra = load_stack(GROUP_PROMPT_FILES if chat_type in ("group", "supergroup") else PRIVATE_PROMPT_FILES)
    vision = load_stack(VISION_PROMPT_FILES) if is_photo else ""
    parts = [p for p in [base, extra, vision] if p]
    return "\n\n".join(parts) if parts else base

# ================== MODES & LIMITS ==================
MODES = {
    "tutor": "MODE: Tutor — direct, structured explanations.",
    "socratic": "MODE: Socratic — ask guiding questions first, then confirm the answer.",
    "drill": "MODE: Drill — short answers with one quick tip.",
}
MAX_HISTORY = 8
COOLDOWN_SEC = 3.0
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ================== ENV (Railway Variables) ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise SystemExit("Please set TELEGRAM_TOKEN and GEMINI_API_KEY as environment variables.")

# ================== Gemini setup ==================
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

# ================== Logging ==================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("james-bot")

# ================== User state ==================
class UState:
    def __init__(self):
        self.mode = "tutor"
        self.history = deque(maxlen=MAX_HISTORY)  # list[(role, text)]
        self.last_ts = 0.0

USER = defaultdict(UState)

# ================== Helpers ==================
def build_prompt(user_id: int, system_text: str, user_msg: str) -> list:
    s = USER[user_id]
    parts = [
        {"text": system_text},
        {"text": MODES.get(s.mode, MODES["tutor"])},
        {"text": "Keep answers under ~300 words unless the user sends a long passage/problem."},
    ]
    for role, text in list(s.history):
        parts.append({"text": f"{role}: {text}"})
    parts.append({"text": f"Student: {user_msg}"})
    parts.append({"text": f"{BOT_NAME}:"})
    return parts

async def ask(parts: list, temp: float = 0.6) -> str:
    try:
        resp = model.generate_content(parts, generation_config={"temperature": temp})
        return (resp.text or "").strip() or "I couldn’t form a reply—try again?"
    except Exception as e:
        log.exception("Gemini error: %s", e)
        return "I couldn’t form a reply—try again?"

async def ask_banter(system_text: str, user_msg: str) -> str:
    """Ask for a tiny witty reply (2–12 words). Never SKIP."""
    parts = [
        {"text": system_text},
        {"text": ("You were addressed casually in a group. "
                  "Reply in 2–12 words, witty and friendly. "
                  "Acknowledge flavors or feelings if mentioned. "
                  "Do NOT output SKIP.")},
        {"text": f"Student: {user_msg}"},
        {"text": f"{BOT_NAME}:"},
    ]
    return await ask(parts, temp=0.9)

def cooled(user_id: int) -> bool:
    now = time.time()
    if now - USER[user_id].last_ts < COOLDOWN_SEC:
        return False
    USER[user_id].last_ts = now
    return True

async def addressed_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_type = update.effective_chat.type if update.effective_chat else ""
    if chat_type not in ("group", "supergroup"):
        return True
    text = (getattr(update.message, "text", None) or
            getattr(update.message, "caption", None) or "")
    text_l = text.lower()
    me = await context.bot.get_me()
    bot_username = me.username.lower() if me.username else ""
    mentioned = ("james" in text_l) or (f"@{bot_username}" in text_l)
    replied_to_bot = (
        update.message.reply_to_message
        and update.message.reply_to_message.from_user
        and update.message.reply_to_message.from_user.id == context.bot.id
    )
    return bool(mentioned or replied_to_bot)

def is_skip(s: str) -> bool:
    if not s:
        return False
    t = s.strip().upper()
    return t == "SKIP" or t.startswith("SKIP")

def brief_fallback(username: str, name: str, photo: bool = False) -> str:
    my_lord = (username == "yazdon_ov") or ("yazdonov" in (name or "").lower())
    picks_text = [
        "Deal. Double scoop?",
        "Let’s roll. Cone or cup?",
        "Count me in. What flavor?",
        "Sweet idea. Study after?",
        "I’m in. Chocolate first?",
    ]
    picks_photo = [
        "Looks good. Study after dessert?",
        "Yum. Save me a scoop?",
        "Classy choice. Back to SAT soon?",
    ]
    base = random.choice(picks_photo if photo else picks_text)
    return base.replace("?", ", my lord?") if my_lord else base

# ================== Commands ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER[update.effective_user.id]
    text = (
        f"Hey {update.effective_user.first_name}! I’m {BOT_NAME} {BOT_SURNAME}, your SAT helper from SAT Makon.\n"
        f"My lord, {BOT_LORD}, keeps us aiming high.\n\n"
        "Try:\n"
        "• /mode tutor | socratic | drill\n"
        "• /vocab science\n"
        "• /reading\n"
        "Or just send a question or a photo of a problem."
    )
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/mode tutor|socratic|drill — choose style\n"
        "/vocab [topic] — 10 SAT words (def, example, synonyms)\n"
        "/reading — short passage + 3 questions + answers\n"
        "/reset — clear chat memory\n"
        "/about — who is James?"
    )

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{BOT_NAME} {BOT_SURNAME}: {BOT_ROLE}.\n"
        f"My lord: {BOT_LORD}.\n"
        "Mission: make SAT less scary—with jokes."
    )

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER[update.effective_user.id] = UState()
    await update.message.reply_text("History cleared. Fresh start!")

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = (context.args or ["tutor"])
    choice = args[0].lower()
    if choice not in MODES:
        return await update.message.reply_text("Use: /mode tutor | socratic | drill")
    USER[update.effective_user.id].mode = choice
    await update.message.reply_text(f"Mode set to: {choice}")

async def vocab_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) if context.args else "mixed SAT"
    system_text = persona_for(update, is_photo=False)
    prompt = [
        {"text": system_text},
        {"text": MODES["drill"]},
        {"text": f"Create 10 SAT-level vocabulary words about '{topic}'. "
                 f"For each: word — concise definition — 1 simple example — 2–3 synonyms. Number 1–10."},
        {"text": f"{BOT_NAME}:"},
    ]
    txt = await ask(prompt, temp=0.7)
    if not is_skip(txt):
        await update.message.reply_text(txt)

async def reading_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    system_text = persona_for(update, is_photo=False)
    prompt = [
        {"text": system_text},
        {"text": MODES["tutor"]},
        {"text": ("Generate a short SAT-style reading passage (120–160 words) with 3 questions: "
                  "Q1 main idea, Q2 inference, Q3 function of a sentence. "
                  "Provide correct answers at the end (A/B/C/D).")},
        {"text": f"{BOT_NAME}:"},
    ]
    txt = await ask(prompt, temp=0.8)
    if not is_skip(txt):
        await update.message.reply_text(txt)

# ================== Message & Photo ==================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not cooled(uid):
        return await update.message.reply_text("One moment ⏳")

    if not await addressed_in_group(update, context):
        return

    username = (update.effective_user.username or "").lower()
    name = (getattr(update.effective_user, "full_name", None) or update.effective_user.first_name or "").strip()

    msg = update.message.text or ""
    USER[uid].history.append(("Student", msg))

    system_text = persona_for(update, is_photo=False)
    msg_for_prompt = f"[username=@{username}] [name={name}] {msg}".strip()
    parts = build_prompt(uid, system_text, msg_for_prompt)
    reply = await ask(parts)

    if is_skip(reply):
        # second try: short witty banter via dedicated prompt
        banter = await ask_banter(system_text, msg_for_prompt)
        if not is_skip(banter) and "couldn’t form a reply" not in banter:
            return await update.message.reply_text(banter)
        # final fallback (no model)
        return await update.message.reply_text(brief_fallback(username, name))

    USER[uid].history.append((BOT_NAME, reply))
    await update.message.reply_text(reply)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not cooled(uid):
        return await update.message.reply_text("One moment ⏳")

    if not await addressed_in_group(update, context):
        return

    username = (update.effective_user.username or "").lower()
    name = (getattr(update.effective_user, "full_name", None) or update.effective_user.first_name or "").strip()
    caption = (update.message.caption or "").strip()
    caption_for_prompt = f"[username=@{username}] [name={name}] {caption}".strip()

    file = await context.bot.get_file(update.message.photo[-1].file_id)
    b = await file.download_as_bytearray()
    img = Image.open(io.BytesIO(b))

    system_text = persona_for(update, is_photo=True)
    parts = [
        {"text": system_text},
        {"text": MODES.get(USER[uid].mode, MODES["tutor"])},
        {"text": ("Analyze this SAT question image. If MCQ, pick the best option and explain briefly. "
                  "If reading, summarize first, then answer likely question types succinctly.")},
        {"text": caption_for_prompt},
        img,
        {"text": f"{BOT_NAME}:"},
    ]
    reply = await ask(parts)

    if is_skip(reply):
        banter = await ask_banter(system_text, caption_for_prompt)
        if not is_skip(banter) and "couldn’t form a reply" not in banter:
            return await update.message.reply_text(banter)
        return await update.message.reply_text(brief_fallback(username, name, photo=True))

    USER[uid].history.append((BOT_NAME, reply))
    await update.message.reply_text(reply)

# ================== Run bot (long-polling) ==================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler("vocab", vocab_cmd))
    app.add_handler(CommandHandler("reading", reading_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logging.info("James Makonian bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
