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


class VendorConfig(NamedTuple):
    vendor: str
    extension: str
    provider_archive_subdir: Path
    is_clash_yaml: bool


class ProviderSyncTask(NamedTuple):
    vendor: str
    source: GitHubArchiveTree
    target: Path


class DirectSyncTask(NamedTuple):
    label: str
    url: str
    target: Path
    vendor: str


class StreamingCombineTask(NamedTuple):
    vendor: str
    extension: str
    cn_file_set: set[str]
    out_cn_name: str
    out_all_name: str
    is_clash_yaml: bool


DLER_RULES_ARCHIVE_URL = "https://github.com/dler-io/Rules/archive/refs/heads/main.zip"
GET_SOME_FRIES_RAW_URL = (
    "https://raw.githubusercontent.com/VirgilClyne/GetSomeFries/main/ruleset"
)
BLACKMATRIX7_RAW_URL = (
    "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/"
    "master/rule"
)
KEEP_EXISTING = True
REMOVE_INCOMPLETE = False

VENDOR_CONFIGS = (
    VendorConfig("Clash", ".yaml", Path("Clash/Provider"), True),
    VendorConfig("Surge", ".list", Path("Surge/Surge 3/Provider"), False),
)

PROVIDER_SYNC_TASKS = tuple(
    ProviderSyncTask(
        config.vendor,
        GitHubArchiveTree(DLER_RULES_ARCHIVE_URL, config.provider_archive_subdir),
        Path(config.vendor) / "Provider",
    )
    for config in reversed(VENDOR_CONFIGS)
)

ASN_SYNC_TASKS = tuple(
    DirectSyncTask(
        f"{config.vendor} ASNChina{config.extension}",
        f"{GET_SOME_FRIES_RAW_URL}/ASN.China{config.extension}",
        Path(config.vendor) / "Provider" / f"ASNChina{config.extension}",
        config.vendor,
    )
    for config in reversed(VENDOR_CONFIGS)
)

BLACKMATRIX7_TIKTOK_SYNC_TASKS = tuple(
    DirectSyncTask(
        f"{config.vendor} blackmatrix7 TikTok{config.extension}",
        f"{BLACKMATRIX7_RAW_URL}/{config.vendor}/TikTok/TikTok{config.extension}",
        Path(config.vendor) / "Provider" / "Media" / f"TikTok{config.extension}",
        config.vendor,
    )
    for config in reversed(VENDOR_CONFIGS)
)

MEDIA_RULE_MOVE_TASKS = tuple(
    (config.vendor, f"{basename}{config.extension}")
    for config in VENDOR_CONFIGS
    for basename in ("Douyin", "TikTok")
)

