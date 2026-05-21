import os
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionContentPartInputAudioParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionUserMessageParam,
)
import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

LLM_MODEL_ID = os.getenv("LLM_MODEL_ID")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")

assert LLM_MODEL_ID, "LLM_MODEL_ID is not set in .env"
assert LLM_API_KEY, "LLM_API_KEY is not set in .env"
assert LLM_BASE_URL, "LLM_BASE_URL is not set in .env"

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

completion = client.chat.completions.create(
    model=LLM_MODEL_ID,
    messages=[
        {
            "role": "system",
            "content": "You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024.",
        },
        ChatCompletionUserMessageParam(
            role="user",
            content=[
                ChatCompletionContentPartInputAudioParam(
                    type="input_audio",
                    input_audio={
                        "data": "https://example-files.cnbj1.mi-fds.com/example-files/audio/audio_example.wav",
                        "format": "wav",
                    },
                ),
                ChatCompletionContentPartTextParam(
                    type="text", text="please describe the content of the audio"
                ),
            ],
        ),
    ],
    max_completion_tokens=1024,
)

print(completion.choices[0].message.content)
