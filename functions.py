import os
import json
import sys
from tokens import *

GROUPS_FILE = "groups.json"
USERS_FILE = 'users.json'


def load_groups():
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, "r") as f:
            return json.load(f)
    return []

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return []

def save_groups(groups):
    with open(GROUPS_FILE, "w") as f:
        json.dump(groups, f, indent=2)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def split_message(text, limit=4096):
    if len(text) <= limit:
        return [text]

    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        # Add paragraph and a double newline (to preserve spacing)
        if len(current) + len(para) + 2 < limit:
            current += para + "\n\n"
        else:
            chunks.append(current.strip())
            current = para + "\n\n"

    if current:
        chunks.append(current.strip())

    return chunks

def update_token_file():
    g1 = GEMINI_API
    g2 = GEMINI_API2
    with open('tokens.py', 'w', encoding='utf-8') as file:
        file.write(f"GEMINI_API = '{g2}'\n")
        file.write(f"GEMINI_API2 = '{g1}'\n")
        file.write(f"BOT_TOKEN = '{BOT_TOKEN}'\n")
    print('[RESOURCE EXHAUSTED FOR TOKEN] tokens.py updated')

def restart_program():
    """Restarts the current Python program."""
    python = sys.executable
    print("RESTARTED")
    os.execl(python, python, *sys.argv)

def get_private_prompt():
    with open('inst_private.txt', 'r') as instruction:
        instruction = instruction.read()
    return instruction

def get_group_prompt():
    with open('inst_group.txt', 'r') as instruction:
        instruction = instruction.read()
    return instruction

def get_default_prompt():
    with open('inst_default.txt', 'r') as default:
        default = default.read()
    return default
