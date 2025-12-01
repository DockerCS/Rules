#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
from typing import Set

# 脚本所在目录 = Rules 根目录
BASE_DIR = Path(__file__).resolve().parent

# Clash 侧要归入 StreamingCN.yaml 的文件
CLASH_STREAMING_CN_FILES: Set[str] = {
    "Bilibili.yaml",
    "Douyin.yaml",
    "Emby.yaml",
    "IQ.yaml",
    "IQIYI.yaml",
    "Letv.yaml",
    "MOO.yaml",
    "Netease Music.yaml",
    "Tencent Video.yaml",
    "WeTV.yaml",
    "Youku.yaml",
}

# Surge 侧要归入 StreamingCN.list 的文件
SURGE_STREAMING_CN_FILES: Set[str] = {
    "Bilibili.list",
    "Douyin.list",
    "Emby.list",
    "IQ.list",
    "IQIYI.list",
    "Letv.list",
    "MOO.list",
    "Netease Music.list",
    "Tencent Video.list",
    "WeTV.list",
    "Youku.list",
}


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


def move_douyin_tiktok_into_media() -> None:
    """
    在“合并媒体文件之前”：
      - Douyin.yaml / TikTok.yaml  → 移入 Clash/Provider/Media
      - Douyin.list / TikTok.list  → 移入 Surge/Provider/Media
    若目标 Media 目录已存在同名文件，则覆盖。
    源文件优先从这些位置查找：
      1) Rules 根目录
      2) Rules/{vendor}/Provider
      3) Rules/{vendor}
    """
    print("── 🔄 预处理：移动 Douyin / TikTok 规则 ──")

    tasks = [
        ("Clash", "Douyin.yaml"),
        ("Clash", "TikTok.yaml"),
        ("Surge", "Douyin.list"),
        ("Surge", "TikTok.list"),
    ]

    moved_any = False

    for vendor, filename in tasks:
        possible_sources = [
            BASE_DIR / filename,
            BASE_DIR / vendor / "Provider" / filename,
            BASE_DIR / vendor / filename,
        ]

        src: Path | None = None
        for candidate in possible_sources:
            if candidate.is_file():
                src = candidate
                break

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
        print("  ✅ 预处理完成。")
    print("")


def combine_streaming(
    vendor: str,
    extension: str,
    cn_file_set: Set[str],
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

    cn_files = sorted({f.name for f in files if f.name in cn_file_set})
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

    with out_cn_path.open("w", encoding="utf-8") as cn_out, \
            out_all_path.open("w", encoding="utf-8") as all_out:

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
            if is_clash_yaml and len(lines) > 0:
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
    args = parser.parse_args()

    print("✨ Streaming Rules Combiner")
    print(f"📂 根目录: {BASE_DIR}")
    print(f"🎯 目标: {args.target}\n")

    # 1. 先把 Douyin / TikTok 移入对应 Media
    move_douyin_tiktok_into_media()

    had_error = False

    if args.target in ("all", "clash"):
        try:
            combine_streaming(
                vendor="Clash",
                extension=".yaml",
                cn_file_set=CLASH_STREAMING_CN_FILES,
                out_cn_name="StreamingCN.yaml",
                out_all_name="Streaming.yaml",
                is_clash_yaml=True,
            )
        except FileNotFoundError as e:
            had_error = True
            print(f"❌ Clash 合并失败: {e}\n")

    if args.target in ("all", "surge"):
        try:
            combine_streaming(
                vendor="Surge",
                extension=".list",
                cn_file_set=SURGE_STREAMING_CN_FILES,
                out_cn_name="StreamingCN.list",
                out_all_name="Streaming.list",
                is_clash_yaml=False,
            )
        except FileNotFoundError as e:
            had_error = True
            print(f"❌ Surge 合并失败: {e}\n")

    if not had_error:
        print("🎉 全部处理完成 ✅")
    else:
        print("⚠️ 处理结束（部分失败），请根据上方错误检查目录结构。")


if __name__ == "__main__":
    main()
