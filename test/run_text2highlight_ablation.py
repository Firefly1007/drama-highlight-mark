import asyncio
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.paths import DATA_DIR
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    get_drama_name_from_path,
    load_drama_info,
    parse_highlights_document,
    parse_segments_list,
    write_json_document,
)

TEXT2HIGHLIGHT_PATH = ROOT / "pipline" / "04_text2highlight.py"
OUTPUT_ROOT = DATA_DIR / "highlight_ablation"
MAX_ATTEMPTS = 3


def load_text2highlight_module():
    spec = importlib.util.spec_from_file_location(
        "text2highlight_module",
        TEXT2HIGHLIGHT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {TEXT2HIGHLIGHT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_text2highlight_module()
SYSTEM_PROMPT = MODULE.SYSTEM_PROMPT


@dataclass(frozen=True)
class Variant:
    name: str
    drama_context: dict[str, Any] | None
    extra_instruction: str


def build_variants(text_path: Path) -> list[Variant]:
    drama_info = load_drama_info()
    drama_name = get_drama_name_from_path(text_path)
    drama = drama_info.get(drama_name)
    if drama is None:
        raise ValueError(
            f"找不到短剧 '{drama_name}' 的参考信息，请检查 {DRAMA_INFO_PATH}"
        )

    return [
        Variant(
            name="A",
            drama_context=None,
            extra_instruction=(
                "本组不提供 drama_context。"
                "你只能依据 segments 判断，不允许纠错。"
                "不要把疑似错别字、同音词、人名或关系改写成你认为更合理的版本。"
            ),
        ),
        Variant(
            name="B",
            drama_context={
                "name": drama.name,
                "characters": drama.characters,
            },
            extra_instruction=(
                "本组只提供剧名和角色表，不提供简介。"
                "不要求纠错；若 segments 本身不清楚，优先保守表达。"
            ),
        ),
        Variant(
            name="C",
            drama_context=drama.model_dump(mode="json"),
            extra_instruction=(
                "本组提供完整剧名、简介、角色表。"
                "允许在高置信情况下纠错，但不得改写没有证据的剧情。"
            ),
        ),
    ]


def build_user_prompt(
    *,
    variant: Variant,
    segments_json_minified: str,
) -> str:
    parts: list[str] = []
    if variant.drama_context is not None:
        parts.extend(
            [
                "<drama_context>",
                json.dumps(
                    variant.drama_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "</drama_context>",
                "",
            ]
        )
    parts.extend(
        [
            "<segments>",
            segments_json_minified,
            "</segments>",
            "",
            variant.extra_instruction,
            "请根据当前输入识别可互动剧情高光点，并严格按照 system prompt 指定的 JSON 格式输出。",
        ]
    )
    return "\n".join(parts)


async def run_variant(
    *,
    client,
    model: str,
    variant: Variant,
    segments: list,
    user_prompt: str,
    output_dir: Path,
) -> dict[str, Any]:
    variant_dir = output_dir / variant.name
    variant_dir.mkdir(parents=True, exist_ok=True)
    (variant_dir / "prompt.txt").write_text(user_prompt, encoding="utf-8")
    last_exception: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        result = completion.choices[0].message.content or ""
        (variant_dir / f"raw_response_attempt{attempt}.txt").write_text(
            result,
            encoding="utf-8",
        )

        try:
            parsed = parse_highlights_document(result, segments)
            write_json_document(str(variant_dir / "highlights.json"), parsed)
            return {
                "variant": variant.name,
                "output_path": str(variant_dir / "highlights.json"),
                "count": len(parsed),
                "attempts": attempt,
            }
        except Exception as exc:
            last_exception = exc

    if last_exception is not None:
        raise last_exception
    raise RuntimeError(f"变体 {variant.name} 未产生有效输出")


async def main() -> None:
    text_path = (
        DATA_DIR
        / "text"
        / "十八岁太奶奶驾到，重整家族荣耀第三部"
        / "第1集.json"
    )
    raw_text = text_path.read_text(encoding="utf-8")
    segments = parse_segments_list(raw_text)
    segments_json_minified = json.dumps(
        [segment.model_dump(mode="json") for segment in segments],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    output_dir = OUTPUT_ROOT / text_path.parent.name / text_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    variants = build_variants(text_path)
    manifest = {
        "text_path": str(text_path),
        "output_dir": str(output_dir),
        "variants": [
            {
                "name": variant.name,
                "has_drama_context": variant.drama_context is not None,
                "drama_context_keys": (
                    list(variant.drama_context.keys())
                    if variant.drama_context is not None
                    else []
                ),
                "extra_instruction": variant.extra_instruction,
            }
            for variant in variants
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    client = get_async_openai_client()
    model = get_settings().llm_model_id
    tasks = [
        run_variant(
            client=client,
            model=model,
            variant=variant,
            segments=segments,
            user_prompt=build_user_prompt(
                variant=variant,
                segments_json_minified=segments_json_minified,
            ),
            output_dir=output_dir,
        )
        for variant in variants
    ]
    results = await asyncio.gather(*tasks)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