PRESERVED_MEDIA_RULES = {
    config.vendor: (f"Emby{config.extension}",)
    for config in VENDOR_CONFIGS
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

STREAMING_CN_FILES = {
    config.vendor: {
        f"{basename}{config.extension}"
        for basename in STREAMING_CN_BASENAMES
    }
    for config in VENDOR_CONFIGS
}
CLASH_STREAMING_CN_FILES = STREAMING_CN_FILES["Clash"]
SURGE_STREAMING_CN_FILES = STREAMING_CN_FILES["Surge"]

STREAMING_COMBINE_TASKS = tuple(
    StreamingCombineTask(
        config.vendor,
        config.extension,
        STREAMING_CN_FILES[config.vendor],
        f"StreamingCN{config.extension}",
        f"Streaming{config.extension}",
        config.is_clash_yaml,
    )
    for config in VENDOR_CONFIGS
)


def _target_matches(vendor: str, target: str) -> bool:
    return target == "all" or target == vendor.lower()


def download_url(url: str, target: Path) -> None:
    """下载文件；Python 证书链异常时回退到系统 curl。"""
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


def _download_direct_file(
    source_url: str,
    target: Path,
    label: str,
    download_file: DownloadFile,
) -> None:
    """直接下载到最终路径；失败时删除空文件或不完整文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_file(source_url, target)
        _ensure_non_empty_file(target, label)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _sync_direct_rules(
    target: str,
    download_file: DownloadFile,
) -> bool:
    """同步单文件任务，并按任务策略处理失败目标。"""
    all_synced = True

    task_groups = (
        (ASN_SYNC_TASKS, KEEP_EXISTING),
        (BLACKMATRIX7_TIKTOK_SYNC_TASKS, REMOVE_INCOMPLETE),
    )
    for tasks, keep_existing in task_groups:
        for task in tasks:
            if not _target_matches(task.vendor, target):
                continue

            destination = BASE_DIR / task.target
            try:
                if keep_existing:
                    _replace_file(
                        task.url,
                        destination,
                        task.label,
                        download_file,
                    )
                else:
                    _download_direct_file(
                        task.url,
                        destination,
                        task.label,
                        download_file,
                    )
                print(f"  ✅ {task.label}: 已同步 {task.target}")
            except Exception as e:
                all_synced = False
                failure_action = (
                    "继续使用本地文件"
                    if keep_existing
                    else "已删除不完整文件"
                )
                print(
                    f"  ⚠️ {task.label}: 同步失败，"
                    f"{failure_action}：{e}"
                )

    return all_synced


def sync_remote_rules(
    target: str = "all",
    download_file: DownloadFile | None = None,
) -> bool:
    """同步 Provider、ASNChina 和 blackmatrix7 TikTok 规则。"""
    download_file = download_file or download_url

    print("── 🌐 同步远程规则 ──")
    all_synced = True
    provider_tasks = tuple(
        task
        for task in PROVIDER_SYNC_TASKS
        if _target_matches(task.vendor, target)
    )

    with tempfile.TemporaryDirectory(prefix="rules-provider-") as tmp:
        workspace = Path(tmp)
        repository_root: Path | None = None

        if provider_tasks:
            try:
                repository_root = _extract_github_archive(
                    provider_tasks[0].source.archive_url,
                    workspace / "archive",
                )
            except Exception as e:
                vendors = ", ".join(task.vendor for task in provider_tasks)
                print(
                    f"  ⚠️ {vendors}: Provider 归档下载失败，"
                    f"本次保留本地文件：{e}"
                )
                print(
                    "     ↳ 已跳过 ASN 与 blackmatrix7 TikTok 更新，"
                    "重新运行脚本即可重试。"
                )
                print()
                return False

        for index, task in enumerate(provider_tasks):
            target_dir = BASE_DIR / task.target
            downloaded_dir = (
                workspace / f"{index}-{task.vendor.lower()}-Provider"
            )
            try:
                preserved_rules = _read_preserved_media_rules(
                    target_dir,
                    task.vendor,
                )
                assert repository_root is not None
                _copy_github_archive_tree(
                    task.source,
                    repository_root,
                    downloaded_dir,
                )
                _ensure_non_empty_dir(
                    downloaded_dir,
                    f"{task.vendor} Provider",
                )
                _restore_preserved_media_rules(downloaded_dir, preserved_rules)
                _replace_directory(downloaded_dir, target_dir)
                print(f"  ✅ {task.vendor}: 已同步 {task.target}")
                if preserved_rules:
                    names = ", ".join(
                        f"Media/{name}" for name in sorted(preserved_rules)
                    )
                    print(f"     ↳ 已保留本地规则: {names}")
            except Exception as e:
                all_synced = False
                print(
                    f"  ⚠️ {task.vendor}: Provider 同步失败，"
                    f"继续使用本地文件：{e}"
                )

    if not all_synced:
        print(
            "     ↳ Provider 部分失败，本次跳过 ASN 与 "
            "blackmatrix7 TikTok 更新。"
        )
        print()
        return False

    all_synced = _sync_direct_rules(
        target,
        download_file,
    )
    print()
    return all_synced


def _media_folder(vendor: str, create: bool = False) -> Path:
    """返回媒体目录；合并时可回退 Provider，整理时可创建 Media。"""
    provider = BASE_DIR / vendor / "Provider"
    media = provider / "Media"

    if media.is_dir():
        return media
    if provider.is_dir():
        if create:
            media.mkdir()
            return media
        return provider

    detail = (
        f"  需存在 Rules/{vendor}/Provider"
        if create
        else f"  需存在 Rules/{vendor}/Provider/Media 或 Rules/{vendor}/Provider"
    )
    action = "，无法创建 Media" if create else ""
    raise FileNotFoundError(f"[{vendor}] 找不到 Provider 目录{action}：\n{detail}")


def find_media_folder(vendor: str) -> Path:
    return _media_folder(vendor)


def ensure_media_dir(vendor: str) -> Path:
    return _media_folder(vendor, create=True)


def _read_rule_block(path: Path, is_clash_yaml: bool) -> str:
    """读取单个规则文件，并规范化为可直接合并的文本块。"""
    text = path.read_text(encoding="utf-8")
    if not text:
        return ""

    lines = text.splitlines(keepends=True)
    if is_clash_yaml and lines[0].lstrip().lower().startswith("payload"):
        lines = lines[1:]

    block = "".join(lines)
    if not block:
        return ""
    return block + ("" if block.endswith("\n") else "\n") + "\n"


def _write_streaming_file(
    target: Path,
    sources: list[Path],
    is_clash_yaml: bool,
) -> None:
    """将一组规则文件按既定顺序写入单个合并文件。"""
    header = "payload:\n" if is_clash_yaml else ""
    blocks = (_read_rule_block(source, is_clash_yaml) for source in sources)
    target.write_text(header + "".join(blocks), encoding="utf-8")


def _tiktok_rule_from_line(line: str, is_clash_yaml: bool) -> str | None:
    """提取用于去重的 TikTok 规则；忽略空行、注释和 Clash payload 头。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if is_clash_yaml and stripped.rstrip(":").lower() == "payload":
        return None
    if is_clash_yaml and stripped.startswith("-"):
        stripped = stripped[1:].lstrip()
    return stripped or None


def _merge_tiktok_text(
    dler_text: str,
    blackmatrix7_text: str,
    is_clash_yaml: bool,
) -> str:
    """
    合并两份 TikTok 规则。

    dler-io 的规则与注释保持在前；blackmatrix7 只追加未出现过的有效规则，
    丢弃其注释、空行以及 Clash payload 头。
    """
    output_lines = ["payload:"] if is_clash_yaml else []
    seen_rules: set[str] = set()

    for line in dler_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            output_lines.append(line.rstrip())
            continue

        rule = _tiktok_rule_from_line(line, is_clash_yaml)
        if rule is None or rule in seen_rules:
            continue
        seen_rules.add(rule)
        output_lines.append(f"  - {rule}" if is_clash_yaml else rule)

    blackmatrix7_rule_count = 0
    for line in blackmatrix7_text.splitlines():
        rule = _tiktok_rule_from_line(line, is_clash_yaml)
        if rule is None:
            continue
        blackmatrix7_rule_count += 1
        if rule in seen_rules:
            continue
        seen_rules.add(rule)
        output_lines.append(f"  - {rule}" if is_clash_yaml else rule)

    if blackmatrix7_rule_count == 0:
        raise RuntimeError("blackmatrix7 TikTok 文件中没有有效规则")
    if not seen_rules:
        raise RuntimeError("TikTok 合并结果中没有有效规则")

    return "\n".join(output_lines) + "\n"


def _merge_tiktok_rule_files(
    dler_source: Path,
    blackmatrix7_target: Path,
    is_clash_yaml: bool,
) -> None:
    """合并两份 TikTok 文件，成功写入后才删除 dler-io 源文件。"""
    dler_text = dler_source.read_text(encoding="utf-8")
    blackmatrix7_text = blackmatrix7_target.read_text(encoding="utf-8")
    merged_text = _merge_tiktok_text(
        dler_text,
        blackmatrix7_text,
        is_clash_yaml,
    )
    written = blackmatrix7_target.write_text(merged_text, encoding="utf-8")
    if written != len(merged_text):
        raise OSError(f"TikTok 合并结果未完整写入: {blackmatrix7_target}")
    dler_source.unlink()


def organize_provider_media_rules() -> None:
    """按根目录、Provider、vendor 的优先级整理 Douyin/TikTok。"""
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
        should_merge_tiktok = filename.startswith("TikTok.") and dst.is_file()
        if should_merge_tiktok:
            _merge_tiktok_rule_files(
                src,
                dst,
                is_clash_yaml=filename.endswith(".yaml"),
            )
            action = "合并"
        else:
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
    """将 vendor 的媒体规则分类合并为 StreamingCN 和 Streaming。"""
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

    cn_files = [file for file in files if file.name in cn_file_set]
    other_files = [file for file in files if file.name not in cn_file_set]
    cn_count = len(cn_files)
    total = len(files)
    other_count = len(other_files)

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

        _write_streaming_file(
            temp_cn_path,
            cn_files,
            is_clash_yaml,
        )
        _write_streaming_file(
            temp_all_path,
            other_files,
            is_clash_yaml,
        )

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

    # 1. 整理 Douyin，并合并 dler-io 与 blackmatrix7 TikTok
    organize_provider_media_rules()

    had_error = False

    for task in STREAMING_COMBINE_TASKS:
        if not _target_matches(task.vendor, args.target):
            continue

        try:
            combine_streaming(**task._asdict())
        except FileNotFoundError as e:
            had_error = True
            print(f"❌ {task.vendor} 合并失败: {e}\n")

    if not had_error:
        print("🎉 全部处理完成 ✅")
    else:
        print("⚠️ 处理结束（部分失败），请根据上方错误检查目录结构。")


if __name__ == "__main__":
    main()
