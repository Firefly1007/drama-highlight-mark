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

    video_model_id: str = ""
    video_api_key: str = ""
    video_base_url: str = ""


def load_env() -> None:
    """加载项目根目录下的环境变量文件。"""
    dotenv.load_dotenv(ENV_FILE, override=True)


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
        video_model_id=os.getenv("VIDEO_MODEL_ID", ""),
        video_api_key=os.getenv("VIDEO_API_KEY", ""),
        video_base_url=os.getenv("VIDEO_BASE_URL", ""),
    )


def get_async_openai_client() -> AsyncOpenAI:
    """基于当前配置创建异步 OpenAI 客户端。"""
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


def get_video_client() -> OpenAI:
    """基于当前配置创建图片生成 OpenAI 客户端。"""
    settings = get_settings()
    assert settings.video_api_key, "VIDEO_API_KEY is not set in .env"
    assert settings.video_base_url, "VIDEO_BASE_URL is not set in .env"
    assert settings.video_model_id, "VIDEO_MODEL_ID is not set in .env"
    return OpenAI(
        api_key=settings.video_api_key,
        base_url=settings.video_base_url,
    )
