#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple

# 脚本所在目录 = Rules 根目录
BASE_DIR = Path(__file__).resolve().parent


class VendorConfig(NamedTuple):
    vendor: str
    extension: str
    provider_archive_subdir: Path
    is_clash_yaml: bool


DLER_RULES_ARCHIVE_URL = "https://github.com/dler-io/Rules/archive/refs/heads/main.zip"
GET_SOME_FRIES_RAW_URL = (
    "https://raw.githubusercontent.com/VirgilClyne/GetSomeFries/main/ruleset"
)
BLACKMATRIX7_RAW_URL = (
    "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule"
)

VENDOR_CONFIGS = (
    VendorConfig("Clash", ".yaml", Path("Clash/Provider"), True),
    VendorConfig("Surge", ".list", Path("Surge/Surge 3/Provider"), False),
)

STREAMING_CN_BASENAMES = {
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


def download_url(url: str, target: Path) -> None:
    """使用 curl 下载，非空文件才替换目标；失败时清理临时文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.sync-", dir=target.parent) as tmp:
        staging = Path(tmp) / target.name
        subprocess.run(
            [
                "curl", "-sS", "-fL", "--retry", "3",
                "--connect-timeout", "15", "--max-time", "180",
                "-A", "Rules-Sync-Combiner", "-o", str(staging), url,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if staging.stat().st_size == 0:
            raise RuntimeError(f"下载结果为空: {url}")
        staging.replace(target)


def _extract_github_archive(workspace: Path) -> Path:
    """下载并解压 GitHub 分支归档，返回唯一的仓库根目录。"""
    archive = workspace / "source.zip"
    extract_dir = workspace / "extract"
    download_url(DLER_RULES_ARCHIVE_URL, archive)
    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(extract_dir)

    roots = [path for path in extract_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError("GitHub 压缩包需包含唯一的仓库目录")
    return roots[0]


def _sync_provider(repository_root: Path, config: VendorConfig) -> None:
    """直接复制到目标同盘暂存目录，保留本地 Emby 后替换 Provider。"""
    target = BASE_DIR / config.vendor / "Provider"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".Provider.sync-", dir=target.parent) as tmp:
        workspace = Path(tmp)
        staging = workspace / "new"
        previous = workspace / "old"
        shutil.copytree(repository_root / config.provider_archive_subdir, staging)
        if not any(staging.iterdir()):
            raise RuntimeError(f"{config.vendor} Provider 下载结果为空")

        emby = target / "Media" / f"Emby{config.extension}"
        preserved_emby = emby.is_file()
        if preserved_emby:
            (staging / "Media").mkdir(exist_ok=True)
            shutil.copyfile(emby, staging / "Media" / emby.name)

        had_target = target.exists() or target.is_symlink()
        if had_target:
            target.rename(previous)
        try:
            staging.rename(target)
        except OSError:
            if had_target and not (target.exists() or target.is_symlink()):
                previous.rename(target)
            raise

    print(f"  ✅ {config.vendor}: 已同步 {target.relative_to(BASE_DIR)}")
    if preserved_emby:
        print(f"     ↳ 已保留本地规则: Media/{emby.name}")


def sync_remote_rules(configs: tuple[VendorConfig, ...]) -> None:
    """同步所选平台的 Provider、ASNChina 和 blackmatrix7 TikTok；失败即停止。"""
    print("── 🌐 同步远程规则 ──")
    with tempfile.TemporaryDirectory(prefix="rules-provider-") as tmp:
        repository_root = _extract_github_archive(Path(tmp))
        for config in configs:
            _sync_provider(repository_root, config)

    for config in configs:
        provider = BASE_DIR / config.vendor / "Provider"
        extension = config.extension
        asn = provider / f"ASNChina{extension}"
        download_url(f"{GET_SOME_FRIES_RAW_URL}/ASN.China{extension}", asn)
        print(f"  ✅ {config.vendor}: 已同步 {asn.relative_to(BASE_DIR)}")

        tiktok = provider / "Media" / f"TikTok{extension}"
        # 此位置必须来自 blackmatrix7，下载失败后不能留下上游同名文件供合并。
        tiktok.unlink(missing_ok=True)
        download_url(
            f"{BLACKMATRIX7_RAW_URL}/{config.vendor}/TikTok/TikTok{extension}",
            tiktok,
        )
        print(f"  ✅ {config.vendor}: 已同步 {tiktok.relative_to(BASE_DIR)}")
    print()


def _read_rule_block(path: Path, is_clash_yaml: bool) -> str:
    """移除 Clash 文件头，并保留原有内容及文件间的空行。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if is_clash_yaml and lines and lines[0].lstrip().lower().startswith("payload"):
        lines = lines[1:]
    block = "".join(lines)
    if not block:
        return ""
    return block + ("" if block.endswith("\n") else "\n") + "\n"


def _tiktok_rule_from_line(line: str, is_clash_yaml: bool) -> str | None:
    """提取 TikTok 规则，忽略空行、注释和 Clash payload 头。"""
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
    """保留 dler-io 规则与注释在前，仅追加 blackmatrix7 中未出现的有效规则。"""
    output_lines = ["payload:"] if is_clash_yaml else []
    seen_rules: set[str] = set()
    for text, is_blackmatrix7 in ((dler_text, False), (blackmatrix7_text, True)):
        rule_count = 0
        for line in text.splitlines():
            if not is_blackmatrix7 and line.lstrip().startswith("#"):
                output_lines.append(line.rstrip())
                continue
            rule = _tiktok_rule_from_line(line, is_clash_yaml)
            if rule is None:
                continue
            rule_count += 1
            if rule not in seen_rules:
                seen_rules.add(rule)
                output_lines.append(f"  - {rule}" if is_clash_yaml else rule)

        if is_blackmatrix7 and rule_count == 0:
            raise RuntimeError("blackmatrix7 TikTok 文件中没有有效规则")
    return "\n".join(output_lines) + "\n"


def organize_provider_media_rules(config: VendorConfig) -> None:
    """将所选平台 Provider 中的 Douyin/TikTok 整理到 Media。"""
    print(f"── 🔄 {config.vendor}: 整理 Douyin / TikTok 规则 ──")
    provider = BASE_DIR / config.vendor / "Provider"
    media = provider / "Media"
    for basename in ("Douyin", "TikTok"):
        source = provider / f"{basename}{config.extension}"
        if not source.is_file():
            continue
        media.mkdir(exist_ok=True)
        destination = media / source.name
        if basename == "TikTok" and destination.is_file():
            merged = _merge_tiktok_text(
                source.read_text(encoding="utf-8"),
                destination.read_text(encoding="utf-8"),
                config.is_clash_yaml,
            )
            with tempfile.TemporaryDirectory(prefix=".tiktok-merge-", dir=media) as tmp:
                staging = Path(tmp) / source.name
                staging.write_text(merged, encoding="utf-8")
                staging.replace(destination)
            source.unlink()
            action = "合并"
        else:
            action = "覆盖" if destination.exists() else "移动"
            source.replace(destination)
        print(
            f"  • {action} {source.relative_to(BASE_DIR)} "
            f"→ {destination.relative_to(BASE_DIR)}"
        )
    print()


def combine_streaming(config: VendorConfig) -> None:
    """将 Media 规则按名称分类，分别写入 StreamingCN 和 Streaming。"""
    media = BASE_DIR / config.vendor / "Provider" / "Media"
    out_cn_name = f"StreamingCN{config.extension}"
    out_all_name = f"Streaming{config.extension}"
    files = sorted(
        path for path in media.iterdir()
        if path.is_file()
        and path.suffix == config.extension
        and path.name not in {out_cn_name, out_all_name}
    )
    if not files:
        print(f"── 🧩 {config.vendor}: 未找到 *{config.extension} 规则文件，跳过 ──")
        return

    groups = {
        out_cn_name: [path for path in files if path.stem in STREAMING_CN_BASENAMES],
        out_all_name: [path for path in files if path.stem not in STREAMING_CN_BASENAMES],
    }
    print(f"── 🧩 {config.vendor} 合并 ──")
    print(f"  📁 目录: {media.relative_to(BASE_DIR)}")
    print(
        f"  📦 源文件: {len(files)} 个 | CN: {len(groups[out_cn_name])} 个 → {out_cn_name} | "
        f"其它: {len(groups[out_all_name])} 个 → {out_all_name}"
    )

    header = "payload:\n" if config.is_clash_yaml else ""
    with tempfile.TemporaryDirectory(prefix=".streaming-combine-", dir=media) as tmp:
        staging = Path(tmp)
        for filename, sources in groups.items():
            blocks = (_read_rule_block(source, config.is_clash_yaml) for source in sources)
            (staging / filename).write_text(header + "".join(blocks), encoding="utf-8")
        for filename in groups:
            (staging / filename).replace(media / filename)
    print(f"  ✅ 输出: {out_cn_name}, {out_all_name}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步并合并 Clash / Surge 流媒体规则（需要 curl）"
    )
    parser.add_argument(
        "target", nargs="?", default="all", choices=["all", "clash", "surge"],
        help="要处理的目标：all（默认）、clash、surge",
    )
    parser.add_argument(
        "--no-sync", action="store_true",
        help="跳过远程同步，只整理并合并本地 Provider",
    )
    args = parser.parse_args()
    configs = tuple(
        config for config in VENDOR_CONFIGS
        if args.target == "all" or args.target == config.vendor.lower()
    )
    print("✨ Rules Sync Combiner")
    print(f"📂 根目录: {BASE_DIR}")
    print(f"🎯 目标: {args.target}\n")

    try:
        if args.no_sync:
            print("── 🌐 同步远程规则：已跳过（--no-sync）──\n")
        else:
            sync_remote_rules(configs)
        for config in configs:
            organize_provider_media_rules(config)
            combine_streaming(config)
    except (
        OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile, UnicodeError
    ) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        print(f"❌ 处理失败: {detail}", file=sys.stderr)
        return 1

    print("🎉 全部处理完成 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
