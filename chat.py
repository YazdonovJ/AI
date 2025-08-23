from aiogram import Bot, Dispatcher, types
import aiogram
from google.genai.errors import ClientError
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import Command
from aiogram.filters import CommandStart
import asyncio
from aiogram.client.default import DefaultBotProperties
import aiogram.utils
from google import genai
from tokens import *
from google import genai
from google.genai import types
from gen import generate_image
from aiogram.types import FSInputFile
from aiogram.enums import ChatType
import os
from PIL import Image
from io import BytesIO
import requests
import os
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile
from functions import *



client = genai.Client(api_key=GEMINI_API, )
chat_sessions = {}
google_search_tool = Tool(
    google_search = GoogleSearch()
)


async def escape_markdown(message, chat, text):
    if "**" in text:
        data = chat.send_message("Markdown_check_bot: This is internal system message and user does not know that I exist, so don't tell about me. I have found a markdown sign in your message. DO NOT use any Markdown formatting. Markdown breaks the formatting in Telegram. write in plain text only. Markdown is STRICTLY PROHIBITED!)")
        print(data.text)
    chunks = split_message(text)
    for response in chunks:
         await message.answer(
            response,
            # parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=message.message_id
            )

def get_or_create_chat_session(telegram_chat_id: int, type, description = None):
    default = get_default_prompt()
    if type == "group" or type == 'supergroup' or type == 'channel':
        instruction = get_group_prompt()
    elif type == 'private':
        instruction = get_private_prompt()
    if description and len(description)> 3:
        instruction+=description
    else:
        instruction+=default
    if telegram_chat_id not in chat_sessions or description:
        chat_sessions[telegram_chat_id] = client.chats.create(model= "gemini-2.0-flash", config=types.GenerateContentConfig(
        system_instruction=instruction,
        thinking_config=types.ThinkingConfig(include_thoughts=False),
        
        tools=[google_search_tool],
        response_modalities=["TEXT"],
        safety_settings=[
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
      ]))
    return chat_sessions[telegram_chat_id]

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        # parse_mode=ParseMode.MARKDOWN
        )
)
dp = Dispatcher()
groups_list = load_groups()
users_list = load_users()

@dp.message(lambda message: not message.text or not message.text.startswith("/"))
async def handle_group_messages(message: Message):
    try:
        chat = get_or_create_chat_session(message.chat.id, message.chat.type)
        if not any(user["id"] == message.from_user.id for user in users_list) and message.from_user.username not in ['GroupAnonymousBot', 'Channel_Bot']:
                user_data = {
                    'id': message.from_user.id,
                    'username':message.from_user.username or "Unknown",
                    'name': message.from_user.first_name + " " + (message.from_user.last_name if message.from_user.last_name else "") or "Unknown",
                }
                users_list.append(user_data)
                save_users(users_list)
                print('NEW USER')
        if message.chat.type == 'private':
            await bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
        if message.chat.type in ['supergroup', 'group']:
            if not any(g["id"] == message.chat.id for g in groups_list):
                group_data = {
                    "id": message.chat.id,
                    "title": message.chat.title or "Unknown",
                    "url": f"https://t.me/{message.chat.username}" if message.chat.username else "Private/No link"
                }
                groups_list.append(group_data)
                save_groups(groups_list)
                print(f"✅ Bot already added — saved group: {group_data['title']} ({group_data['id']})", flush=True)
        user = message.from_user
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        if full_name.lower() in ['telegram', 'group', 'admin']:
            full_name = 'Admin'
        original  = ""
        if message.reply_to_message:
            if message.reply_to_message.text:
                original = f"( reply to {'Admin' if message.reply_to_message.from_user.full_name.lower() in ['telegram', 'group', 'admin'] else message.reply_to_message.from_user.full_name}:  {message.reply_to_message.text})"
            elif message.reply_to_message.caption:
                original = f"( reply to {'Admin' if message.reply_to_message.from_user.full_name.lower() in ['telegram', 'group', 'admin'] else message.reply_to_message.from_user.full_name}:  {message.reply_to_message.caption})"

        data = f"{full_name}: {message.text} {original}"
        if message.photo:
            data = f"{full_name}: {message.caption if message.caption else 'Image sent'} {original}"
            print(data, flush=True)
            file_id = message.photo[-1].file_id
            file = await bot.get_file(file_id)
            image_path = f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}'
            image = requests.get(image_path)
            
            response = chat.send_message(
                [
                    Image.open(BytesIO(image.content)),
                    data
                ]
            )
            #FOR TEST
            if response.text.startswith('thought'):
                with open('errors.txt', 'w') as file:
                    file.write(f'{response}'+'\n'+f'*'*50)
            #ENDTEST
            if "GENERATE_IMAGE" in response.text:
                response = response.text
                prompt = response.split("GENERATE_IMAGE")[1]
                caption = response.split("GENERATE_IMAGE")[0]
                image = generate_image(prompt)
                if image == 'error':
                    err = chat.send_message("IMAGE GENERATOR BOT: Sorry, due to high demand, i cannot generate this image right now. Retry later... EXPLAIN IT TO USER")
                    await message.answer(err.text, reply_to_message_id=message.message_id)
                else:
                    await message.answer_photo(FSInputFile(image), show_caption_above_media=True, caption=caption, reply_to_message_id=message.message_id)
                    os.system(f'rm {image}')
            
            elif "SKIP" not in response.text:
                await escape_markdown(message, chat, response.text)
                
                

        else:
            response  = chat.send_message(data,)
            print(data, flush=True)
            print(f"GPTillo: {response.text}", flush=True)
            if "GENERATE_IMAGE" in response.text:
                response = response.text
                prompt = response.split("GENERATE_IMAGE")[1]
                caption = response.split("GENERATE_IMAGE")[0]
                image = generate_image(prompt)
                if image == 'error':
                    err = chat.send_message("IMAGE GENERATOR BOT: Sorry, due to high demand, i cannot generate this image right now. Retry later... EXPLAIN IT TO USER")
                    await message.answer(err.text, reply_to_message_id=message.message_id)
                else:
                    await message.answer_photo(FSInputFile(image), show_caption_above_media=True, caption=caption, reply_to_message_id=message.message_id)
                    os.system(f'rm {image}')
            

            elif "SKIP" not in response.text:
                #FOR TEST
                if response.text.lower().startswith('thought'):
                    with open('errors.txt', 'w') as file:
                        file.write(f'{response}'+'\n'+f'*'*50)
                #ENDTEST
                await escape_markdown(message, chat, response.text)
    except ClientError as e:
        if "429 RESOURCE_EXHAUSTED" in str(e):
            update_token_file()
            restart_program()

