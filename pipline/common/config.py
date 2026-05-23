import os
from functools import lru_cache

import dotenv
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ConfigDict

from pipline.common.paths import ENV_FILE


class PipelineSettings(BaseModel):
    """定义流水线运行所需的环境配置。"""
    model_config = ConfigDict(extra="forbid")

    llm_model_id: str
    llm_api_key: str
    llm_base_url: str


def load_env() -> None:
    """加载项目根目录下的环境变量文件。"""
    dotenv.load_dotenv(ENV_FILE)


@lru_cache(maxsize=1)
def get_settings() -> PipelineSettings:
    """读取并缓存流水线运行所需的配置项。"""
    load_env()
    llm_model_id = os.getenv("LLM_MODEL_ID", "")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_base_url = os.getenv("LLM_BASE_URL", "")

    assert llm_model_id, "LLM_MODEL_ID is not set in .env"
    assert llm_api_key, "LLM_API_KEY is not set in .env"
    assert llm_base_url, "LLM_BASE_URL is not set in .env"

    return PipelineSettings(
        llm_model_id=llm_model_id,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
    )


def get_async_openai_client() -> AsyncOpenAI:
    """基于当前配置创建异步 OpenAI 客户端。"""
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )
