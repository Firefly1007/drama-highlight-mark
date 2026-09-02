import os
import time
import traceback

import dotenv
import httpx
from openai import OpenAI

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

LLM_MODEL_ID = os.getenv("LLM_MODEL_ID")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")

assert LLM_MODEL_ID, "LLM_MODEL_ID is not set in .env"
assert LLM_API_KEY, "LLM_API_KEY is not set in .env"
assert LLM_BASE_URL, "LLM_BASE_URL is not set in .env"

client = OpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    timeout=httpx.Timeout(30.0, connect=5.0),
)

model = LLM_MODEL_ID
print(f"模型: {model}")
print(f"地址: {os.getenv('LLM_BASE_URL')}")
print("-" * 40)

started_at = time.perf_counter()

try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "请介绍一下你自己。"},
        ],
        max_tokens=256,
    )
except Exception as exc:
    elapsed = time.perf_counter() - started_at
    print(f"耗时: {elapsed:.2f}s")
    print(f"异常类型: {type(exc).__name__}")
    print(f"异常信息: {exc}")
    traceback.print_exc()
    raise

elapsed = time.perf_counter() - started_at
print(f"耗时: {elapsed:.2f}s")
print(f"回复: {response.choices[0].message.content}")
