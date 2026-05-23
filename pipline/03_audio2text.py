import argparse
import asyncio
import base64
import json
import re
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.paths import DATA_DIR, map_output_dir, map_output_file
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    EpisodeStatus,
    load_drama_info,
    get_drama_name_from_path,
    parse_segments_document,
    print_episode_status,
    with_retry,
    write_json_document,
)
from pipline.common.schemas import SegmentsDocument

SETTINGS = get_settings()


def build_user_prompt(audio_path: str | Path) -> str:
    drama_info = load_drama_info()
    drama_name = get_drama_name_from_path(audio_path)
    drama = drama_info.get(drama_name)
    if drama is None:
        raise ValueError(
            f"找不到短剧 '{drama_name}' 的参考信息，请检查 {DRAMA_INFO_PATH}"
        )
    char_names_json = json.dumps(
        drama.characters, ensure_ascii=False, separators=(",", ":")
    )
    return USER_PROMPT.replace("{{CHARACTER_NAMES_JSON}}", char_names_json)


SYSTEM_PROMPT = """
你是一名专业的音频转写与结构化标注助手。请根据我上传的音频，生成音频语义 JSON。

你的任务是尽可能客观地记录音频中可以直接听到的信息，包括台词、人声状态、情绪表现、语气、音量、语速、停顿、背景音乐、音效和其他声音线索。

每次任务都会提供当前短剧的角色名单。角色名单只作为”专有名词拼写参考”，用于提高台词转写中人名、称呼等专有表达的准确性。

专名参考上下文使用规则：

1. 参考信息不是音频内容，不要根据参考信息补写音频中没有听到的台词。
2. 只有当音频中确实听到相近发音时，才可以使用参考信息中的标准写法。
3. 如果音频发音不清，但疑似对应参考信息中的人名或专有表达，可以使用参考写法，并在 uncertainty 中说明“专名根据参考信息校准”。
4. 如果完全听不清，不要用参考信息猜出台词，仍然写为「[听不清]」。
5. 不要因为参考信息中存在某个角色名，就强行把模糊声音识别成该角色名。
6. 不要识别说话人身份，不要判断“男主”“女主”“反派”等人物身份。
7. 参考信息只影响 text 中专有名词和专有表达的写法，不影响 emotion、voice、music、audio_cues 的客观标注。
8. 如果音频听到的内容与参考信息冲突，优先以音频为准；参考信息只用于专名校准，不用于改写剧情。

请严格遵守以下要求：

1. 只输出一个 JSON 对象，不要输出 JSON 数组作为根节点。
2. 根对象必须且只能包含一个字段：segments。
3. segments 的值必须是数组。
4. 不要输出解释、Markdown、代码块或多余文字。
5. 不要分析剧情，不要判断片段重要性，不要输出总结性剧情标签。
6. 不要识别说话人身份，不要猜测“男主”“女主”“反派”等人物身份。
7. 不要强行使用固定选项，请用简短自然语言描述真实听到的音频特征。
8. 听不清的台词写为「[听不清]」，不要编造。
9. 没有台词时，text 必须设为空字符串 ""。
10. 如果某项信息不存在、没有明显特征、无法判断或不确定，不要写“无”“没有”“无法判断”“无明显”等文字，必须输出空字符串 ""。
11. audio_cues 如果没有真实存在且有用的声音线索，必须输出空数组 []。
12. 不要输出 confidence 分数。
13. uncertainty 只在存在明确不确定原因时填写；如果没有明确不确定原因，必须输出空字符串 ""。
14. 输出必须是可以被 JSON.parse 直接解析的合法 JSON。
15. 不要输出多个 JSON 对象。
16. 不要在 JSON 前后添加任何文本。

切分规则：

1. 将音频切分为多个片段。
2. 每个片段对应一段台词、一次明显声音事件，或一段有意义的沉默、音乐变化。
3. 每个片段建议控制在 1 到 5 秒。
4. 如果台词很短，可以短于 1 秒。
5. 如果情绪、语气、音量、语速、音乐、音效或沉默状态发生明显变化，应拆分为新片段。
6. 没有人声但有明显音乐、音效或沉默变化时，也要单独生成片段。
7. 时间戳精确到毫秒，格式为 HH:MM:SS.mmm。
8. id 从 1 开始连续递增，不要跳号。

输出 JSON 必须严格符合以下结构：

{
  "segments": [
    {
      "id": 1,
      "start": "00:00:00.000",
      "end": "00:00:00.000",
      "text": "",
      "speech": "",
      "emotion": "",
      "voice": "",
      "music": "",
      "audio_cues": [],
      "uncertainty": ""
    }
  ]
}

字段填写要求：

- segments：音频片段数组，不能为空。
- id：片段编号，从 1 开始连续递增。
- start：片段开始时间，格式为 HH:MM:SS.mmm。
- end：片段结束时间，格式为 HH:MM:SS.mmm。
- text：只写听到的台词，不写情绪、语气或解释；没有台词时写空字符串 ""。
- speech：描述人声状态和对话状态，例如“单人发言”“回应上一句”“疑似打断”“多人重叠”；如果没有人声、无法判断或没有必要描述，写空字符串 ""。
- emotion：只描述声音表现出的情绪和变化，例如“压抑中带怒气”“声音发抖像要哭”“情绪逐渐升高”“突然沉默”；如果没有明显情绪或无法判断，写空字符串 ""。
- voice：描述语气、语调、音量、语速、停顿等声音特征，例如“语速偏快”“声音突然拔高”“低声压抑”“尾音上扬”“长时间停顿”；如果没有明显声音特征或无法判断，写空字符串 ""。
- music：描述背景音乐是否存在，以及音乐氛围和变化，例如“低沉紧张的背景音乐”“悲伤钢琴声”“音乐突然增强”“音乐突然停止”；如果没有背景音乐、音乐不明显或无法判断，写空字符串 ""。
- audio_cues：只记录真实存在、可以直接听到、且对理解声音场景有用的声音线索。
  - 如果没有明显声音线索，必须输出空数组 []。
  - 不要在 audio_cues 中写“无”“无明显声音”“没有”“无音效”等占位内容。
  - 不要在 audio_cues 中写主观评价，例如“质问感明显”“情绪很强”“很有压迫感”。
  - audio_cues 可以包含具体音效、沉默、音乐变化、人声重叠、背景噪声等，例如“摔门声”“脚步声”“电话铃声”“哭声明显”“玻璃碎裂声”“多人重叠”“突然安静”“背景音乐压过台词”“环境噪声”。
- uncertainty：只说明明确的不确定原因，例如“部分台词被音乐盖住”“多人重叠导致个别字不清”“情绪判断不稳定”“音效来源不明确”“专名根据参考信息校准”；如果没有明确不确定原因，写空字符串 ""。

额外禁止：

- 不要把“无法判断”写进任何字段。
- 不要把“无”“没有”“无明显”“无台词”“无背景音乐”“无音效”写进任何字段。
- 不要把字段说明文字原样填入 JSON。
- 不要输出示例。
- 不要输出省略号。
- 不要输出注释。
"""

