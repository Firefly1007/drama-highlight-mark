import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp
from bs4 import BeautifulSoup
from tqdm import tqdm

from pipline.common.paths import DATA_DIR
from pipline.common.runtime import (
    EpisodeStatus,
    print_episode_status,
    write_json_document,
)

BASE_URL = "https://www.hongguoduanju.com/detail?series_id="

JSON_PATH = DATA_DIR / "video" / "name2id.json"
OUTPUT_PATH = DATA_DIR / "video" / "drama_info.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]


def extract_info(html: str):
    soup = BeautifulSoup(html, "html.parser")

    desc_div = soup.find("div", class_=re.compile(r"^pc-desc-[a-zA-Z0-9]{6}$"))
    description = desc_div.get_text(strip=True) if desc_div else ""

    char_divs = soup.find_all("div", class_=re.compile(r"^pc-fakename-[a-zA-Z0-9]{6}$"))
    characters = []
    for div in char_divs:
        text = div.get_text(strip=True)
        if text.startswith("饰"):
            text = text[1:].strip()
        characters.append(text)

    return description, characters


async def fetch_with_retry(session: aiohttp.ClientSession, url: str, name: str) -> str:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.get(
                url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    last_error = Exception(f"HTTP {resp.status}")
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[attempt]
                        tqdm.write(
                            f"  {name} retry {attempt + 1}/{MAX_RETRIES} in {delay}s (HTTP {resp.status})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise last_error
                return await resp.text(encoding="utf-8")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt]
                tqdm.write(
                    f"  {name} retry {attempt + 1}/{MAX_RETRIES} in {delay}s ({type(e).__name__})"
                )
                await asyncio.sleep(delay)
                continue
            raise last_error
    raise last_error  # type: ignore[return]


async def _fetch_one(
    session: aiohttp.ClientSession, item: dict[str, str]
) -> dict[str, Any]:
    """抓取并解析一部短剧（需传入共享 session）。"""
    name = item["name"]
    url = BASE_URL + item["book_id"]
    html = await fetch_with_retry(session, url, name)
    description, characters = extract_info(html)
    return {"name": name, "description": description, "characters": characters}


async def extract_single(match: dict[str, str]) -> dict[str, Any]:
    """提取单部短剧信息（独立 session，输出单剧文件 + 状态）。"""
    name = match["name"]
    book_id = match["book_id"]
    output_path = str(DATA_DIR / "video" / f"{book_id}_info.json")

    print_episode_status(
        status=EpisodeStatus.PENDING,
        source_path=str(JSON_PATH),
        output_path=output_path,
    )
    print_episode_status(
        status=EpisodeStatus.RUNNING,
        source_path=f"{name} ({book_id})",
        output_path=output_path,
    )

    async with aiohttp.ClientSession() as session:
        try:
            result = await _fetch_one(session, match)
        except Exception as e:
            result = {"name": name, "description": "", "characters": []}
            tqdm.write(f"[FAIL] {name}: {e}")

    if result["description"]:
        write_json_document(output_path, [result])
        print_episode_status(
            status=EpisodeStatus.SUCCESS,
            source_path=f"{name} ({book_id})",
            output_path=output_path,
        )
    else:
        print_episode_status(
            status=EpisodeStatus.FAILED,
            source_path=f"{name} ({book_id})",
            output_path=output_path,
            error="提取失败，描述为空",
        )

    return result


async def extract_batch():
    """批量提取全部短剧（共享 session，输出聚合文件）。"""
    items = load_name_id_list()
    results: list[dict[str, Any] | None] = [None] * len(items)

    async with aiohttp.ClientSession() as session:
        task_map: dict[asyncio.Future[Any], int] = {
            asyncio.create_task(_fetch_one(session, item)): i
            for i, item in enumerate(items)
        }
        with tqdm(total=len(task_map), desc="Fetching", unit="drama") as pbar:
            for fut in asyncio.as_completed(task_map):
                idx = task_map[fut]
                try:
                    results[idx] = await fut
                except Exception as e:
                    results[idx] = {
                        "name": items[idx]["name"],
                        "description": "",
                        "characters": [],
                    }
                    tqdm.write(f"[FAIL] {items[idx]['name']}: {e}")
                pbar.update(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_document(str(OUTPUT_PATH), results)

    ok_count = sum(1 for r in results if r and r["description"])
    print(f"\n{ok_count}/{len(results)} succeeded, saved to {OUTPUT_PATH}")


def load_name_id_list() -> list[dict[str, str]]:
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def main():
    parser = argparse.ArgumentParser(description="短剧信息提取工具（异步批量抓取）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--book-id",
        type=str,
        dest="book_id",
        help="按 book_id 提取单部短剧",
    )
    group.add_argument(
        "--name",
        type=str,
        dest="name",
        help="按短剧名提取单部短剧",
    )
    args = parser.parse_args()

    if args.book_id or args.name:
        name_id_list = load_name_id_list()
        if args.book_id:
            match = next(
                (item for item in name_id_list if item["book_id"] == args.book_id), None
            )
            if match is None:
                raise ValueError(f"未找到 book_id={args.book_id} 对应的短剧")
        else:
            match = next(
                (item for item in name_id_list if item["name"] == args.name), None
            )
            if match is None:
                raise ValueError(f"未找到 name={args.name} 对应的短剧")
        asyncio.run(extract_single(match))
    else:
        asyncio.run(extract_batch())


if __name__ == "__main__":
    main()
