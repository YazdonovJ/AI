from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
import base64
import uuid
from tokens import GEMINI_API

client = genai.Client(api_key=GEMINI_API)

def generate_image(text):
    try:
        response = client.models.generate_content(
        model="gemini-2.0-flash-exp-image-generation",
        contents=text,
        config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE']
        ))
        for part in response.candidates[0].content.parts:
            if part.text is not None:
                print(part.text)
            elif part.inline_data is not None:
                image = Image.open(BytesIO((part.inline_data.data)))
                name = str(uuid.uuid4())
                image.save(f'{name}.webp')
                return f'{name}.webp'
    except:
        return "error"
  