USER_PROMPT = """
下面是本次音频所属短剧的角色名单。该信息只用于专有名词拼写校准，不是音频转写内容。

<character_names>
{{CHARACTER_NAMES_JSON}}
</character_names>

请根据我上传的音频，生成音频语义 JSON。

要求：
- 严格按照 system prompt 的 JSON 结构输出。
- 角色名单只用于人名、称呼等专有表达的写法校准。
- 不要根据角色名单补写没有听到的台词。
- 不要根据角色名单判断说话人身份。
- 不要输出解释、Markdown、代码块或多余文字。
"""


client = get_async_openai_client()


def strip_markdown_code_block(text: str) -> str:
    """
    去掉模型可能输出的 Markdown 代码块。
    正常使用 response_format=json_schema 时一般不会出现，但保留容错。
    """
    s = text.strip()

    code_block = re.fullmatch(
        r"```(?:json)?\s*([\s\S]*?)\s*```",
        s,
        flags=re.IGNORECASE,
    )

    if code_block:
        return code_block.group(1).strip()

    return s


def parse_audio_segments(result: str) -> SegmentsDocument:
    """
    解析模型输出的音频语义 JSON。

    当前标准格式适配：
    response_format={"type": "json_schema"}

    标准输出：
    {
      "segments": [
        {
          "id": 1,
          "start": "00:00:00.000",
          "end": "00:00:00.000",
          "text": "",
          "speech": "",
          "emotion": "",
          "voice": "",
          "music": "",
          "audio_cues": [],
          "uncertainty": ""
        }
      ]
    }

    注意：
    - 根节点必须是 JSON 对象。
    - 根对象必须且只能包含 segments 字段。
    - segments 必须是数组。
    - 只要任意 segment 不合法，就整批报错。
    - 不会跳过坏对象。
    - 不会返回残缺结果。
    """
    s = strip_markdown_code_block(result)

    if not s:
        raise ValueError("模型输出为空，放弃全部输出")

    try:
        return parse_segments_document(s)
    except ValueError:
        raise


