#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xrd_stack.py - XRD 堆叠图 + PDF 卡片峰位线生成器（Origin 友好输出）

把多组 XRD 谱图与 Jade 导出的 PDF 卡片峰位数据，画成论文里常见的
"Y 偏移堆积线图 + 卡片竖线" 图，并同时导出可直接导入 Origin 的数据表。

示例：
  # 自检：用合成数据跑完整流程，不读任何用户文件
  python xrd_stack.py --demo --out ./_xrd_demo

  # 正式出图
  python xrd_stack.py \
      --sample "未处理=raw/s1.txt" --sample "5% Mn=raw/s2.txt" \
      --card   "beta-PbO2=jade/pbo2.txt" \
      --out ./figs/xrd --dpi 600

  # 只解析 PDF 卡片、不出图（不需要 matplotlib）
  python xrd_stack.py --card "beta-PbO2=jade/pbo2.txt" --cards-only --out ./cards

科学边界：本脚本只做"读取 - 可选平滑 - 归一化 - 排版"，不扣背景、不检索物相、
不判断峰归属。平滑参数、卡片峰位与 λ 都会写进 manifest.json，便于复核与写进论文实验部分。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

VERSION = "1.3.0"


def _configure_console() -> None:
    """Avoid UnicodeEncodeError for help/status text on legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


_configure_console()

# 常用 X 射线波长（Å）。以测试报告/仪器设置为准，这里只作为默认值。
RADIATIONS = {
    "CuKa1": (1.54056, "Cu Ka1"),
    "CuKa": (1.5418, "Cu Ka (Ka1+Ka2 weighted average)"),
    "CoKa1": (1.78897, "Co Ka1"),
    "MoKa1": (0.70930, "Mo Ka1"),
    "CrKa1": (2.28970, "Cr Ka1"),
    "FeKa1": (1.93604, "Fe Ka1"),
}

DEFAULT_COLORS = [
    "#1F4E79",  # 深蓝
    "#C1543A",  # 砖红
    "#222222",  # 黑
    "#7A5EA8",  # 紫
    "#C9A227",  # 金
    "#2F8F9D",  # 青
]

DEFAULT_CARD_COLORS = [
    "#8E6BBE",  # 紫
    "#4FA65A",  # 绿
    "#F0A35E",  # 橙
    "#4C9DB8",  # 青蓝
    "#B07AA1",  # 紫红
    "#7B8B3A",  # 橄榄绿
]

MARKER_SHAPES = ["o", "v", "s", "D", "^", "P"]
MARKER_NAMES = ["circle", "triangle-down", "square", "diamond", "triangle-up", "plus"]
ORIGIN_MARKER_KINDS = [1, 4, 2, 3, 5, 6]

KEY_TWO_THETA = ("2-theta", "2theta", "2 theta", "twotheta", "theta", "2θ", "2θ(°)", "angle")
KEY_D_SPACING = ("d(a)", "d(å)", "d-spacing", "dspacing", "d value", "d值", "晶面间距")
KEY_INTENSITY = ("i(f)", "i(rel", "intensity", "int", "rel", "height", "强度", "%")

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uff00-\uffef]")
CARD_FORMULA_RE = re.compile(r"^\s*#\s*formula:\s*(.+?)\s*$", re.I | re.M)
CARD_PHASE_RE = re.compile(r"^\s*#\s*phase:\s*(.+?)\s*$", re.I | re.M)
CARD_PDF_RE = re.compile(r"^\s*#\s*PDF#([^\s]+)", re.I | re.M)


def format_chemical_formula(value: str) -> str:
    """Render common chemical formulas with numeric subscripts in matplotlib."""
    text = value.strip()
    if not text:
        return text
    return re.sub(r"(?<=[A-Za-z)])(\d+)", r"$_{\1}$", text)


def card_display_label(card: dict) -> str:
    """Prefer the chemistry from Jade's card header; keep the user label as fallback."""
    return (card.get("formula") or card.get("name") or "").strip()


def format_hkl_label(value: str) -> str:
    """Render standard hkl notation, using an overbar for negative indices."""
    tokens = value.split()
    if tokens and all(re.fullmatch(r"[+-]?\d+", token) for token in tokens):
        body = "".join(
            rf"\bar{{{abs(int(token))}}}" if int(token) < 0 else str(int(token))
            for token in tokens
        )
        return f"(${body}$)"
    return f"({value.replace(' ', '')})"


