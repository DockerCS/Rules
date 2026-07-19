#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, NamedTuple

# 脚本所在目录 = Rules 根目录
BASE_DIR = Path(__file__).resolve().parent

DownloadFile = Callable[[str, Path], None]


class GitHubArchiveTree(NamedTuple):
    archive_url: str
    subdir: Path


class StreamingCombineTask(NamedTuple):
    vendor: str
    extension: str
    cn_file_set: set[str]
    out_cn_name: str
    out_all_name: str
    is_clash_yaml: bool


DLER_RULES_ARCHIVE_URL = (
    "https://github.com/dler-io/Rules/archive/refs/heads/main.zip"
)

PROVIDER_SYNC_TASKS = (
    (
        "Surge",
        GitHubArchiveTree(
            DLER_RULES_ARCHIVE_URL,
            Path("Surge") / "Surge 3" / "Provider",
        ),
        Path("Surge") / "Provider",
    ),
    (
        "Clash",
        GitHubArchiveTree(
            DLER_RULES_ARCHIVE_URL,
            Path("Clash") / "Provider",
        ),
        Path("Clash") / "Provider",
    ),
)

ASN_SYNC_TASKS = (
    (
        "Surge ASNChina.list",
        "https://raw.githubusercontent.com/VirgilClyne/GetSomeFries/"
        "main/ruleset/ASN.China.list",
        Path("Surge") / "Provider" / "ASNChina.list",
        "Surge",
    ),
    (
        "Clash ASNChina.yaml",
        "https://raw.githubusercontent.com/VirgilClyne/GetSomeFries/"
        "main/ruleset/ASN.China.yaml",
        Path("Clash") / "Provider" / "ASNChina.yaml",
        "Clash",
    ),
)

MEDIA_RULE_MOVE_TASKS = (
    ("Clash", "Douyin.yaml"),
    ("Clash", "TikTok.yaml"),
    ("Surge", "Douyin.list"),
    ("Surge", "TikTok.list"),
)

PRESERVED_MEDIA_RULES = {
    "Clash": ("Emby.yaml",),
    "Surge": ("Emby.list",),
}

# Clash / Surge 归入 StreamingCN 的文件共用同一份基础名单
STREAMING_CN_BASENAMES: set[str] = {
    "Bilibili",
    "Douyin",
    "Emby",
    "IQ",
    "IQIYI",
    "Letv",
    "MOO",
    "Netease Music",
    "Tencent Video",
    "WeTV",
    "Youku",
}

CLASH_STREAMING_CN_FILES = {f"{name}.yaml" for name in STREAMING_CN_BASENAMES}
SURGE_STREAMING_CN_FILES = {f"{name}.list" for name in STREAMING_CN_BASENAMES}

STREAMING_COMBINE_TASKS = (
    StreamingCombineTask(
        vendor="Clash",
        extension=".yaml",
        cn_file_set=CLASH_STREAMING_CN_FILES,
        out_cn_name="StreamingCN.yaml",
        out_all_name="Streaming.yaml",
        is_clash_yaml=True,
    ),
    StreamingCombineTask(
        vendor="Surge",
        extension=".list",
        cn_file_set=SURGE_STREAMING_CN_FILES,
        out_cn_name="StreamingCN.list",
        out_all_name="Streaming.list",
        is_clash_yaml=False,
    ),
)


def _target_matches(vendor: str, target: str) -> bool:
    return target == "all" or target == vendor.lower()