@with_retry()
async def audio_to_text(audio_path: str, text_path: str):
    """将音频文件发送给模型，获取文本转录结果（异步）"""
    try:
        with open(audio_path, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")

        user_prompt = build_user_prompt(audio_path)

        completion = await client.chat.completions.create(
            model=SETTINGS.llm_model_id,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": b64_str,
                                "format": "mp3",
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            temperature=0
        )

        result = completion.choices[0].message.content or "{}"
        parsed = parse_audio_segments(result)
        write_json_document(text_path, parsed)
    except Exception:
        raise


async def batch_convert(audio_files: list[str], text_files: list[str]):
    """批量转换"""
    success_count = 0
    fail_count = 0
    tasks = [audio_to_text(a, t) for a, t in zip(audio_files, text_files)]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="音频转文本"):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1
    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_convert_dir(audio_dir: str | Path, text_dir: str | Path):
    """批量转换目录下所有音频文件"""
    audio_dir = Path(audio_dir)
    text_dir = Path(text_dir)
    candidates = list(audio_dir.rglob("*.mp3"))
    audio_files = []
    text_files = []
    for audio_path in tqdm(candidates, desc="扫描音频文件"):
        rel_path = audio_path.relative_to(audio_dir)
        text_path = text_dir / rel_path.with_suffix(".json")
        if text_path.exists():
            continue
        audio_files.append(str(audio_path))
        text_files.append(str(text_path))
        text_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(batch_convert(audio_files, text_files))


def get_text_path(audio_path: str | Path) -> Path:
    """根据音频路径推导文本路径（audio -> text，后缀改 .json）"""
    return map_output_file(
        audio_path,
        source_dir_name="audio",
        target_dir_name="text",
        target_suffix=".json",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="音频转文本工具（异步批量转换）")
    parser.add_argument(
        "--audio-path",
        type=str,
        dest="audio_path",
        help="音频文件或目录路径。传文件转单个，传目录递归转换，不传则转换 data/audio 下所有音频",
    )
    args = parser.parse_args()

    if args.audio_path:
        audio_path = Path(args.audio_path)
        if audio_path.is_file():
            text_path = get_text_path(audio_path)
            if text_path.exists():
                tqdm.write(f"输出文件已存在，跳过: {text_path}")
            else:
                print_episode_status(
                    status=EpisodeStatus.PENDING,
                    source_path=str(audio_path),
                    output_path=str(text_path),
                )
                text_path.parent.mkdir(parents=True, exist_ok=True)
                print_episode_status(
                    status=EpisodeStatus.RUNNING,
                    source_path=str(audio_path),
                    output_path=str(text_path),
                )
                try:
                    asyncio.run(audio_to_text(str(audio_path), str(text_path)))
                    print_episode_status(
                        status=EpisodeStatus.SUCCESS,
                        source_path=str(audio_path),
                        output_path=str(text_path),
                    )
                except Exception as exc:
                    print_episode_status(
                        status=EpisodeStatus.FAILED,
                        source_path=str(audio_path),
                        output_path=str(text_path),
                        error=str(exc),
                    )
                    raise
        elif audio_path.is_dir():
            text_dir = map_output_dir(
                audio_path,
                source_dir_name="audio",
                target_dir_name="text",
            )
            batch_convert_dir(audio_path, text_dir)
        else:
            raise FileNotFoundError(f"路径不存在: {audio_path}")
    else:
        batch_convert_dir(DATA_DIR / "audio", DATA_DIR / "text")
