"""剧集上下文加载测试。"""

import json
from pathlib import Path

from drama_interaction.context import DramaContext, load_drama_context


def test_load_drama_context_uses_input_parent_name(tmp_path: Path) -> None:
    info_path = tmp_path / "drama_info.json"
    info_path.write_text(
        json.dumps(
            [
                {
                    "name": "测试剧",
                    "description": "一段简介",
                    "characters": ["甲", "乙"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = tmp_path / "测试剧" / "第1集.json"

    assert load_drama_context(source, info_path) == DramaContext(
        name="测试剧",
        description="一段简介",
        characters=["甲", "乙"],
    )
