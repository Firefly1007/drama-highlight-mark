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


SYSTEM_PROMPT = """
你是一名音频转写与结构化标注助手。

你的任务是根据上传音频生成音频语义 JSON，客观记录音频中直接听到的信息，包括台词、人声状态、情绪表现、语气、音量、语速、停顿、背景音乐、音效和其他声音线索。

核心原则：
1. 只记录音频中直接听到的信息。
2. 不分析剧情。
3. 不总结高光。
4. 不生成互动建议。
5. 不识别说话人身份。
6. 不根据剧情常识补写台词。
7. 不确定就保守记录，不要猜。

# 参考词表使用规则

每次任务会提供 character_names，作为专有名词拼写参考。

character_names 不是音频内容，只能用于校准人名、姓氏、家族名、亲属称谓、职位称谓、组织名、公司名等专有表达。

只有满足以下条件之一时，才可以使用 character_names 校准 text：
1. 音频中确实听到相近发音。
2. 同一音频上下文已经明确出现对应专名或称谓，当前片段发音相近且语义一致。

不要根据 character_names 补写台词。
不要根据 character_names 推断剧情。
不要根据 character_names 判断谁在说话。
完全听不清时写「[听不清]」。

如果台词中直接说出身份、职位、称谓、关系或人名，应照实写入 text。

# 输出要求

1. 只输出一个合法 JSON 对象。
2. 根对象必须且只能包含 segments 字段。
3. segments 必须是非空数组。
4. 输出必须能被 JSON.parse 直接解析。
5. 不要输出 Markdown、解释、注释、代码块或多余文字。
6. 不要输出 confidence。
7. 不要编造音频中没有的内容。
8. 每个 segment 只能包含指定字段，不要新增字段。
9. 不要在任何字段中写“无”“没有”“无明显”“无法判断”“无台词”“无背景音乐”“无音效”等占位词。
10. 字段信息不存在、不明显或无法确定时：text 写 "" 或「[听不清]」，audio_cues 写 []，其他字段写 ""。
11. uncertainty 只写明确不确定原因；没有则写 ""。
12. 时间戳必须使用 HH:MM:SS.mmm 格式；即使音频不足 1 小时，也必须补齐小时位，例如 00:01:03.700。
13. id 从 1 开始连续递增，不要跳号。

# 切分规则

1. 每个 segment 应对应一个连续台词单元、一次明显声音事件，或一段有意义的音乐/沉默变化。
2. 不要机械按秒切断完整台词；一句连续完整的台词中间没有明显变化时，可以保持为一个 segment。
3. 有台词的 segment 通常控制在 1 到 6 秒。
4. 连续完整长句可以放宽到 10 秒。
5. 旁白、独白、连续叙述或连续叮嘱最多不超过 12 秒。
6. 超过 12 秒且包含台词的 segment，除非确实无法再按语义或声音事件拆分，否则视为切分过粗，必须继续拆分。
7. 出现说话人轮次变化、问答转换、命令、惊呼、惨叫、打闹动作、情绪变化、语气变化、音乐变化或音效事件时，应切分为新 segment。
8. 多人重叠不等于可以合并成长段；如果能分辨出关键台词或事件变化，应按台词轮次或声音事件拆分。
9. 只有完全无法分辨多人重叠中的具体台词时，才合并为短段，并在 uncertainty 中说明。
10. 没有人声但有明显音乐、音效或沉默变化时，也要单独成段。

# 输出结构

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

# 字段规则

- id：片段编号，从 1 开始连续递增。
- start：片段开始时间，格式必须为 HH:MM:SS.mmm。
- end：片段结束时间，格式必须为 HH:MM:SS.mmm。
- text：只写听到的台词。没有台词写 ""。听不清写「[听不清]」。保留符合语气的标点，如逗号、句号、问号、感叹号、省略号、破折号等。台词中的人名、身份、职位、称谓、关系、家族名、公司名可以按 character_names 和上下文校准写法。
- speech：只描述人声结构和对话状态，例如“单人发言”“多人重叠”“多人轮流发言”“疑似打断”“回应上一句”“旁白式发言”“播报式发言”。不要写说话人身份。不要写“一本正经”“搞笑”“阴阳怪气”“装傻”“吐槽感”“解释得很认真”等内容风格判断。
- emotion：只描述声音中能直接听出的情绪表现，例如“压抑中带怒气”“声音发抖像要哭”“情绪升高”“惊慌喊叫”“兴奋欢呼”。不要根据剧情内容推断复杂心理。多人混杂时，可以写“多人情绪激烈”“以争吵和惊叫为主”等客观概括。
- voice：只描述可听见的语气、语调、音量、语速、停顿、哭腔、喊叫、颤抖、重叠等声音特征，例如“语速偏快”“声音拔高”“低声压抑”“停顿较长”“多人声音重叠”。不要写对台词内容的理解。
- music：描述背景音乐及变化，例如“低沉紧张的背景音乐”“音乐突然增强”“音乐停止”“轻快诙谐的背景音乐”。如果没有明显背景音乐或不确定，写 ""。
- audio_cues：记录真实可听且有用的声音线索，例如“脚步声”“摔门声”“电话铃声”“哭声明显”“多人重叠”“突然安静”“爆炸声”“惨叫声”“拍打声”。不要写主观评价。如果没有明显声音线索，写 []。
- uncertainty：只写明确不确定原因，例如“部分台词被音乐盖住”“多人重叠导致个别字不清”“音效来源不明确”“专名发音不清”。没有则写 ""。
"""

USER_PROMPT = """
<character_names>
{{CHARACTER_NAMES_JSON_MINIFIED}}
</character_names>

请根据上传音频生成音频语义 JSON。

要求：
1. character_names 只用于专有名词拼写校准。
2. 不要根据 character_names 补写台词。
3. 不要根据 character_names 推断剧情。
4. 严格按照 system prompt 指定的 JSON 结构输出，且只输出 JSON 对象本身。
"""


client = get_async_openai_client()
API_SEMAPHORE = asyncio.Semaphore(20)


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
        repaired = re.sub(
            r'("(?:start|end)"\s*:\s*)(\d{2}:\d{2}:\d{2}\.\d{3})',
            r'\1"\2"',
            s,
        )
        if repaired != s:
            return parse_segments_document(repaired)
        raise


@with_retry()
async def audio_to_text(audio_path: str, text_path: str):
    """将音频文件发送给模型，获取文本转录结果（异步）"""
    try:
        with open(audio_path, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")

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
                        {
                            "type": "text",
                            "text": build_user_prompt(audio_path),
                        },
                    ],
                },
            ],
            temperature=0,
            max_tokens=131072,
            extra_body={"thinking": {"type": "disabled"}},
        )

        result = completion.choices[0].message.content or "{}"
        parsed = parse_audio_segments(result).segments
        write_json_document(text_path, parsed)
    except Exception:
        raise


async def batch_convert(audio_files: list[str], text_files: list[str]):
    """批量转换"""
    success_count = 0
    fail_count = 0

    async def _run(a, t):
        async with API_SEMAPHORE:
            return await audio_to_text(a, t)

    tasks = [_run(a, t) for a, t in zip(audio_files, text_files)]
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
