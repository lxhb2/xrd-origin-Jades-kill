#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an editable XRD stacked plot in a local Origin/OriginPro install."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

VERSION = "1.3.0"
DEFAULT_COLORS = ["#1F4E79", "#C1543A", "#222222", "#7A5EA8", "#C9A227", "#2F8F9D"]
DEFAULT_CARD_COLORS = ["#8E6BBE", "#4FA65A", "#F0A35E", "#4C9DB8", "#B07AA1", "#7B8B3A"]
ORIGIN_MARKER_KINDS = [1, 4, 2, 3, 5, 6]


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


_configure_console()


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise SystemExit(f"空表：{path}")
    return rows[0], rows[1:]


def _read_annotations(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _columns_as_pairs(path: Path) -> list[tuple[str, list[float], str, list[float]]]:
    headers, rows = _read_csv(path)
    if len(headers) % 2:
        raise SystemExit(f"{path.name} 应为成对的 X/Y 列，但表头有 {len(headers)} 列。")
    pairs = []
    for index in range(0, len(headers), 2):
        xs: list[float] = []
        ys: list[float] = []
        for row in rows:
            if len(row) <= index + 1:
                continue
            x_text, y_text = row[index].strip(), row[index + 1].strip()
            if not x_text or not y_text:
                continue
            try:
                x_value, y_value = float(x_text), float(y_text)
            except ValueError:
                continue
            if math.isfinite(x_value) and math.isfinite(y_value):
                xs.append(x_value)
                ys.append(y_value)
        if xs:
            pairs.append((headers[index], xs, headers[index + 1], ys))
    if not pairs:
        raise SystemExit(f"{path.name} 没有读到有效数值列。")
    return pairs


def _origin_running() -> bool:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Origin64.exe", "/FO", "CSV", "/NH"],
            text=True,
            encoding="gbk",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    return "Origin64.exe" in output


def _load_manifest(origin_dir: Path) -> dict[str, Any]:
    manifest = origin_dir.parent / "manifest.json"
    if not manifest.exists():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _add_graph_label(layer: Any, text: str, x: float, y: float, color: str) -> None:
    """Add a simple editable text label, but do not fail the graph if Origin blocks it."""
    try:
        label = layer.add_label(text, x, y)
        if label is not None:
            label.color = color
    except Exception:
        return


def _card_baselines(
    card_count: int,
    sample_offsets: list[float],
    gap: float,
    row_height: float,
) -> list[float]:
    """Place every card in its own row below the stacked XRD patterns."""
    if not sample_offsets:
        start = 0.0
    else:
        start = min(sample_offsets) - 0.56 * (1.0 + gap)
    step = max(0.34, row_height)
    return [start - index * step for index in range(card_count)]


def _build_graph(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import originpro as op
    except ImportError as exc:
        raise SystemExit(
            "缺少 originpro。请在本机 Origin 对应的 Python 环境里运行：\n"
            f'  "{sys.executable}" -m pip install originpro'
        ) from exc

    origin_dir = Path(args.origin_dir).expanduser().resolve()
    samples_path = origin_dir / "Sheet1_samples.csv"
    cards_path = origin_dir / "Sheet2_cards.csv"
    if not samples_path.exists():
        raise SystemExit(f"找不到样例数据：{samples_path}")

    samples = _columns_as_pairs(samples_path)
    cards = _columns_as_pairs(cards_path) if cards_path.exists() else []
    manifest = _load_manifest(origin_dir)
    layout = manifest.get("layout", {}) if isinstance(manifest, dict) else {}
    manifest_cards = manifest.get("cards", []) if isinstance(manifest, dict) else []
    peak_marking = (
        manifest.get("peak_marking", {}).get("mode", "none")
        if isinstance(manifest, dict)
        else "none"
    )
    annotations = _read_annotations(origin_dir / "Sheet3_peak_annotations.csv")
    single_sample = bool(layout.get("single_sample", False))
    hide_card_sticks = single_sample and peak_marking in {"markers", "hkl"}
    if args.card_row_height is None:
        args.card_row_height = float(layout.get("card_row_height", 0.40))
    if args.stick_height is None:
        args.stick_height = float(layout.get("stick_height", 0.58))
    if args.card_min_intensity is None:
        args.card_min_intensity = float(layout.get("card_min_intensity", 5.0))
    offsets = [float(value) for value in manifest.get("offsets", [])]
    if len(offsets) != len(samples):
        gap = float(manifest.get("gap", 0.75))
        offsets = [index * (1.0 + gap) for index in range(len(samples))]

    op.set_show(bool(args.show))
    op.new()
    sample_sheet = op.new_sheet("w", lname="XRD_Samples")
    card_sheet = None if hide_card_sticks else op.new_sheet("w", lname="PDF_Cards")

    for index, (_, xs, label, ys) in enumerate(samples):
        shifted = [value + offsets[index] for value in ys]
        sample_sheet.from_list(index * 2, xs, lname=f"2theta_{index + 1}", axis="X")
        sample_sheet.from_list(index * 2 + 1, shifted, lname=label, axis="Y")

    gap = float(manifest.get("gap", 0.75))
    if args.x_range:
        x_min, x_max = args.x_range
    else:
        all_x = [x for _, xs, _, _ in samples for x in xs]
        if not hide_card_sticks:
            all_x.extend(x for _, xs, _, _ in cards for x in xs)
        x_min, x_max = (min(all_x), max(all_x)) if all_x else (0.0, 1.0)
    card_bases = (
        []
        if hide_card_sticks
        else _card_baselines(len(cards), offsets, gap, args.card_row_height)
    )
    card_metadata: list[dict[str, Any]] = []
    if not hide_card_sticks and card_sheet is not None:
        for index, (_, xs, label, ys) in enumerate(cards):
            manifest_card = manifest_cards[index] if index < len(manifest_cards) else {}
            display_label = str(manifest_card.get("formula") or label)
            x_sticks: list[float] = []
            y_sticks: list[float] = []
            base = card_bases[index]
            for x_value, intensity in zip(xs, ys):
                if intensity < args.card_min_intensity:
                    continue
                height = (
                    args.card_row_height
                    * args.stick_height
                    * max(0.0, min(100.0, intensity))
                    / 100.0
                )
                x_sticks.extend([x_value, x_value])
                y_sticks.extend([base, base + height])
            # The final pair is the horizontal baseline for this card layer.
            x_sticks.extend([x_min, x_max])
            y_sticks.extend([base, base])
            card_sheet.from_list(index * 2, x_sticks, lname=f"card{index + 1}_2theta", axis="X")
            card_sheet.from_list(index * 2 + 1, y_sticks, lname=display_label, axis="Y")
            card_metadata.append(
                {"label": display_label, "baseline": base, "row_height": args.card_row_height}
            )

    graph = op.new_graph(template="LINE", lname="XRD_Stack")
    layer = graph[0]
    plots = []
    for index, (_, _, label, _) in enumerate(samples):
        plot = layer.add_plot(sample_sheet, index * 2 + 1, index * 2, type="l")
        plot.color = DEFAULT_COLORS[index % len(DEFAULT_COLORS)]
        plot.set_cmd("-w 2000")
        plots.append(plot)
    if not hide_card_sticks and card_sheet is not None:
        for index, _ in enumerate(cards):
            # Each card peak is stored as an x-y pair followed by the same x and a
            # higher y. LabTalk connection method 2 ("segment") draws every pair
            # independently, yielding one vertical stick per standard peak. A
            # normal line connection would add horizontal segments between peaks.
            plot = layer.add_plot(card_sheet, index * 2 + 1, index * 2, type="l")
            plot.color = DEFAULT_CARD_COLORS[index % len(DEFAULT_CARD_COLORS)]
            plot.set_cmd("-l 2", "-w 1100")
            plots.append(plot)

    if args.sample_labels and len(samples) > 1:
        label_x = x_min + 0.88 * (x_max - x_min)
        for index, (_, _, label, _) in enumerate(samples):
            _add_graph_label(
                layer,
                label,
                label_x,
                offsets[index] + 0.56,
                DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
            )
    if args.card_labels and not hide_card_sticks:
        label_x = x_min + 0.73 * (x_max - x_min)
        for index, item in enumerate(card_metadata):
            _add_graph_label(
                layer,
                item["label"],
                label_x,
                card_bases[index] + 0.64 * args.stick_height * args.card_row_height,
                DEFAULT_CARD_COLORS[index % len(DEFAULT_CARD_COLORS)],
            )

    annotation_metadata: list[dict[str, Any]] = []
    if peak_marking == "markers" and annotations:
        annotation_sheet = op.new_sheet("w", lname="Peak_Annotations")
        groups: dict[int, list[dict[str, str]]] = {}
        for item in annotations:
            if item.get("kind") != "marker":
                continue
            try:
                group_index = int(item.get("card_index", "0"))
            except ValueError:
                group_index = 0
            groups.setdefault(group_index, []).append(item)
        for plot_index, (card_index, items) in enumerate(groups.items()):
            xs = [float(item["observed_two_theta"]) for item in items]
            ys = [float(item["plot_y"]) for item in items]
            legend = items[0].get("legend") or items[0].get("formula", "")
            annotation_sheet.from_list(
                plot_index * 2,
                xs,
                lname=f"annotation{plot_index + 1}_x",
                axis="X",
            )
            annotation_sheet.from_list(
                plot_index * 2 + 1,
                ys,
                lname=legend,
                axis="Y",
            )
            plot = layer.add_plot(
                annotation_sheet,
                plot_index * 2 + 1,
                plot_index * 2,
                type="s",
            )
            plot.color = items[0].get(
                "color",
                DEFAULT_CARD_COLORS[card_index % len(DEFAULT_CARD_COLORS)],
            )
            plot.symbol_kind = ORIGIN_MARKER_KINDS[
                card_index % len(ORIGIN_MARKER_KINDS)
            ]
            plot.symbol_interior = 1
            plot.symbol_size = 8
            annotation_metadata.append(
                {"kind": "marker", "label": legend, "points": len(items)}
            )
    elif peak_marking == "hkl" and annotations:
        for item in annotations:
            if item.get("kind") != "hkl":
                continue
            hkl_label = f"({item.get('hkl', '').strip()})"
            _add_graph_label(
                layer,
                hkl_label,
                float(item["observed_two_theta"]),
                float(item["plot_y"]),
                "#222222",
            )
            annotation_metadata.append(
                {"kind": "hkl", "label": hkl_label, "points": 1}
            )

    layer.axis("x").title = args.xlabel
    layer.axis("y").title = args.ylabel
    layer.set_xlim(x_min, x_max)
    layer.rescale()

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    opju_path = out_dir / "xrd_origin.opju"
    png_path = out_dir / "xrd_origin.png"
    pdf_path = out_dir / "xrd_origin.pdf"
    graph.save_fig(str(png_path), type="png", width=args.png_width)
    graph.save_fig(str(pdf_path), type="pdf")
    op.save(str(opju_path))

    metadata = {
        "generator": f"origin_stack.py v{VERSION}",
        "origin_dir": str(origin_dir),
        "out_dir": str(out_dir),
        "samples": [{"label": label, "points": len(xs), "offset": offsets[index]}
                    for index, (_, xs, label, _) in enumerate(samples)],
        "cards": card_metadata,
        "peak_marking": {
            "mode": peak_marking,
            "annotations": annotation_metadata,
        },
        "layout": {
            "card_position": "bottom",
            "card_row_height": args.card_row_height,
            "stick_height": args.stick_height,
            "card_min_intensity": args.card_min_intensity,
        },
        "outputs": {
            "opju": str(opju_path),
            "png": str(png_path),
            "pdf": str(pdf_path),
        },
        "note": "曲线使用逐条 Y 平移实现可编辑堆叠；PDF 卡片统一放在下方并按行分层。",
    }
    (out_dir / "origin_run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin_stack.py",
        description="把 xrd_stack.py 导出的 Origin 数据表做成可编辑 OPJU 堆叠图。",
    )
    parser.add_argument("--origin-dir", required=True, help="包含 Sheet1_samples.csv / Sheet2_cards.csv 的目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--x-range", type=float, nargs=2, default=None, metavar=("MIN", "MAX"))
    parser.add_argument("--xlabel", default="2\u03b8 (\u00b0)")
    parser.add_argument("--ylabel", default="Intensity (a.u.)")
    parser.add_argument("--card-row-height", type=float, default=None,
                        help="卡片分层行高；默认沿用 xrd_stack.py 的 manifest")
    parser.add_argument("--stick-height", type=float, default=None,
                        help="卡片竖线占卡片行高的比例；默认沿用 manifest")
    parser.add_argument("--card-min-intensity", type=float, default=None,
                        help="只显示相对强度不低于该值的卡片棒线；默认沿用 manifest")
    parser.add_argument("--card-labels", action="store_true", default=True,
                        help="显示卡片名称（默认显示）")
    parser.add_argument("--no-card-labels", dest="card_labels", action="store_false")
    parser.add_argument("--sample-labels", action="store_true", default=True,
                        help="显示样品名称（默认显示）")
    parser.add_argument("--no-sample-labels", dest="sample_labels", action="store_false")
    parser.add_argument("--png-width", type=int, default=1200)
    parser.add_argument("--show", action="store_true", help="显示 Origin 窗口")
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="允许在已有 Origin 进程上运行；默认先要求关闭 Origin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if _origin_running() and not args.allow_existing:
        raise SystemExit(
            "检测到 Origin64.exe 正在运行。为避免覆盖你正在编辑的工程，"
            "请先保存并关闭 Origin，或明确加上 --allow-existing。"
        )
    metadata = _build_graph(args)
    print(f"OPJU：{metadata['outputs']['opju']}")
    print(f"PNG：{metadata['outputs']['png']}")
    print(f"PDF：{metadata['outputs']['pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