@dp.my_chat_member()
async def handle_bot_status_change(event: ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status
    print(new_status, flush=True)

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        groups_list = load_groups()  # Always get fresh version

        if new_status == "administrator":
            if not any(g["id"] == chat.id for g in groups_list):
                group_data = {
                    "id": chat.id,
                    "title": chat.title or "Unknown",
                    "url": f"https://t.me/{chat.username}" if chat.username else "Private/No link"
                }
                groups_list.append(group_data)
                save_groups(groups_list)
                print(f"✅ Bot added to: {chat.title} ({chat.id})", flush=True)

        elif new_status in ("left", "kicked", "removed"):
            groups_list = [g for g in groups_list if g["id"] != chat.id]
            save_groups(groups_list)
            print(f"❌ Bot removed from: {chat.title} ({chat.id})", flush=True)


@dp.message(Command("groups"))
async def pollmath_handler(message:Message):
    all_users = 0
    for i in groups_list:
        try:
            count = await bot.get_chat_member_count(chat_id=i['id'])
        except:
            count = 0
        all_users+=count
    await message.answer(f"Gptillo {len(groups_list)}ta guruhlarga a'zo bo'lgan")
    if message.from_user.username == 'zaynobiddin_shakhabiddinov':
        await message.answer(f"Gptillo bilan {all_users}ta insonlar guruhlarda suhbatda")
        await message.answer(f"Gptillo bilan jami {len(users_list)}ta insonlar suhbatda")
        file = FSInputFile('errors.txt')
        await message.answer_document(file)
        groups_json = FSInputFile('groups.json')
        await message.answer_document(groups_json)
        users_json = FSInputFile('users.json')
        await message.answer_document(users_json)



@dp.message(Command('broadcast'))
async def broadcast_message(message:Message):
    if message.chat.type == 'private' and message.from_user.username == 'zaynobiddin_shakhabiddinov':
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            if message.reply_to_message:
                replied = message.reply_to_message.message_id
                from_chat_id = message.reply_to_message.chat.id
                for chat in groups_list:
                    chat_id = chat['id']
                    try:
                        await bot.forward_message(
                            chat_id=chat_id,
                            from_chat_id=from_chat_id,
                            message_id=replied
                        )
                    except Exception as e:
                        print(f"Failed to send message to {chat_id}: {e}", flush=True)
            else:
                await message.reply("Please provide a message to broadcast after the command.")
            return
        
        text = parts[1]

        for chat in groups_list:
            chat_id = chat["id"]
            try:
                await bot.send_message(chat_id, text)
                print(f"Message sent to {chat_id}", flush=True)
                await asyncio.sleep(0.3)  # avoid flood limits
            except Exception as e:
                print(f"Failed to send message to {chat_id}: {e}", flush=True)
        await message.reply("Broadcast sent!")
    else:
        await message.reply("You are not authorized to use this command.")
    
@dp.message(Command('personality'))
async def add_personality(message:Message):
    description = message.text.split('/personality')[1]
    get_or_create_chat_session(message.chat.id, message.chat.type, description)
    await message.answer(f'Personality changed to: {description}')

@dp.message(Command('start'))
async def add_personality(message:Message):
    if message.chat.type.lower() == "private":
        chat = get_or_create_chat_session(message.chat.id, message.chat.type)
        user = message.from_user
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        response = chat.send_message(f'{full_name}: Hello')
        await message.answer(response.text)

    

async def main():
    await dp.start_polling(bot, skip_updates = True, relax=1.0)

if __name__ == "__main__":
    asyncio.run(main())