def download_url(url: str, target: Path) -> None:
    """
    下载单个文件到 target。
    Python 证书链异常时回退到系统 curl，以适配本机 GitHub 访问环境。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Rules-Sync-Combiner"})

    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            target.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        return
    except Exception as python_error:
        target.unlink(missing_ok=True)
        curl = shutil.which("curl")
        if curl is None:
            raise RuntimeError(f"下载失败且未找到 curl: {url}") from python_error

        result = subprocess.run(
            [
                curl,
                "-sS",
                "-fL",
                "--retry",
                "3",
                "--connect-timeout",
                "15",
                "--max-time",
                "180",
                "-A",
                "Rules-Sync-Combiner",
                "-o",
                str(target),
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            target.unlink(missing_ok=True)
            detail = result.stderr.strip() or result.stdout.strip() or str(python_error)
            raise RuntimeError(f"下载失败: {url}\n{detail}") from python_error


def _extract_github_archive(archive_url: str, workspace: Path) -> Path:
    """下载并解压 GitHub 分支归档，返回仓库根目录。"""
    workspace.mkdir(parents=True, exist_ok=False)
    archive = workspace / "source.zip"
    extract_dir = workspace / "extract"

    download_url(archive_url, archive)
    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(extract_dir)

    roots = [path for path in extract_dir.iterdir() if path.is_dir()]
    if not roots:
        raise RuntimeError("GitHub 压缩包中没有仓库目录")
    return roots[0]


def _copy_github_archive_tree(
    source: GitHubArchiveTree,
    repository_root: Path,
    target: Path,
) -> None:
    """从已解压的仓库中拷贝指定子目录。"""
    source_dir = repository_root / source.subdir
    if not source_dir.is_dir():
        raise RuntimeError(f"GitHub 压缩包中缺少目录: {source.subdir}")

    shutil.copytree(source_dir, target)


def _ensure_non_empty_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{label} 下载结果为空")


def _ensure_non_empty_dir(path: Path, label: str) -> None:
    if not path.is_dir() or not any(path.iterdir()):
        raise RuntimeError(f"{label} 下载结果为空")


def _replace_directory(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}.sync-",
        dir=target.parent,
    ) as tmp:
        workspace = Path(tmp)
        staging = workspace / "new"
        previous = workspace / "old"
        shutil.copytree(source, staging)

        had_target = target.exists() or target.is_symlink()
        if had_target:
            target.rename(previous)
        try:
            staging.rename(target)
        except Exception:
            if had_target and not (target.exists() or target.is_symlink()):
                previous.rename(target)
            raise


def _read_preserved_media_rules(provider_dir: Path, vendor: str) -> dict[str, bytes]:
    media_dir = provider_dir / "Media"
    if not media_dir.is_dir():
        return {}

    preserved: dict[str, bytes] = {}
    for filename in PRESERVED_MEDIA_RULES.get(vendor, ()):
        path = media_dir / filename
        if path.is_file():
            preserved[filename] = path.read_bytes()
    return preserved


def _restore_preserved_media_rules(provider_dir: Path, preserved: dict[str, bytes]) -> None:
    if not preserved:
        return

    media_dir = provider_dir / "Media"
    media_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in preserved.items():
        (media_dir / filename).write_bytes(content)


def _replace_file(
    source_url: str,
    target: Path,
    label: str,
    download_file: DownloadFile,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{target.name}.sync-",
        dir=target.parent,
    )
    os.close(descriptor)
    staging = Path(staging_name)

    try:
        download_file(source_url, staging)
        _ensure_non_empty_file(staging, label)
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)


def sync_remote_rules(
    target: str = "all",
    download_file: DownloadFile | None = None,
) -> bool:
    """
    同步远程 Provider 和 ASNChina 文件。
    任何同步失败都保留本地已有文件，并返回 False。
    """
    download_file = download_file or download_url

    print("── 🌐 同步远程规则 ──")
    all_synced = True
    provider_tasks = tuple(
        task
        for task in PROVIDER_SYNC_TASKS
        if _target_matches(task[0], target)
    )

    with tempfile.TemporaryDirectory(prefix="rules-provider-") as tmp:
        workspace = Path(tmp)
        repository_root: Path | None = None

        if provider_tasks:
            try:
                repository_root = _extract_github_archive(
                    provider_tasks[0][1].archive_url,
                    workspace / "archive",
                )
            except Exception as e:
                vendors = ", ".join(task[0] for task in provider_tasks)
                print(
                    f"  ⚠️ {vendors}: Provider 归档下载失败，"
                    f"本次保留本地文件：{e}"
                )
                print("     ↳ 已跳过 ASN 更新，重新运行脚本即可重试。")
                print()
                return False

        for index, (vendor, source, rel_target) in enumerate(provider_tasks):
            target_dir = BASE_DIR / rel_target
            downloaded_dir = workspace / f"{index}-{vendor.lower()}-Provider"
            try:
                preserved_rules = _read_preserved_media_rules(target_dir, vendor)
                assert repository_root is not None
                _copy_github_archive_tree(
                    source,
                    repository_root,
                    downloaded_dir,
                )
                _ensure_non_empty_dir(downloaded_dir, f"{vendor} Provider")
                _restore_preserved_media_rules(downloaded_dir, preserved_rules)
                _replace_directory(downloaded_dir, target_dir)
                print(f"  ✅ {vendor}: 已同步 {rel_target}")
                if preserved_rules:
                    names = ", ".join(
                        f"Media/{name}" for name in sorted(preserved_rules)
                    )
                    print(f"     ↳ 已保留本地规则: {names}")
            except Exception as e:
                all_synced = False
                print(
                    f"  ⚠️ {vendor}: Provider 同步失败，"
                    f"继续使用本地文件：{e}"
                )

    if not all_synced:
        print("     ↳ Provider 部分失败，本次跳过 ASN 更新。")
        print()
        return False

    for label, url, rel_target, vendor in ASN_SYNC_TASKS:
        if not _target_matches(vendor, target):
            continue

        try:
            _replace_file(url, BASE_DIR / rel_target, label, download_file)
            print(f"  ✅ {label}: 已同步 {rel_target}")
        except Exception as e:
            all_synced = False
            print(f"  ⚠️ {label}: 同步失败，继续使用本地文件：{e}")

    print()
    return all_synced


def find_media_folder(vendor: str) -> Path:
    """
    查找 Clash/Surge 的 Provider 目录用于“合并”：
    优先使用 Rules/{vendor}/Provider/Media
    找不到则使用 Rules/{vendor}/Provider
    """
    candidates = [
        BASE_DIR / vendor / "Provider" / "Media",
        BASE_DIR / vendor / "Provider",
    ]
    for path in candidates:
        if path.is_dir():
            return path

    raise FileNotFoundError(
        f"[{vendor}] 找不到 Provider 目录：\n"
        f"  需存在 Rules/{vendor}/Provider/Media 或 Rules/{vendor}/Provider"
    )


def ensure_media_dir(vendor: str) -> Path:
    """
    确保存在 Rules/{vendor}/Provider/Media 目录：
    - 若已存在 Media：直接返回
    - 若只有 Provider：自动创建 Media
    - 若连 Provider 都没有：抛出异常
    """
    provider = BASE_DIR / vendor / "Provider"
    media = provider / "Media"

    if media.is_dir():
        return media
    if provider.is_dir():
        media.mkdir(exist_ok=True)
        return media

    raise FileNotFoundError(
        f"[{vendor}] 找不到 Provider 目录，无法创建 Media：\n"
        f"  需存在 Rules/{vendor}/Provider"
    )


def _append_blank_line(block: list[str]) -> list[str]:
    """确保每个文件块末尾至少有一个空行。"""
    if not block:
        return block
    if not block[-1].endswith("\n"):
        block[-1] = block[-1] + "\n"
    block.append("\n")
    return block


def organize_provider_media_rules() -> None:
    """
    在“合并媒体文件之前”整理 Provider：
      - Douyin.yaml / TikTok.yaml  → 移入 Clash/Provider/Media
      - Douyin.list / TikTok.list  → 移入 Surge/Provider/Media
    若目标 Media 目录已存在同名文件，则覆盖。
    源文件优先从这些位置查找：
      1) Rules 根目录
      2) Rules/{vendor}/Provider
      3) Rules/{vendor}
    """
    print("── 🔄 Provider 整理：移动 Douyin / TikTok 规则 ──")

    moved_any = False

    for vendor, filename in MEDIA_RULE_MOVE_TASKS:
        possible_sources = [
            BASE_DIR / filename,
            BASE_DIR / vendor / "Provider" / filename,
            BASE_DIR / vendor / filename,
        ]

        src = next(
            (candidate for candidate in possible_sources if candidate.is_file()),
            None,
        )

        if src is None:
            continue

        try:
            media_dir = ensure_media_dir(vendor)
        except FileNotFoundError as e:
            print(f"  ⚠️ {vendor}: {e}")
            continue

        dst = media_dir / filename
        action = "覆盖" if dst.exists() else "移动"

        dst.write_bytes(src.read_bytes())
        src.unlink(missing_ok=True)

        print(
            f"  • {vendor}: {action} {src.relative_to(BASE_DIR)} "
            f"→ {dst.relative_to(BASE_DIR)}"
        )
        moved_any = True

    if not moved_any:
        print("  • 无 Douyin/TikTok 更新，跳过。")
    else:
        print("  ✅ Provider 整理完成。")
    print()


def combine_streaming(
    vendor: str,
    extension: str,
    cn_file_set: set[str],
    out_cn_name: str,
    out_all_name: str,
    is_clash_yaml: bool = False,
) -> None:
    """
    通用合并函数：
    - vendor: "Clash" 或 "Surge"
    - extension: ".yaml" 或 ".list"
    - cn_file_set: 需要归入 StreamingCN 的文件名集合
    - out_cn_name: 输出的国内流媒体文件名
    - out_all_name: 输出的国际/其他流媒体文件名
    - is_clash_yaml: 是否为 Clash YAML（需要写 payload: 头，并去除子文件第一行 payload）
    """
    media_folder = find_media_folder(vendor)
    rel_media_folder = media_folder.relative_to(BASE_DIR)

    # 列出所有指定后缀的文件，排除输出文件自身
    files = sorted(
        f
        for f in media_folder.iterdir()
        if f.is_file()
        and f.suffix == extension
        and f.name not in {out_cn_name, out_all_name}
    )

    if not files:
        print(f"── 🧩 {vendor}: 未找到 *{extension} 规则文件，跳过 ──")
        return

    cn_files = {f.name for f in files} & cn_file_set
    cn_count = len(cn_files)
    total = len(files)
    other_count = total - cn_count

    out_cn_path = media_folder / out_cn_name
    out_all_path = media_folder / out_all_name

    print(f"── 🧩 {vendor} 合并 ──")
    print(f"  📁 目录: {rel_media_folder}")
    print(
        f"  📦 源文件: {total} 个 | CN: {cn_count} 个 → {out_cn_name} | "
        f"其它: {other_count} 个 → {out_all_name}"
    )

    with tempfile.TemporaryDirectory(
        prefix=f".{vendor.lower()}-combine-",
        dir=media_folder,
    ) as tmp:
        temp_dir = Path(tmp)
        temp_cn_path = temp_dir / out_cn_name
        temp_all_path = temp_dir / out_all_name

        with (
            temp_cn_path.open("w", encoding="utf-8") as cn_out,
            temp_all_path.open("w", encoding="utf-8") as all_out,
        ):
            # Clash 的 YAML 输出文件写入 payload: 头
            if is_clash_yaml:
                cn_out.write("payload:\n")
                all_out.write("payload:\n")

            for f in files:
                text = f.read_text(encoding="utf-8")
                if not text:
                    continue

                lines = text.splitlines(keepends=True)

                # Clash YAML：如果首行是 payload 或 payload:，就去掉
                if is_clash_yaml and lines:
                    first = lines[0].lstrip().lower()
                    if first.startswith("payload"):
                        lines = lines[1:]

                if not lines:
                    continue

                lines = _append_blank_line(lines)

                if f.name in cn_files:
                    cn_out.writelines(lines)
                else:
                    all_out.writelines(lines)

        temp_cn_path.replace(out_cn_path)
        temp_all_path.replace(out_all_path)

    print(
        "  ✅ 输出: "
        f"{out_cn_path.relative_to(BASE_DIR)}, "
        f"{out_all_path.relative_to(BASE_DIR)}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="合并 Clash / Surge 流媒体规则（支持 mac / Windows，相对路径）"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=["all", "clash", "surge"],
        help="要合并的目标：all（默认）、clash、surge",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="跳过远程同步，只整理并合并本地 Provider",
    )
    args = parser.parse_args()

    print("✨ Rules Sync Combiner")
    print(f"📂 根目录: {BASE_DIR}")
    print(f"🎯 目标: {args.target}\n")

    if args.no_sync:
        print("── 🌐 同步远程规则：已跳过（--no-sync）──\n")
    elif not sync_remote_rules(target=args.target):
        print("❌ 远程同步未完成，请稍后重新运行脚本。")
        return

    # 1. 先把 Douyin / TikTok 移入对应 Media
    organize_provider_media_rules()

    had_error = False

    for task in STREAMING_COMBINE_TASKS:
        if not _target_matches(task.vendor, args.target):
            continue

        try:
            combine_streaming(
                vendor=task.vendor,
                extension=task.extension,
                cn_file_set=task.cn_file_set,
                out_cn_name=task.out_cn_name,
                out_all_name=task.out_all_name,
                is_clash_yaml=task.is_clash_yaml,
            )
        except FileNotFoundError as e:
            had_error = True
            print(f"❌ {task.vendor} 合并失败: {e}\n")

    if not had_error:
        print("🎉 全部处理完成 ✅")
    else:
        print("⚠️ 处理结束（部分失败），请根据上方错误检查目录结构。")


if __name__ == "__main__":
    main()