# --------------------------------------------------------------------------- #
# 读取与解析
# --------------------------------------------------------------------------- #
def read_text(path: Path) -> tuple[str, str]:
    """按常见编码顺序读取文本，返回 (内容, 实际编码)。中文仪器导出的文件常为 GBK。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def to_float(token: str) -> float | None:
    token = token.strip().strip(",;")
    if not token:
        return None
    # 去掉单位、括注等包围字符，保留数字/正负号/小数点/指数
    cleaned = re.sub(r"[^0-9eE+\-.]", "", token)
    if not cleaned or cleaned in {"+", "-", ".", "-."}:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def split_tokens(line: str) -> list[str]:
    return [t for t in re.split(r"[,\t;]+|\s{1,}", line.strip()) if t]


def is_data_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith(("#", ";", "!", "*", "//")):
        return False
    tokens = split_tokens(s)
    if len(tokens) < 2 or len(tokens) > 20:
        return False
    numeric = [t for t in tokens if to_float(t) is not None]
    if len(numeric) < 2:
        return False
    return len(numeric) / len(tokens) >= 0.6


def find_data_block(text: str) -> tuple[list[list[float]], int, list[str], str]:
    """找出文件中最长的一段数值数据，返回 (数值行, 起始行号, 表头候选行, 原始行)。"""
    lines = text.splitlines()
    flags = [is_data_line(ln) for ln in lines]
    best: tuple[int, int] = (-1, -1)  # (长度, 起点)
    start = None
    for idx, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            length = idx - start
            if length > best[0]:
                best = (length, start)
            start = None
    if best[0] <= 0:
        return [], 0, [], text

    start, length = best[1], best[0]
    rows: list[list[float]] = []
    for line in lines[start : start + length]:
        nums = [to_float(t) for t in split_tokens(line)]
        rows.append([n for n in nums if n is not None])

    # 列数取众数，避免个别行多/少一列造成错位
    counts: dict[int, int] = {}
    for row in rows:
        counts[len(row)] = counts.get(len(row), 0) + 1
    modal = max(counts, key=lambda k: (counts[k], k))
    rows = [row for row in rows if len(row) == modal]

    header_lines = [ln for ln in lines[max(0, start - 12) : start] if ln.strip()]
    return rows, start + 1, header_lines, "\n".join(lines[start : start + length])


def header_column_map(header_lines: list[str], ncols: int) -> dict[str, int]:
    """若表头能被可靠切分成与数据同列数，则返回 {角色: 列号(0基)}。"""
    for line in reversed(header_lines):
        tokens = split_tokens(line)
        if len(tokens) != ncols:
            continue
        low = [t.lower() for t in tokens]
        mapping: dict[str, int] = {}
        for idx, tok in enumerate(low):
            if any(k in tok for k in KEY_TWO_THETA) and "two_theta" not in mapping:
                mapping["two_theta"] = idx
            if any(k in tok for k in KEY_D_SPACING) and "d" not in mapping:
                mapping["d"] = idx
            if any(k in tok for k in KEY_INTENSITY) and "intensity" not in mapping:
                mapping["intensity"] = idx
        if "two_theta" in mapping or "d" in mapping:
            return mapping
    return {}


def header_card_kind(header_lines: list[str]) -> str | None:
    """从表头文字判断卡片第一列是 2θ 还是 d 值，即使 hkl 被拆成多列也能用。"""
    for line in reversed(header_lines):
        low = line.lower()
        if any(key in low for key in KEY_TWO_THETA):
            return "two_theta"
        if any(key in low for key in KEY_D_SPACING):
            return "d"
    return None


def parse_card_hkl(block: str, expected: int) -> list[str]:
    """Read hkl labels from the cleaned Jade d-I table; fall back to blanks."""
    labels: list[str] = []
    for line in block.splitlines():
        if not is_data_line(line):
            continue
        tokens = split_tokens(line)
        if len(tokens) < 3:
            labels.append("")
            continue
        labels.append(" ".join(tokens[2:]))
    if len(labels) < expected:
        labels.extend([""] * (expected - len(labels)))
    return labels[:expected]


def columns(rows: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*rows)]


def decreasing_ratio(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    ok = sum(1 for a, b in zip(values, values[1:]) if b <= a)
    return ok / (len(values) - 1)


def guess_card_columns(
    cols: list[list[float]],
    ncols: int,
    preferred_kind: str | None = None,
) -> tuple[int, int, str]:
    """在没有任何提示时，猜 (x_col, i_col, kind)。kind 为 'two_theta' 或 'd'。"""
    if ncols == 2:
        first = cols[0]
        # d 值随 2θ 增大而单调减小；2θ 一般在 3~150 之间且不单调
        if max(first) <= 30 and min(first) > 0.3 and decreasing_ratio(first) > 0.8:
            return 0, 1, "d"
        return 0, 1, "two_theta"

    d_candidates = [
        i for i, c in enumerate(cols)
        if max(c) <= 30 and min(c) > 0.3 and decreasing_ratio(c) > 0.7
    ]
    i_candidates = [
        i for i, c in enumerate(cols)
        if 0 <= min(c) and max(c) <= 1e5 and (abs(max(c) - 100) < 0.5 or max(c) <= 1000)
    ]
    angle_candidates = [i for i, c in enumerate(cols) if 3 <= min(c) and max(c) <= 150]

    x_col, kind = None, None
    if preferred_kind == "d" and d_candidates:
        x_col, kind = d_candidates[0], "d"
    elif preferred_kind == "two_theta" and angle_candidates:
        x_col, kind = angle_candidates[0], "two_theta"

    if x_col is None:
        # A monotonic 0.3-30 Å column is much more diagnostic than a loose
        # 3-150 numeric range, because card intensity columns often look like
        # angles when the hkl indices are split into separate columns.
        if d_candidates:
            x_col, kind = d_candidates[0], "d"
        else:
            for cand in angle_candidates:
                x_col, kind = cand, "two_theta"
                break
    if x_col is None:
        raise SystemExit("无法自动识别卡片表列，请用 --card-cols 手动指定，例如 --card-cols 2,3")

    i_col = None
    for cand in i_candidates:
        if cand != x_col:
            i_col = cand
            break
    if i_col is None:
        raise SystemExit("无法自动识别卡片强度列，请用 --card-cols 手动指定")
    return x_col, i_col, kind


def bragg_two_theta(d_spacing: float, wavelength: float) -> float | None:
    """d(Å) -> 2θ(°)：Bragg 定律 nλ = 2d·sinθ，取 n=1。"""
    if d_spacing <= 0:
        return None
    sin_theta = wavelength / (2.0 * d_spacing)
    if not (0 < sin_theta <= 1):
        return None
    return 2.0 * math.degrees(math.asin(sin_theta))


def parse_pair_spec(spec: str) -> tuple[str, Path]:
    """把 '名称=路径' 解析成 (名称, Path)。"""
    if "=" not in spec:
        path = Path(spec)
        return path.stem, path
    name, _, raw_path = spec.partition("=")
    return (name.strip() or Path(raw_path.strip()).stem), Path(raw_path.strip())


def parse_sample(path: Path, cols: tuple[int, int] | None, warnings: list[str]) -> dict:
    text, enc = read_text(path)
    rows, start_line, header, _ = find_data_block(text)
    if not rows:
        raise SystemExit(f"{path}: 没有找到两列以上的数值数据，请检查导出格式")
    ncols = len(rows[0])
    if cols:
        x_idx, y_idx = cols[0] - 1, cols[1] - 1
        if max(x_idx, y_idx) >= ncols:
            raise SystemExit(f"{path}: 文件只有 {ncols} 列数值，--sample-cols 超出范围")
    elif ncols == 2:
        x_idx, y_idx = 0, 1
    else:
        raise SystemExit(
            f"{path}: 检测到 {ncols} 列数值，无法确定哪两列是 2θ 与强度，"
            f"请用 --sample-cols 指定（例如 --sample-cols 1,2）"
        )
    col_data = columns(rows)
    x, y = col_data[x_idx], col_data[y_idx]
    if x[0] > x[-1]:
        x, y = x[::-1], y[::-1]
        warnings.append(f"{path.name}: 角度列是递减的，已自动反转为递增")
    order = sorted(range(len(x)), key=lambda i: x[i])
    x = [x[i] for i in order]
    y = [y[i] for i in order]
    if len(x) < 10:
        warnings.append(f"{path.name}: 只有 {len(x)} 个数据点，图形可能不够平滑")
    if min(y) < -1e-6:
        warnings.append(f"{path.name}: 强度出现负值（{min(y):.4g}），请确认是否已扣背景")
    return {
        "name": path.stem,
        "path": str(path),
        "encoding": enc,
        "data_start_line": start_line,
        "n_points": len(x),
        "two_theta": x,
        "intensity": y,
        "two_theta_range": [min(x), max(x)],
    }


def parse_card(path: Path, kind: str, cols: tuple[int, int] | None,
               wavelength: float, warnings: list[str]) -> dict:
    text, enc = read_text(path)
    formula_match = CARD_FORMULA_RE.search(text)
    phase_match = CARD_PHASE_RE.search(text)
    pdf_match = CARD_PDF_RE.search(text)
    formula = formula_match.group(1).strip() if formula_match else ""
    phase_name = phase_match.group(1).strip() if phase_match else ""
    pdf_number = pdf_match.group(1).strip() if pdf_match else ""
    rows, start_line, header, block = find_data_block(text)
    if not rows:
        raise SystemExit(f"{path}: 没有找到卡片数值数据（应至少有两列数字）")
    ncols = len(rows[0])
    col_data = columns(rows)

    if cols:
        x_idx, y_idx = cols[0] - 1, cols[1] - 1
        if max(x_idx, y_idx) >= ncols:
            raise SystemExit(f"{path}: 文件只有 {ncols} 列数值，--card-cols 超出范围")
        resolved_kind = kind if kind != "auto" else (
            "d" if decreasing_ratio(col_data[x_idx]) > 0.8 and max(col_data[x_idx]) <= 30
            else "two_theta"
        )
        source = "manual"
    else:
        hinted = header_column_map(header, ncols)
        kind_hint = header_card_kind(header)
        if kind == "auto" and hinted:
            if "two_theta" in hinted:
                x_idx, resolved_kind = hinted["two_theta"], "two_theta"
            else:
                x_idx, resolved_kind = hinted["d"], "d"
            y_idx = hinted.get("intensity")
            if y_idx is None or y_idx == x_idx:
                x_idx, y_idx, resolved_kind = guess_card_columns(col_data, ncols)
                source = "value-heuristic"
            else:
                source = "header"
        else:
            gx, gy, gk = guess_card_columns(col_data, ncols, kind_hint)
            x_idx, y_idx = gx, gy
            resolved_kind = kind if kind != "auto" else gk
            source = "header-kind" if kind_hint and kind == "auto" else "value-heuristic"

    raw_x = col_data[x_idx]
    raw_i = col_data[y_idx]
    hkl_values = parse_card_hkl(block, len(raw_x))
    records: list[dict] = []
    dropped = 0
    for index, (xv, iv) in enumerate(zip(raw_x, raw_i)):
        hkl = hkl_values[index] if index < len(hkl_values) else ""
        if resolved_kind == "d":
            two_theta = bragg_two_theta(xv, wavelength)
            if two_theta is None:
                dropped += 1
                continue
            records.append({"two_theta": two_theta, "intensity": iv, "hkl": hkl})
        else:
            records.append({"two_theta": xv, "intensity": iv, "hkl": hkl})
    if dropped:
        warnings.append(f"{path.name}: {dropped} 个 d 值无法按 λ={wavelength} Å 换算成 2θ，已跳过")
    if not records:
        raise SystemExit(f"{path.name}: 换算后没有可用的 2θ 峰位")

    records.sort(key=lambda item: item["two_theta"])
    two_theta = [item["two_theta"] for item in records]
    intensity = [item["intensity"] for item in records]
    hkl_labels = [item["hkl"] for item in records]
    peak = max(intensity) if intensity else 0.0
    if peak <= 0:
        raise SystemExit(f"{path.name}: 强度列全为 0，请确认列是否选对")
    rel = [100.0 * v / peak for v in intensity]
    return {
        "name": path.stem,
        "formula": formula,
        "phase_name": phase_name,
        "pdf_number": pdf_number,
        "hkl": hkl_labels,
        "path": str(path),
        "encoding": enc,
        "data_start_line": start_line,
        "n_peaks": len(two_theta),
        "interpreted_as": resolved_kind,
        "interpretation_source": source,
        "wavelength": wavelength,
        "two_theta": two_theta,
        "intensity_raw": intensity,
        "intensity_rel100": rel,
        "two_theta_range": [min(two_theta), max(two_theta)],
        "three_strongest": sorted(
            [
                {"two_theta": round(t, 4), "i_rel": round(i, 1), "hkl": hkl}
                for t, i, hkl in zip(two_theta, rel, hkl_labels)
            ],
            key=lambda d: -d["i_rel"],
        )[:3],
        "raw_block_preview": block.splitlines()[:4],
    }


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def write_card_tables(out_dir: Path, cards: list[dict]) -> list[str]:
    written = []
    for card in cards:
        target = out_dir / "cards_clean" / f"{card['name']}.csv"
        write_csv(
            target,
            ["2theta_deg", "d_A", "I_rel_100", "I_raw", "hkl"],
            [
                [
                    f"{t:.4f}",
                    f"{card['wavelength'] / (2 * math.sin(math.radians(t / 2))):.4f}",
                    f"{i:.2f}",
                    f"{raw:.4f}",
                    hkl,
                ]
                for t, i, raw, hkl in zip(
                    card["two_theta"],
                    card["intensity_rel100"],
                    card["intensity_raw"],
                    card.get("hkl", [""] * len(card["two_theta"])),
                )
            ],
        )
        written.append(str(target))
    return written


def write_origin_tables(out_dir: Path, samples: list[dict], cards: list[dict],
                        norm: str, offsets: list[float]) -> list[str]:
    """导出 Origin 友好数据表：每个样品/卡片一个两列 CSV + 一张合并表。"""
    written: list[str] = []
    origin = out_dir / "origin"
    origin.mkdir(parents=True, exist_ok=True)

    for idx, s in enumerate(samples):
        norm_values = normalize(s["intensity"], norm)
        target = origin / f"sample{idx + 1}_{s['name']}.csv"
        write_csv(
            target,
            ["2theta_deg", "I_raw", f"I_{norm}", "y_offset"],
            [
                [f"{t:.4f}", f"{raw:.6g}", f"{n:.6g}", f"{offsets[idx]:.6g}"]
                for t, raw, n in zip(s["two_theta"], s["intensity"], norm_values)
            ],
        )
        written.append(str(target))

    for idx, c in enumerate(cards):
        target = origin / f"card{idx + 1}_{c['name']}.csv"
        write_csv(
            target,
            ["2theta_deg", "I_rel_100"],
            [[f"{t:.4f}", f"{i:.2f}"] for t, i in zip(c["two_theta"], c["intensity_rel100"])],
        )
        written.append(str(target))

    # 合并表：A/B 为样品 1，C/D 为样品 2 …… 与 Origin 手工流程的列结构一致
    sample_cols: list[tuple[str, list]] = []
    for idx, s in enumerate(samples):
        sample_cols.append((f"2theta_{idx + 1}", [f"{t:.4f}" for t in s["two_theta"]]))
        sample_cols.append((f"I_{idx + 1}_{s['name']}", [f"{v:.6g}" for v in normalize(s["intensity"], norm)]))
    width = max((len(col) for _, col in sample_cols), default=0)
    target = origin / "Sheet1_samples.csv"
    write_csv(
        target,
        [name for name, _ in sample_cols],
        [[col[r] if r < len(col) else "" for _, col in sample_cols] for r in range(width)],
    )
    written.append(str(target))

    card_cols: list[tuple[str, list]] = []
    for idx, c in enumerate(cards):
        card_cols.append((f"card{idx + 1}_2theta", [f"{t:.4f}" for t in c["two_theta"]]))
        card_cols.append((card_display_label(c), [f"{i:.2f}" for i in c["intensity_rel100"]]))
    width = max((len(col) for _, col in card_cols), default=0)
    target = origin / "Sheet2_cards.csv"
    write_csv(
        target,
        [name for name, _ in card_cols],
        [[col[r] if r < len(col) else "" for _, col in card_cols] for r in range(width)],
    )
    written.append(str(target))

    readme = origin / "导入Origin说明.txt"
    readme.write_text(
        "这些 CSV 已按 Origin 习惯排好列：\n"
        "  Sheet1_samples.csv —— 每个样品两列（第一列 2theta，第二列强度），样品依次排列\n"
        "  Sheet2_cards.csv   —— 每张 PDF 卡片两列（2theta、相对强度 I/I0×100）\n\n"
        "Origin 2025b 手工流程（中文界面）：\n"
        "  1. 文件 → 导入 → 多个 ASCII，导入 Sheet1_samples.csv\n"
        "  2. 选中全部样品列 → 绘图 → 基础 2D 图 → Y 偏移堆积线图\n"
        "  3. 双击图形 → 绘图细节 → 图层属性 → 堆叠 → 偏移选「单独」→ 上下拖动曲线调间距\n"
        "  4. 卡片数据用散点图 + 垂直线（平行于 Y 轴）画成峰位竖线，X 轴范围与主图一致\n"
        "  详见 skill 里的 references/origin-stacking.md\n",
        encoding="utf-8",
    )
    written.append(str(readme))
    return written


def normalize(values: list[float], mode: str) -> list[float]:
    if mode == "none":
        return list(values)
    peak = max(values) if values else 0.0
    if peak <= 0:
        return list(values)
    if mode == "max100":
        return [100.0 * v / peak for v in values]
    return [v / peak for v in values]


def smooth_intensity(
    values: list[float],
    mode: str,
    window_length: int,
    polyorder: int,
    warnings: list[str],
) -> list[float]:
    """Return plot-only smoothing; exported Origin tables keep the raw intensity."""
    if mode == "none" or len(values) < 5:
        return list(values)

    window = max(polyorder + 2, int(window_length))
    if window % 2 == 0:
        window += 1
    max_window = len(values) if len(values) % 2 else len(values) - 1
    window = min(window, max_window)
    if window <= polyorder:
        warnings.append("谱线过短，已跳过 Savitzky-Golay 平滑")
        return list(values)

    try:
        from scipy.signal import savgol_filter
    except ImportError:
        warnings.append("未安装 scipy，已跳过 Savitzky-Golay 平滑；原始谱线仍正常输出")
        return list(values)

    return savgol_filter(
        values, window_length=window, polyorder=polyorder, mode="interp"
    ).tolist()


def detect_observed_peaks(
    two_theta: list[float],
    intensity: list[float],
    min_fraction: float,
) -> list[dict]:
    """Find simple local maxima for annotation matching; this is not a phase ID step."""
    y = normalize(intensity, "max1")
    if len(y) < 3:
        return []
    baseline = min(y)
    threshold = baseline + max(0.005, min_fraction)
    peaks: list[dict] = []
    for index in range(1, len(y) - 1):
        if not (y[index] > y[index - 1] and y[index] >= y[index + 1]):
            continue
        if y[index] < threshold:
            continue
        left = max(0, index - 2)
        right = min(len(y), index + 3)
        if y[index] < max(y[left:right]) - 1e-12:
            continue
        local_left = max(0, index - 8)
        local_right = min(len(y), index + 9)
        local_prominence = y[index] - min(y[local_left:local_right])
        if local_prominence < max(0.02, min_fraction):
            continue
        peaks.append(
            {
                "two_theta": two_theta[index],
                "y": y[index],
                "index": index,
            }
        )
    return peaks


def nearest_observed_peak(
    observed: list[dict],
    standard_two_theta: float,
    tolerance: float,
) -> dict | None:
    candidates = [
        peak for peak in observed
        if abs(peak["two_theta"] - standard_two_theta) <= tolerance
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda peak: abs(peak["two_theta"] - standard_two_theta))


def build_peak_annotations(
    args,
    samples: list[dict],
    cards: list[dict],
    offsets: list[float],
    warnings: list[str],
) -> list[dict]:
    """Match card peaks to observed peaks for single-pattern marker or hkl annotation."""
    if args.peak_marking == "none" or not cards:
        return []
    if len(samples) != 1:
        warnings.append("--peak-marking 只用于单条 XRD 谱，多样品图已忽略该标峰模式。")
        return []

    sample = samples[0]
    observed = detect_observed_peaks(
        sample["two_theta"],
        sample["intensity"],
        args.observed_min_fraction,
    )
    if not observed:
        warnings.append("没有从单条 XRD 谱中识别到可匹配的局部峰，未添加标峰。")
        return []

    annotations: list[dict] = []
    if args.peak_marking == "markers":
        for card_index, card in enumerate(cards):
            marker = MARKER_SHAPES[card_index % len(MARKER_SHAPES)]
            marker_name = MARKER_NAMES[card_index % len(MARKER_NAMES)]
            color = args.card_colors[card_index % len(args.card_colors)]
            formula = card_display_label(card)
            pdf_number = str(card.get("pdf_number", "")).strip()
            legend = f"{formula}: PDF#{pdf_number}" if pdf_number else formula
            used: set[int] = set()
            for standard_theta, rel_i in zip(card["two_theta"], card["intensity_rel100"]):
                if rel_i < args.marker_min_intensity:
                    continue
                matched = nearest_observed_peak(observed, standard_theta, args.peak_tolerance)
                if matched is None or matched["index"] in used:
                    continue
                used.add(matched["index"])
                annotations.append(
                    {
                        "kind": "marker",
                        "card_index": card_index,
                        "formula": formula,
                        "pdf_number": pdf_number,
                        "legend": legend,
                        "standard_two_theta": round(standard_theta, 4),
                        "observed_two_theta": round(matched["two_theta"], 4),
                        "observed_y": round(matched["y"], 6),
                        "plot_y": round(
                            min(0.97, matched["y"] + 0.035 + 0.025 * card_index),
                            6,
                        ),
                        "marker": marker,
                        "marker_name": marker_name,
                        "hkl": "",
                        "color": color,
                    }
                )
        return annotations

    card_index = max(1, int(args.hkl_card)) - 1
    if card_index >= len(cards):
        warnings.append(
            f"--hkl-card {args.hkl_card} 超出卡片数量 {len(cards)}，未添加 hkl 标峰。"
        )
        return []
    card = cards[card_index]
    color = args.card_colors[card_index % len(args.card_colors)]
    stable_order = sorted(
        range(len(card["two_theta"])),
        key=lambda item: (-card["intensity_rel100"][item], card["two_theta"][item]),
    )
    used_observed: set[int] = set()
    for index in stable_order:
        rel_i = card["intensity_rel100"][index]
        hkl = card["hkl"][index] if index < len(card["hkl"]) else ""
        if rel_i < args.hkl_min_intensity or not hkl:
            continue
        standard_theta = card["two_theta"][index]
        matched = nearest_observed_peak(observed, standard_theta, args.peak_tolerance)
        if matched is None:
            continue
        label = format_hkl_label(hkl)
        if matched["index"] in used_observed:
            continue
        used_observed.add(matched["index"])
        annotations.append(
            {
                "kind": "hkl",
                "card_index": card_index,
                "formula": card_display_label(card),
                "pdf_number": str(card.get("pdf_number", "")).strip(),
                "legend": card_display_label(card),
                "standard_two_theta": round(standard_theta, 4),
                "observed_two_theta": round(matched["two_theta"], 4),
                "observed_y": round(matched["y"], 6),
                "plot_y": round(
                    min(1.10, matched["y"] + 0.045),
                    6,
                ),
                "marker": "",
                "marker_name": "",
                "hkl": hkl,
                "hkl_label": label,
                "color": color,
            }
        )
    return annotations


def write_peak_annotations(out_dir: Path, annotations: list[dict]) -> str | None:
    if not annotations:
        return None
    columns_order = [
        "kind",
        "card_index",
        "formula",
        "pdf_number",
        "legend",
        "standard_two_theta",
        "observed_two_theta",
        "observed_y",
        "plot_y",
        "marker",
        "marker_name",
        "hkl",
        "hkl_label",
        "color",
    ]
    rows = [[item.get(key, "") for key in columns_order] for item in annotations]
    target = out_dir / "peak_annotations.csv"
    write_csv(target, columns_order, rows)
    origin_target = out_dir / "origin" / "Sheet3_peak_annotations.csv"
    write_csv(origin_target, columns_order, rows)
    return str(target)


# --------------------------------------------------------------------------- #
# 绘图
# --------------------------------------------------------------------------- #
def pick_fonts(requested: str | None, need_cjk: bool) -> list[str]:
    try:
        from matplotlib import font_manager
    except Exception:  # pragma: no cover - matplotlib 缺失时由调用方处理
        return [requested] if requested else []
    available = {f.name for f in font_manager.fontManager.ttflist}
    families: list[str] = []
    if requested and requested in available:
        families.append(requested)
    elif not requested:
        for name in ("Times New Roman", "Arial", "DejaVu Sans"):
            if name in available:
                families.append(name)
                break
    if need_cjk:
        for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC", "SimSun"):
            if name in available:
                if name not in families:
                    families.append(name)
                break
    if not families:
        for name in ("DejaVu Sans", "Arial"):
            if name in available:
                families.append(name)
                break
    return families or ["DejaVu Sans"]


def make_figure(args, samples: list[dict], cards: list[dict], offsets: list[float],
                card_owner: list[int | None], annotations: list[dict],
                warnings: list[str]) -> "object":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator

    labels = [s["name"] for s in samples] + [c["name"] for c in cards] + [args.title or ""]
    fonts = pick_fonts(args.font, need_cjk=any(CJK_RE.search(x) for x in labels))
    if args.font and args.font not in fonts:
        warnings.append(f"未找到指定字体 {args.font}，已回退到 {', '.join(fonts)}")
    plt.rcParams["font.family"] = fonts
    plt.rcParams["font.serif"] = fonts
    plt.rcParams["font.sans-serif"] = fonts
    plt.rcParams["mathtext.fontset"] = "stix"
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.default"] = "regular"

    gap = args.gap
    sample_step = 1.0 + gap
    single_sample = len(samples) == 1
    sample_line_width = max(0.55, args.line_width * (0.72 if single_sample else 1.0))

    fig, ax = plt.subplots(figsize=(args.width, args.height), dpi=100)
    for idx, sample in enumerate(samples):
        plotted_intensity = smooth_intensity(
            sample["intensity"],
            args.smooth,
            args.smooth_window,
            args.smooth_polyorder,
            warnings,
        )
        y = [offsets[idx] + v for v in normalize(plotted_intensity, args.norm)]
        color = args.colors[idx % len(args.colors)]
        ax.plot(sample["two_theta"], y, color=color, lw=sample_line_width,
                solid_joinstyle="round", label=sample["name"], zorder=3)

    if annotations and len(samples) == 1:
        for item in annotations:
            if item["kind"] == "marker":
                ax.scatter(
                    [item["observed_two_theta"]],
                    [item["plot_y"]],
                    marker=item["marker"],
                    s=32,
                    color=item["color"],
                    edgecolors="none",
                    zorder=6,
                    clip_on=False,
                )
            elif item["kind"] == "hkl":
                ax.text(
                    item["observed_two_theta"],
                    item["plot_y"],
                    item.get("hkl_label") or item.get("hkl", ""),
                    ha="center",
                    va="bottom",
                    fontsize=args.hkl_label_size,
                    color="#222222",
                    zorder=6,
                    clip_on=False,
                )

    if args.x_range:
        x_left, x_right = args.x_range
    else:
        all_x = [x for sample in samples for x in sample["two_theta"]]
        all_x.extend(x for card in cards for x in card["two_theta"])
        x_left = math.floor(min(all_x) / 5.0) * 5.0
        x_right = math.ceil(max(all_x) / 5.0) * 5.0
    x_span = max(x_right - x_left, 1e-9)

    # 默认将所有卡片统一排在下方，每条卡片基线占用一层。
    per_sample_mode = (
        args.card_position == "per-sample"
        and len(cards) <= len(samples)
        and all(owner is not None for owner in card_owner)
    )
    bands: list[tuple[int, float, float, float, str]] = []
    annotated_single = single_sample and args.peak_marking != "none"
    if annotated_single:
        per_sample_mode = False
    elif per_sample_mode:
        card_band = max(0.05, args.stick_height) * gap
        for idx in range(len(cards)):
            owner = int(card_owner[idx])
            top = owner * sample_step - 0.16 * gap
            color = args.card_colors[idx % len(args.card_colors)]
            bands.append((idx, top - card_band, top, top - card_band, color))
    elif not annotated_single:
        row_height = max(0.34, args.card_row_height)
        first_baseline = min(offsets) - 0.56 * sample_step
        for idx in range(len(cards)):
            baseline = first_baseline - idx * row_height
            top = baseline + max(0.30, args.stick_height) * row_height
            color = args.card_colors[idx % len(args.card_colors)]
            bands.append((idx, baseline, top, baseline, color))

    if not per_sample_mode and cards and bands:
        row_height = max(0.34, args.card_row_height)
        divider = max(baseline for _, _, _, baseline, _ in bands) + row_height + 0.03
        ax.hlines(
            divider, x_left, x_right, colors="#9A9A9A",
            linewidth=0.55, zorder=1, clip_on=False,
        )

    for idx, bottom, top, baseline, color in bands:
        card = cards[idx]
        height_band = max(top - bottom, 1e-9)
        visible_index = [
            idx for idx, intensity in enumerate(card["intensity_rel100"])
            if intensity >= args.card_min_intensity
        ]
        visible_x = [card["two_theta"][idx] for idx in visible_index]
        visible_tops = [
            bottom + card["intensity_rel100"][idx] / 100.0 * height_band
            for idx in visible_index
        ]
        ax.vlines(visible_x, bottom, visible_tops, color=color, lw=args.stick_width,
                  alpha=0.95, zorder=2)
        ax.hlines(
            baseline, x_left, x_right, colors="#6F6F6F",
            linewidth=0.45, zorder=1, clip_on=False,
        )
        if args.card_labels:
            ax.text(
                x_right - 0.012 * x_span,
                top + 0.045 * max(top - bottom, 1e-9),
                format_chemical_formula(card_display_label(card)),
                ha="right", va="bottom", fontsize=args.card_label_size, color=color,
                fontweight="bold",
                clip_on=True, zorder=4,
            )

    if args.sample_labels and not single_sample:
        for idx, sample in enumerate(samples):
            y_label = offsets[idx] + 0.56
            ax.text(
                x_right - 0.012 * x_span, y_label, sample["name"],
                ha="right", va="center", fontsize=args.sample_label_size,
                color=args.colors[idx % len(args.colors)], clip_on=False, zorder=5,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.72, pad=0.5),
            )

    top_pad = 1.20 if args.peak_marking == "hkl" and annotations else 1.08
    y_top = max(offsets) + top_pad if samples else 1.0
    y_bottom = min([0.0] + [baseline for _, _, _, baseline, _ in bands])
    if bands:
        y_bottom -= 0.12 if per_sample_mode else 0.16 * args.card_row_height
    elif samples:
        y_bottom -= 0.08
    ax.set_xlim(x_left, x_right)
    ax.set_ylim(y_bottom, y_top)

    ax.xaxis.set_major_locator(MultipleLocator(args.x_tick))
    ax.set_xlabel(args.xlabel, fontsize=11.5)
    ax.set_ylabel(args.ylabel, fontsize=11.5)
    ax.set_yticks([])
    ax.tick_params(axis="x", which="both", direction="in", top=False, bottom=True,
                   labelsize=10.5)
    ax.tick_params(axis="y", which="both", direction="in", right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    legend_mode = args.legend
    if legend_mode == "auto":
        if args.peak_marking == "markers":
            legend_mode = "inside"
        elif args.peak_marking == "hkl":
            legend_mode = "none"
        else:
            # 默认分层卡片已经在框内逐行标注，不再重复放大图例。
            legend_mode = "none"
    if legend_mode == "above":
        ax.legend(
            loc="lower left", bbox_to_anchor=(0.0, 1.01), ncol=min(max(len(samples), 1), 4),
            frameon=False, fontsize=9.5, handlelength=1.8, columnspacing=1.2,
            borderaxespad=0.0,
        )
    elif legend_mode == "inside":
        if single_sample and args.peak_marking == "markers" and annotations:
            from matplotlib.lines import Line2D

            handles = []
            seen: set[int] = set()
            for item in annotations:
                card_index = int(item["card_index"])
                if card_index in seen:
                    continue
                seen.add(card_index)
                handles.append(
                    Line2D(
                        [0], [0], linestyle="none", marker=item["marker"],
                        markersize=6.5, markerfacecolor=item["color"],
                        markeredgecolor="none",
                        label=(
                            f"{format_chemical_formula(item['formula'])}: "
                            f"PDF#{item['pdf_number']}"
                            if item.get("pdf_number")
                            else item["legend"]
                        ),
                    )
                )
            ax.legend(
                handles=handles, loc="upper right", frameon=False,
                fontsize=8.8, handlelength=1.2, labelspacing=0.45,
            )
        elif single_sample and cards:
            from matplotlib.lines import Line2D

            handles = [
                Line2D(
                    [0], [0], color=args.card_colors[idx % len(args.card_colors)],
                    lw=2.0, label=format_chemical_formula(card_display_label(card)),
                )
                for idx, card in enumerate(cards)
            ]
            ax.legend(
                handles=handles, loc="upper right", frameon=False,
                fontsize=9.0, handlelength=1.4, labelspacing=0.35,
            )
        else:
            ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    if args.title:
        ax.set_title(args.title, fontsize=11, pad=26 if legend_mode == "above" else 6)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- #
# 演示数据
# --------------------------------------------------------------------------- #
def demo_inputs(tmp: Path) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    """合成两组谱图 + 两张卡片文本，用于自检（不涉及任何真实样品数据）。"""
    tmp.mkdir(parents=True, exist_ok=True)
    peaks_sets = [
        [(28.4, 100), (34.9, 42), (49.2, 26), (58.1, 15), (61.3, 12)],
        [(28.5, 100), (35.0, 55), (49.3, 30), (58.2, 18), (61.5, 14)],
        [(28.3, 100), (34.8, 33), (49.1, 22), (58.0, 11), (61.2, 9)],
    ]
    samples = []
    for idx, peaks in enumerate(peaks_sets, start=1):
        path = tmp / f"demo_sample{idx}.txt"
        rows = ["# 合成演示数据 synthetic demo data (2theta intensity)"]
        x = 10.0
        while x <= 80.0001:
            y = 12.0 + 3.0 * math.sin(x * 0.7 + idx)
            for center, height in peaks:
                y += height * math.exp(-((x - center) ** 2) / (2 * 0.22 ** 2))
            rows.append(f"{x:.3f} {y:.2f}")
            x += 0.02
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        samples.append((f"Demo-{idx}", path))

    cards = []
    for idx, (name, peaks) in enumerate(
        [("DemoPhaseA", [(28.4, 100), (34.9, 45), (49.2, 25), (58.1, 14), (61.3, 11)]),
         ("DemoPhaseB", [(31.7, 100), (45.5, 62), (56.6, 38), (66.2, 20)])],
        start=1,
    ):
        path = tmp / f"demo_card{idx}.txt"
        lines = [f"## Synthetic reference card {name} (demo only, not a real PDF card)",
                 "   d(A)      I(f)    h  k  l"]
        for center, height in peaks:
            d = 1.54056 / (2 * math.sin(math.radians(center / 2)))
            lines.append(f"  {d:8.4f}  {height:7.1f}    1  0  0")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cards.append((name, path))
    return samples, cards


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xrd_stack.py",
        description="XRD 堆叠图 + PDF 卡片峰位线（Origin 友好输出）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python xrd_stack.py --demo --out ./_xrd_demo",
    )
    p.add_argument("--sample", action="append", default=[], metavar="名称=路径",
                   help="样品谱图文件，可重复；文件需为两列数值（2θ、强度）")
    p.add_argument("--card", action="append", default=[], metavar="名称=路径",
                   help="Jade 导出的 PDF 卡片 TXT，可重复；d-I 或 2θ-I 都能识别")
    p.add_argument("--out", default="./xrd_out", help="输出目录（默认 ./xrd_out）")
    p.add_argument("--demo", action="store_true", help="用合成数据自检，不需要任何输入文件")
    p.add_argument("--cards-only", action="store_true", help="只解析卡片并导出 CSV，不出图")

    p.add_argument("--radiation", default="CuKa1", choices=sorted(RADIATIONS),
                   help="X 射线波长预设（默认 CuKa1）；d 值换算 2θ 时使用")
    p.add_argument("--wavelength", type=float, default=None,
                   help="直接指定波长（Å），优先级高于 --radiation")

    p.add_argument("--norm", default="max1", choices=["max1", "max100", "none"],
                   help="每条谱线的归一化方式（默认 max1）")
    p.add_argument("--smooth", default="savgol", choices=["none", "savgol"],
                   help="谱线显示平滑：默认 savgol；原始强度表不改动")
    p.add_argument("--smooth-window", type=int, default=11,
                   help="Savitzky-Golay 窗口点数（默认 11，自动为奇数）")
    p.add_argument("--smooth-polyorder", type=int, default=3,
                   help="Savitzky-Golay 多项式阶数（默认 3）")
    p.add_argument("--sample-cols", default=None, metavar="i,j",
                   help="样品文件里 2θ 与强度所在的列号（1 基）")
    p.add_argument("--card-cols", default=None, metavar="i,j",
                   help="卡片文件里峰位与强度所在的列号（1 基）")
    p.add_argument("--card-kind", default="auto", choices=["auto", "two_theta", "d"],
                   help="卡片第一列的含义（默认自动判断）")

    p.add_argument("--gap", type=float, default=0.75, help="曲线间距（相对谱线高度，默认 0.75）")
    p.add_argument("--stick-height", type=float, default=0.58,
                   help="卡片竖线占卡片行高的比例（默认 0.58）")
    p.add_argument("--stick-width", type=float, default=0.85, help="卡片竖线线宽（默认 0.85）")
    p.add_argument("--card-row-height", type=float, default=0.40,
                   help="下方卡片的分层行高（默认 0.40，较紧凑）")
    p.add_argument("--card-min-intensity", type=float, default=5.0,
                   help="只显示相对强度不低于该值的卡片棒线；默认 5，原始卡表不变")
    p.add_argument("--card-position", default="bottom", choices=["per-sample", "bottom"],
                   help="卡片位置：贴在对应曲线下方，或统一放在最底部")
    p.add_argument("--card-labels", action="store_true", default=True,
                   help="在坐标框内显示卡片名称（默认显示）")
    p.add_argument("--no-card-labels", dest="card_labels", action="store_false",
                   help="不显示卡片名称")
    p.add_argument("--sample-labels", action="store_true", default=True,
                   help="在曲线右侧显示样品名称（默认显示）")
    p.add_argument("--no-sample-labels", dest="sample_labels", action="store_false",
                   help="不显示样品名称")

    p.add_argument("--line-width", type=float, default=0.9, help="谱线线宽（默认 0.9）")
    p.add_argument("--colors", default=",".join(DEFAULT_COLORS),
                   help="样品颜色列表，逗号分隔的 HEX 值")
    p.add_argument("--card-colors", default=",".join(DEFAULT_CARD_COLORS),
                   help="PDF 卡片颜色列表，逗号分隔的 HEX 值")
    p.add_argument("--font", default=None,
                   help="首选英文字体（默认 Times New Roman，中文自动回退 Microsoft YaHei）")
    p.add_argument("--x-range", type=float, nargs=2, default=None, metavar=("MIN", "MAX"),
                   help="X 轴范围，例如 --x-range 10 80")
    p.add_argument("--x-tick", type=float, default=10.0, help="X 轴主刻度间隔（默认 10°）")
    p.add_argument("--xlabel", default="2-Theta (°)", help="X 轴标题")
    p.add_argument("--ylabel", default="Intensity (a.u.)", help="Y 轴标题")
    p.add_argument("--title", default=None, help="图标题（默认不加）")
    p.add_argument("--legend", default="auto", choices=["auto", "above", "inside", "none"],
                   help="图例：auto（分层卡片不重复图例）、上方、图框内、或不显示")
    p.add_argument("--card-label-size", type=float, default=8.5, help="卡片名称字号")
    p.add_argument("--sample-label-size", type=float, default=9.0, help="样品名称字号")
    p.add_argument(
        "--peak-marking",
        default="none",
        choices=["none", "markers", "hkl"],
        help="单条谱标峰：markers=符号对应 PDF 卡片，hkl=晶面指数；默认不标",
    )
    p.add_argument(
        "--hkl-card",
        type=int,
        default=1,
        help="hkl 标峰使用第几张卡片（从 1 开始，默认第 1 张）",
    )
    p.add_argument(
        "--peak-tolerance",
        type=float,
        default=0.35,
        help="卡片峰与实测局部峰的匹配容差（°；默认 0.35）",
    )
    p.add_argument(
        "--observed-min-fraction",
        type=float,
        default=0.05,
        help="实测局部峰至少达到归一化最大强度的比例（默认 0.05）",
    )
    p.add_argument(
        "--marker-min-intensity",
        type=float,
        default=5.0,
        help="markers 模式只标卡片中相对强度不低于该值的峰（默认 5）",
    )
    p.add_argument(
        "--hkl-min-intensity",
        type=float,
        default=15.0,
        help="hkl 模式只标卡片中相对强度不低于该值的峰（默认 15）",
    )
    p.add_argument("--hkl-label-size", type=float, default=8.0, help="hkl 标签字号")
    p.add_argument("--width", type=float, default=3.6, help="图宽（英寸，默认 3.6，约单栏）")
    p.add_argument("--height", type=float, default=4.2, help="图高（英寸，默认 4.2）")
    p.add_argument("--dpi", type=int, default=600, help="位图分辨率（默认 600 dpi）")
    p.add_argument("--formats", default="png,pdf,svg", help="导出格式，逗号分隔（默认 png,pdf,svg）")
    return p


def parse_col_arg(value: str | None, label: str) -> tuple[int, int] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.replace("，", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise SystemExit(f"--{label} 需要两个列号，例如 --{label} 1,2")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise SystemExit(f"--{label} 只能是整数列号，例如 --{label} 1,2")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    warnings: list[str] = []

    if args.smooth_polyorder < 1:
        raise SystemExit("--smooth-polyorder 必须至少为 1")
    if args.smooth_window <= args.smooth_polyorder:
        raise SystemExit("--smooth-window 必须大于 --smooth-polyorder")
    if args.smooth_window % 2 == 0:
        args.smooth_window += 1
        warnings.append(f"Savitzky-Golay 窗口自动调整为奇数 {args.smooth_window}")

    if args.wavelength:
        wavelength = args.wavelength
        radiation_label = f"自定义 λ = {wavelength} Å"
    else:
        wavelength, radiation_label = RADIATIONS[args.radiation]

    args.colors = [c.strip() for c in args.colors.split(",") if c.strip()] or DEFAULT_COLORS[:1]
    args.card_colors = (
        [c.strip() for c in args.card_colors.split(",") if c.strip()]
        or DEFAULT_CARD_COLORS[:1]
    )

    if args.demo:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="xrd_demo_"))
        demo_samples, demo_cards = demo_inputs(tmp)
        args.sample = [f"{n}={p}" for n, p in demo_samples]
        args.card = [f"{n}={p}" for n, p in demo_cards]
        print(f"[demo] 合成数据目录：{tmp}")

    sample_specs = [parse_pair_spec(s) for s in args.sample]
    card_specs = [parse_pair_spec(c) for c in args.card]
    if not card_specs and not sample_specs:
        build_parser().print_help()
        return 2

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_cols = parse_col_arg(args.sample_cols, "sample-cols")
    card_cols = parse_col_arg(args.card_cols, "card-cols")

    samples: list[dict] = []
    for name, path in sample_specs:
        if not path.exists():
            raise SystemExit(f"找不到样品文件：{path}")
        item = parse_sample(path, sample_cols, warnings)
        item["name"] = name
        samples.append(item)

    cards: list[dict] = []
    for name, path in card_specs:
        if not path.exists():
            raise SystemExit(f"找不到卡片文件：{path}")
        item = parse_card(path, args.card_kind, card_cols, wavelength, warnings)
        item["name"] = name
        cards.append(item)

    written = write_card_tables(out_dir, cards)
    outputs = {"cards_clean": written}

    # 卡片数量与样品数量不匹配时不强行配对，交给用户决定
    card_owner: list[int | None] = [None] * len(cards)
    if samples and cards and args.card_position == "per-sample":
        if len(cards) == len(samples):
            card_owner = list(range(len(cards)))
        else:
            warnings.append(
                f"卡片数（{len(cards)}）与样品数（{len(samples)}）不一致，无法一一对应；"
                "卡片已统一排在图的底部。若物相与样品有明确对应关系，"
                "请让 --card 的顺序与 --sample 一致，或分别出图后自行拼版"
            )

    offsets = [i * (1.0 + args.gap) for i in range(max(len(samples), 1))]
    annotations = build_peak_annotations(args, samples, cards, offsets, warnings)

    if samples and not args.cards_only:
        outputs["origin"] = write_origin_tables(out_dir, samples, cards, args.norm, offsets)
        annotation_table = write_peak_annotations(out_dir, annotations)
        if annotation_table:
            outputs["peak_annotations"] = annotation_table
        try:
            fig = make_figure(
                args, samples, cards, offsets, card_owner, annotations, warnings
            )
        except ImportError:
            warnings.append(
                "未安装 matplotlib，已跳过出图；只导出数据表。"
                f"安装命令：\"{sys.executable}\" -m pip install --user matplotlib"
            )
        else:
            stem = out_dir / "xrd_stack"
            figure_files = []
            for fmt in [f.strip().lower() for f in args.formats.split(",") if f.strip()]:
                target = stem.with_suffix("." + fmt)
                fig.savefig(target, dpi=args.dpi, bbox_inches="tight", facecolor="white")
                figure_files.append(str(target))
            outputs["figure"] = figure_files
            import matplotlib.pyplot as plt
            plt.close(fig)

    manifest = {
        "generator": f"xrd_stack.py v{VERSION}",
        "created": datetime.now().isoformat(timespec="seconds"),
        "radiation": radiation_label,
        "wavelength_angstrom": wavelength,
        "normalization": args.norm,
        "gap": args.gap,
        "plot_processing": {
            "smoothing": args.smooth,
            "savgol_window": args.smooth_window,
            "savgol_polyorder": args.smooth_polyorder,
            "smoothing_scope": "display-only; Origin intensity tables remain raw",
        },
        "layout": {
            "card_position": args.card_position,
            "card_row_height": args.card_row_height,
            "stick_height": args.stick_height,
            "card_min_intensity": args.card_min_intensity,
            "single_sample": len(samples) == 1,
        },
        "peak_marking": {
            "mode": args.peak_marking,
            "hkl_card": args.hkl_card,
            "peak_tolerance": args.peak_tolerance,
            "observed_min_fraction": args.observed_min_fraction,
            "marker_min_intensity": args.marker_min_intensity,
            "hkl_min_intensity": args.hkl_min_intensity,
        },
        "peak_annotations": annotations,
        "offsets": offsets,
        "samples": [
            {k: v for k, v in s.items() if k not in ("two_theta", "intensity")} for s in samples
        ],
        "cards": [
            {k: v for k, v in c.items() if k not in ("two_theta", "intensity_raw", "intensity_rel100")}
            for c in cards
        ],
        "outputs": outputs,
        "warnings": warnings,
        "note": "本脚本不扣背景、不检索物相；显示平滑参数、卡片峰位与 λ 已记录，便于复现。",
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"输出目录：{out_dir}")
    for card in cards:
        top = "、".join(f"{p['two_theta']}°" for p in card["three_strongest"])
        print(f"  卡片 {card['name']}：{card['n_peaks']} 个峰位，按 {card['interpreted_as']} 解析，三强峰 {top}")
    for sample in samples:
        print(f"  样品 {sample['name']}：{sample['n_points']} 点，"
              f"2θ {sample['two_theta_range'][0]:.2f}~{sample['two_theta_range'][1]:.2f}°")
    for item in outputs.get("figure", []):
        print(f"  图形：{item}")
    if annotations:
        print(f"  单谱标峰：{len(annotations)} 条（{args.peak_marking}）")
    print(f"  记录：{manifest_path}")
    for warning in warnings:
        print(f"  ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
