from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"


def replace_path_part(path: str | Path, source_part: str, target_part: str) -> Path:
    """将路径中的指定目录名替换为目标目录名。"""
    source = Path(path)
    parts = list(source.parts)

    try:
        index = parts.index(source_part)
    except ValueError as exc:
        raise ValueError(f"路径 {source} 不包含目录 {source_part}") from exc

    parts[index] = target_part
    return Path(*parts)


def map_output_file(
    source_path: str | Path,
    *,
    source_dir_name: str,
    target_dir_name: str,
    target_suffix: str,
) -> Path:
    """根据源文件路径推导对应的输出文件路径。"""
    mapped = replace_path_part(source_path, source_dir_name, target_dir_name)
    return mapped.with_suffix(target_suffix)


def map_output_dir(
    source_dir: str | Path,
    *,
    source_dir_name: str,
    target_dir_name: str,
) -> Path:
    """根据源目录路径推导对应的输出目录路径。"""
    return replace_path_part(source_dir, source_dir_name, target_dir_name)
