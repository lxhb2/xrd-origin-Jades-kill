#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automate the safe parts of Jade 6.5 phase search and PDF-card export.

The script drives Jade's own GUI through Win32/pywinauto. It does not read,
copy, or redistribute the ICDD database. Search results are candidates only;
the user must confirm phase assignment with chemistry, synthesis conditions,
and literature evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Callable

VERSION = "2.2.0"

DEFAULT_JADE_EXE = Path(
    r"D:\百度网盘下载\XRD数据软件MDI Jade 6.5\MDI Jade 6.5\jade6.5.exe"
)
DEFAULT_PDF2_DB = Path(
    r"D:\百度网盘下载\XRD数据软件MDI Jade 6.5\PDF2-2004\pdf2.dat"
)

SEARCH_TASKS = [
    "Erase Listed Peaks",
    "Find All Peaks [Current Settings]",
    "Search/Match [Current Settings]",
    "     File S/M Hit Listing (*.JSM)",
]

PDF_NUMBER_RE = re.compile(r"(?P<num>\d{2,3}-\d{4,5})")
PDF_NUMBER_FULL_RE = re.compile(r"^\s*\d{2,3}-\d{4,5}\s*$")
CARD_MARKER_RE = re.compile(r"(?P<marker>P[0-9A-Z]{6})(?P<line>HI|X6|H6|X7|H7|H[0-9A-F])\s*$")
COMPACT_CARD_MARKER_RE = re.compile(
    r"(?P<marker>P[0-9A-Z]{6}(?:T|C|H|X|A)[0-9A-Z])\s*$"
)

# Element buttons in the classic Jade 6.5 "Current Chemistry" dialog are
# owner-drawn, so their locations are stable but they are not separate HWNDs.
# Coordinates are relative to the dialog's client area.
ELEMENT_BUTTONS: dict[str, tuple[int, int]] = {
    "H": (35, 57),
    "D": (66, 57),
    "He": (566, 57),
    "Li": (35, 83),
    "Be": (66, 83),
    "B": (410, 83),
    "C": (441, 83),
    "N": (472, 83),
    "O": (504, 83),
    "F": (535, 83),
    "Ne": (566, 83),
    "Na": (35, 109),
    "Mg": (66, 109),
    "Al": (410, 109),
    "Si": (441, 109),
    "P": (472, 109),
    "S": (504, 109),
    "Cl": (535, 109),
    "Ar": (566, 109),
    "K": (35, 136),
    "Ca": (66, 136),
    "Sc": (97, 136),
    "Ti": (129, 136),
    "V": (160, 136),
    "Cr": (191, 136),
    "Mn": (222, 136),
    "Fe": (254, 136),
    "Co": (285, 136),
    "Ni": (316, 136),
    "Cu": (347, 136),
    "Zn": (379, 136),
    "Ga": (410, 136),
    "Ge": (441, 136),
    "As": (472, 136),
    "Se": (504, 136),
    "Br": (535, 136),
    "Kr": (566, 136),
    "Rb": (35, 162),
    "Sr": (66, 162),
    "Y": (97, 162),
    "Zr": (129, 162),
    "Nb": (160, 162),
    "Mo": (191, 162),
    "Tc": (222, 162),
    "Ru": (254, 162),
    "Rh": (285, 162),
    "Pd": (316, 162),
    "Ag": (347, 162),
    "Cd": (379, 162),
    "In": (410, 162),
    "Sn": (441, 162),
    "Sb": (472, 162),
    "Te": (504, 162),
    "I": (535, 162),
    "Xe": (566, 162),
    "Cs": (35, 188),
    "Ba": (66, 188),
    "Hf": (129, 188),
    "Ta": (160, 188),
    "W": (191, 188),
    "Re": (222, 188),
    "Os": (254, 188),
    "Ir": (285, 188),
    "Pt": (316, 188),
    "Au": (347, 188),
    "Hg": (379, 188),
    "Tl": (410, 188),
    "Pb": (441, 188),
    "Bi": (472, 188),
    "Po": (504, 188),
    "At": (535, 188),
    "Rn": (566, 188),
    "Fr": (35, 214),
    "Ra": (66, 214),
    "La": (129, 221),
    "Ce": (160, 221),
    "Pr": (191, 221),
    "Nd": (222, 221),
    "Pm": (254, 221),
    "Sm": (285, 221),
    "Eu": (316, 221),
    "Gd": (347, 221),
    "Tb": (379, 221),
    "Dy": (410, 221),
    "Ho": (441, 221),
    "Er": (472, 221),
    "Tm": (504, 221),
    "Yb": (535, 221),
    "Lu": (566, 221),
    "Ac": (129, 247),
    "Th": (160, 247),
    "Pa": (191, 247),
    "U": (222, 247),
    "Np": (254, 247),
    "Pu": (285, 247),
    "Am": (316, 247),
    "Cm": (347, 247),
    "Bk": (379, 247),
    "Cf": (410, 247),
    "Es": (441, 247),
    "Fm": (472, 247),
    "Md": (504, 247),
    "No": (535, 247),
    "Lr": (566, 247),
}


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            # Tool/editor captures expect UTF-8; keep an interactive console's
            # native code page unchanged so direct Windows usage is readable.
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


_configure_console()
warnings.filterwarnings("ignore", message="32-bit application should be automated")
warnings.filterwarnings(
    "ignore",
    message="32-bit application should be automated using 32-bit Python.*",
)
warnings.filterwarnings(
    "ignore",
    message="32-bit application should be automated using 32-bit Python.*",
    module=r"pywinauto\.application",
)


def _gui_modules() -> dict[str, Any]:
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
        from pywinauto import Application, Desktop
        from pywinauto.controls.common_controls import ListViewWrapper
        from pywinauto.controls.win32_controls import ListBoxWrapper
    except ImportError as exc:
        raise SystemExit(
            "缺少 GUI 自动化依赖 pywinauto/pywin32。请运行：\n"
            f'  "{sys.executable}" -m pip install pywinauto pywin32'
        ) from exc
    # pywinauto installs an "always" filter for UserWarning at import time.
    # Re-register the expected 32-bit/64-bit notice as ignored after import so
    # tool logs stay readable when a 64-bit Python drives Jade 6.5.
    warnings.filterwarnings(
        "ignore",
        message="32-bit application should be automated using 32-bit Python.*",
        category=UserWarning,
        module=r"pywinauto\.application",
    )
    return {
        "win32api": win32api,
        "win32con": win32con,
        "win32gui": win32gui,
        "win32process": win32process,
        "Application": Application,
        "Desktop": Desktop,
        "ListViewWrapper": ListViewWrapper,
        "ListBoxWrapper": ListBoxWrapper,
    }


def _app(pid: int):
    return _gui_modules()["Application"](backend="win32").connect(process=pid)


def _windows(pid: int, visible_only: bool = False) -> list[Any]:
    win32gui = _gui_modules()["win32gui"]
    application = _gui_modules()["Application"](backend="win32")
    application.connect(process=pid)
    handles: list[int] = []

    def callback(handle, _):
        _, process_id = _gui_modules()["win32process"].GetWindowThreadProcessId(handle)
        if process_id != pid:
            return True
        if visible_only and not win32gui.IsWindowVisible(handle):
            return True
        handles.append(handle)
        return True

    win32gui.EnumWindows(callback, None)
    windows = []
    for handle in handles:
        try:
            windows.append(application.window(handle=handle))
        except Exception:
            continue
    return windows


def _wait_for(predicate: Callable[[], Any], timeout: float, interval: float = 0.25) -> Any:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def _title(window: Any) -> str:
    try:
        return window.window_text()
    except Exception:
        return ""


def _find_window(pid: int, title_contains: str, class_name: str | None = None):
    needle = title_contains.lower()
    matches = []
    for window in _windows(pid):
        if needle not in _title(window).lower():
            continue
        if class_name and window.class_name() != class_name:
            continue
        matches.append(window)
    for window in matches:
        try:
            if window.is_visible():
                return window
        except Exception:
            continue
    return None


def _uia_root(pid: int):
    desktop = _gui_modules()["Desktop"]
    for window in desktop(backend="uia").windows(process=pid, visible_only=False):
        if _title(window).startswith("Jade 6 ["):
            return window
    raise RuntimeError("UIAutomation 找不到 Jade 主窗口。")


def _uia_descendants(root: Any) -> list[Any]:
    try:
        return list(root.descendants())
    except Exception:
        return []


def _uia_window(pid: int, title_contains: str):
    root = _uia_root(pid)
    needle = title_contains.lower()
    matches = [
        control
        for control in _uia_descendants(root)
        if getattr(control.element_info, "control_type", "") == "Window"
        and needle in _title(control).lower()
    ]
    for control in matches:
        try:
            if control.is_visible():
                return control
        except Exception:
            continue
    return None


def _invoke_uia_menu(pid: int, command_id: int, timeout: float) -> None:
    """Open one top-level Jade menu and invoke a command by its UIA ID."""
    parent_menus = {
        125: "Analyze",
        147: "Identify",
        148: "Identify",
        163: "PDF",
        165: "PDF",
    }
    parent_title = parent_menus.get(command_id)
    if not parent_title:
        raise RuntimeError(f"没有为 Jade 菜单命令 {command_id} 配置父菜单。")
    last_error = ""
    for attempt in range(3):
        root = _uia_root(pid)
        menu = None
        for control in _uia_descendants(root):
            if (
                getattr(control.element_info, "control_type", "") == "MenuItem"
                and not getattr(control.element_info, "automation_id", "")
                and _title(control) == parent_title
            ):
                menu = control
                break
        if menu is None:
            last_error = f"没有找到 Jade 的 {parent_title} 菜单"
            time.sleep(0.35)
            continue
        try:
            menu.expand()
        except Exception as exc:
            last_error = f"无法展开 Jade 的 {parent_title} 菜单：{exc}"
            time.sleep(0.35)
            continue

        deadline = time.time() + min(timeout, 3.0)
        item = None
        while time.time() < deadline:
            root = _uia_root(pid)
            for control in _uia_descendants(root):
                if (
                    getattr(control.element_info, "control_type", "") == "MenuItem"
                    and str(getattr(control.element_info, "automation_id", ""))
                    == str(command_id)
                ):
                    item = control
                    break
            if item:
                break
            time.sleep(0.15)
        if item:
            item.invoke()
            time.sleep(min(0.5, max(0.15, timeout / 20.0)))
            return

        last_error = f"没有找到 Jade 菜单命令 {command_id}"
        try:
            menu.collapse()
        except Exception:
            pass
        time.sleep(0.35)
    raise RuntimeError(
        f"UIAutomation 没有打开 Jade 菜单命令 {command_id}：{last_error}。"
    )


def _invoke_uia_button(window: Any, automation_id: str | int, text: str | None = None) -> None:
    wanted = str(automation_id)
    for control in window.descendants():
        if (
            getattr(control.element_info, "control_type", "") == "Button"
            and str(getattr(control.element_info, "automation_id", "")) == wanted
            and (text is None or _title(control).strip() == text)
        ):
            control.invoke()
            return
    suffix = f"（{text}）" if text else ""
    raise RuntimeError(f"窗口里没有找到按钮 ID {wanted}{suffix}。")


def _send_menu_command(main: Any, command_id: int) -> None:
    """Invoke a classic Jade menu command without mouse or foreground input."""
    _gui_modules()["win32gui"].PostMessage(
        main.handle,
        _gui_modules()["win32con"].WM_COMMAND,
        command_id,
        0,
    )
    time.sleep(0.5)


def _click_win32_button(window: Any, title: str) -> None:
    target = title.strip().lstrip("&").lower()
    for child in window.children():
        if _title(child).strip().lstrip("&").lower() != target:
            continue
        _press_control(child)
        return
    raise RuntimeError(f"窗口里没有找到按钮：{title}")


def _press_control(control: Any) -> None:
    win32gui = _gui_modules()["win32gui"]
    win32con = _gui_modules()["win32con"]
    rect = win32gui.GetClientRect(control.handle)
    if hasattr(rect, "right"):
        width = rect.right - rect.left
        height = rect.bottom - rect.top
    else:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
    x = max(1, width // 2)
    y = max(1, height // 2)
    lparam = (y << 16) | (x & 0xFFFF)
    win32gui.PostMessage(control.handle, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.05)
    win32gui.PostMessage(control.handle, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.25)


def _click_client(window: Any, x: int, y: int) -> None:
    """Send a real click to a VB6 owner-drawn control without moving the cursor."""
    win32gui = _gui_modules()["win32gui"]
    win32con = _gui_modules()["win32con"]
    lparam = (int(y) << 16) | (int(x) & 0xFFFF)
    win32gui.PostMessage(window.handle, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.05)
    win32gui.PostMessage(window.handle, win32con.WM_LBUTTONUP, 0, lparam)


def _capture_window(window: Any):
    ImageGrab = None
    try:
        from PIL import ImageGrab as _ImageGrab

        ImageGrab = _ImageGrab
    except ImportError:
        return None

    win32gui = _gui_modules()["win32gui"]
    win32con = _gui_modules()["win32con"]
    rect = window.rectangle()
    try:
        win32gui.SetWindowPos(
            window.handle,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
        time.sleep(0.15)
        image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    finally:
        try:
            win32gui.SetWindowPos(
                window.handle,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
        except Exception:
            pass
    return image


def _list_item_checked(window: Any, item: Any) -> bool | None:
    """Read Jade's owner-drawn checklist state from a small screenshot."""
    image = _capture_window(window)
    if image is None:
        return None
    win_rect = window.rectangle()
    item_rect = item.rectangle()
    # The checklist glyph occupies the first few pixels of the row.
    left = max(0, item_rect.left - win_rect.left + 4)
    top = max(0, item_rect.top - win_rect.top + 4)
    dark = 0
    for y in range(top, min(image.height, top + 9)):
        for x in range(left, min(image.width, left + 9)):
            pixel = image.getpixel((x, y))
            if isinstance(pixel, tuple):
                value = max(pixel[:3])
            else:
                value = int(pixel)
            if value < 150:
                dark += 1
    return dark >= 3


def _set_list_item_checked(window: Any, item: Any, checked: bool) -> None:
    current = _list_item_checked(window, item)
    if current is None:
        # UIA's custom Jade list does not expose TogglePattern. If the
        # screenshot backend is unavailable, do not risk silently searching
        # without the requested chemistry constraint.
        raise RuntimeError(
            "无法确认 Jade 的 Use Chemistry Filter 是否已勾选。"
            "请在 Jade 中确认该项已勾选后重试。"
        )
    if current != checked:
        item.invoke()
        time.sleep(0.25)


def _find_data_window(pid: int):
    matches = []
    for window in _windows(pid):
        title = _title(window)
        if window.class_name() == "ThunderRT5Form" and title.startswith("Jade 6 ["):
            matches.append(window)
    for window in matches:
        try:
            if window.is_visible():
                return window
        except Exception:
            continue
    return None


def _find_jade_pid():
    desktop = _gui_modules()["Desktop"]
    for window in desktop(backend="win32").windows(visible_only=False):
        title = _title(window)
        if window.class_name() == "ThunderRT5Main" and title == "MDI Jade 6.5":
            return window.process_id()
        if window.class_name() == "ThunderRT5Form" and title.startswith("Jade 6 ["):
            return window.process_id()
    return None


def _wait_for_jade(pid: int | None, timeout: float) -> int:
    def check():
        found = pid or _find_jade_pid()
        if not found:
            return None
        return found if _find_data_window(found) else None

    found = _wait_for(check, timeout)
    if not found:
        raise SystemExit("Jade 未在限定时间内启动或主窗口未就绪。")
    return int(found)


def _select_menu_command(main: Any, item_id: int) -> None:
    def walk(menu: Any) -> bool:
        for item in menu.items():
            try:
                current_id = item.item_id()
            except Exception:
                current_id = -1
            if current_id == item_id:
                item.select()
                return True
            try:
                submenu = item.sub_menu()
            except Exception:
                submenu = None
            if submenu and walk(submenu):
                return True
        return False

    if not walk(main.menu()):
        raise RuntimeError(f"没有找到 Jade 菜单命令 ID {item_id}")


def _post_close(window: Any) -> None:
    try:
        _gui_modules()["win32gui"].PostMessage(
            window.handle, _gui_modules()["win32con"].WM_CLOSE, 0, 0
        )
    except Exception:
        pass


def _dismiss_error_windows(pid: int) -> None:
    """Close Jade's known modal error log so later GUI steps are actionable."""
    for window in _windows(pid):
        title = _title(window).lower()
        if "jade6.err" not in title:
            continue
        for child in window.descendants():
            if _title(child).strip().lower() not in {"&close", "&ok"}:
                continue
            try:
                if child.is_visible():
                    _gui_modules()["win32gui"].SendMessage(
                        child.handle,
                        _gui_modules()["win32con"].BM_CLICK,
                        0,
                        0,
                    )
                    time.sleep(0.3)
                    break
            except Exception:
                continue


def _dismiss_startup_dialogs(pid: int) -> None:
    for window in _windows(pid):
        if "Select Project ID to Run JADE" not in _title(window):
            continue
        for child in window.descendants():
            if _title(child).strip().lower() != "&select":
                continue
            try:
                if child.is_visible():
                    _gui_modules()["win32gui"].SendMessage(
                        child.handle,
                        _gui_modules()["win32con"].BM_CLICK,
                        0,
                        0,
                    )
                    time.sleep(0.4)
                    break
            except Exception:
                continue


def _close_matching(pid: int, title_contains: str) -> None:
    for window in _windows(pid):
        if title_contains.lower() in _title(window).lower():
            _post_close(window)
    time.sleep(0.4)


def _reset_workflow_windows(pid: int) -> None:
    for title in (
        "Enter File Name to Save",
        "Current Chemistry",
        "Phase ID - Search/Match",
        "Search/Match Display",
        "PDF Retrievals",
        "PDF#",
    ):
        _close_matching(pid, title)


def _load_pattern(main: Any, pattern: Path, timeout: float) -> Any:
    pattern = pattern.expanduser().resolve()
    if not pattern.exists():
        raise SystemExit(f"找不到 XRD 文件：{pattern}")

    current = _find_data_window(main.process_id())
    if current and pattern.name.lower() in _title(current).lower():
        return current

    _select_menu_command(main, 8)  # File -> Read...
    dialog = _wait_for(
        lambda: _find_window(main.process_id(), "Select a File to Read or Browse"),
        timeout,
    )
    if not dialog:
        raise RuntimeError("Jade 没有打开文件选择窗口。")

    edits = [child for child in dialog.children() if child.class_name() == "Edit"]
    if not edits:
        raise RuntimeError("文件选择窗口里没有找到文件名输入框。")
    file_edit = max(edits, key=lambda item: item.rectangle().top)
    file_edit.set_edit_text(str(pattern))

    button = None
    for child in dialog.children():
        if child.class_name() != "Button":
            continue
        if _gui_modules()["win32gui"].GetDlgCtrlID(child.handle) == 1:
            button = child
            break
    if button is None:
        raise RuntimeError("文件选择窗口里没有找到“打开”按钮。")
    _gui_modules()["win32gui"].SendMessage(
        button.handle,
        _gui_modules()["win32con"].BM_CLICK,
        0,
        0,
    )

    def loaded():
        current_window = _find_data_window(main.process_id())
        if current_window and pattern.name.lower() in _title(current_window).lower():
            return current_window
        return None

    loaded_window = _wait_for(loaded, timeout)
    if not loaded_window:
        _close_matching(main.process_id(), "Select a File to Read or Browse")
        raise RuntimeError(
            f"Jade 没有成功载入 {pattern.name}。若该格式需要专用导入对话框，"
            "请先在 Jade 中打开一次，再使用 --no-load。"
        )
    return loaded_window


def _pattern_from_data_window(data_window: Any) -> str:
    title = _title(data_window)
    matches = re.findall(r"\[([^\]]+)\]", title)
    for value in reversed(matches):
        if re.search(r"\.(?:mdi|raw|asc|txt|csv|dif|bin)$", value, re.I):
            return value
    if matches:
        return matches[-1]
    raise RuntimeError("无法从 Jade 标题识别当前样品文件名。")


def _start_or_find_jade(jade_exe: Path, timeout: float) -> tuple[int, Any]:
    pid = _find_jade_pid()
    if pid is None:
        if not jade_exe.exists():
            raise SystemExit(f"找不到 Jade 程序：{jade_exe}")
        subprocess.Popen([str(jade_exe)], cwd=str(jade_exe.parent))
    pid = _wait_for_jade(pid, timeout)
    _dismiss_startup_dialogs(pid)
    _dismiss_error_windows(pid)
    main = _find_data_window(pid)
    if not main:
        raise RuntimeError("Jade 主窗口未就绪。")
    return pid, main


def _macro_file() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Microsoft" / "Windows" / "MDI Jade 6" / "jade6.m01"


def _task_listboxes(window: Any) -> tuple[Any, Any]:
    wrappers = []
    for child in window.children():
        if child.class_name() != "ThunderRT5ListBox":
            continue
        rect = child.rectangle()
        if rect.bottom - rect.top > 180 and rect.right - rect.left > 250:
            wrappers.append(child)
    if len(wrappers) < 2:
        raise RuntimeError("任务宏窗口里的任务列表没有按预期显示。")
    wrappers.sort(key=lambda item: item.rectangle().left)
    return wrappers[0], wrappers[-1]


def _clear_listbox(listbox: Any) -> None:
    for _ in range(80):
        if not listbox.item_texts():
            return
        rect = listbox.item_rect(0)
        x = max(1, (rect.right - rect.left) // 2)
        y = max(1, (rect.bottom - rect.top) // 2)
        listbox.double_click_input(coords=(x, y))
        time.sleep(0.1)
    raise RuntimeError("任务宏列表无法清空。")


def _add_macro_task(available: Any, label: str) -> None:
    texts = available.item_texts()
    try:
        index = texts.index(label)
    except ValueError:
        matches = [idx for idx, text in enumerate(texts) if label.strip() in text]
        if len(matches) != 1:
            raise RuntimeError(f"Jade 任务宏列表里找不到任务：{label}")
        index = matches[0]
    available.select(index)
    available.set_focus()
    available.type_keys("{ENTER}")
    time.sleep(0.15)


def _click_button(window: Any, title: str) -> None:
    for child in window.children():
        if _title(child).strip() == title:
            child.click_input()
            return
    raise RuntimeError(f"窗口里没有找到按钮：{title}")


def _save_macro(window: Any, pid: int, name: str, timeout: float) -> None:
    _click_button(window, "&Apply")
    time.sleep(0.8)
    if _macro_file().exists():
        return

    _click_button(window, "&Save")
    name_dialog = _wait_for(
        lambda: _find_window(pid, "Enter Name to Save the Macro"), timeout
    )
    if not name_dialog:
        raise RuntimeError("保存任务宏时没有出现命名窗口。")
    edit = None
    for child in name_dialog.children():
        if "TextBox" in child.class_name() or child.class_name() == "Edit":
            edit = child
            break
    if edit is None:
        raise RuntimeError("任务宏命名窗口里没有输入框。")
    edit.set_focus()
    edit.type_keys("^a")
    edit.type_keys(name)
    _click_button(name_dialog, "&OK")


def _build_search_macro(pid: int, main: Any, timeout: float) -> bytes | None:
    macro_file = _macro_file()
    backup = macro_file.read_bytes() if macro_file.exists() else None
    macro_file.parent.mkdir(parents=True, exist_ok=True)

    _select_menu_command(main, 142)  # Analyze -> Auto-Processing -> Setup Task Macros
    window = _wait_for(
        lambda: _find_window(pid, "Auto-Processing with Task Macros"), timeout
    )
    if not window:
        raise RuntimeError("Jade 没有打开任务宏设置窗口。")

    available, current = _task_listboxes(window)
    _clear_listbox(current)
    for label in SEARCH_TASKS:
        _add_macro_task(available, label)
    _save_macro(window, pid, "codex_xrd_auto", timeout)
    _click_button(window, "&Close")
    time.sleep(0.5)
    return backup


def _restore_macro(backup: bytes | None) -> None:
    macro_file = _macro_file()
    if backup is None:
        try:
            macro_file.unlink()
        except FileNotFoundError:
            pass
        return
    macro_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        macro_file.write_bytes(backup)
    except PermissionError:
        time.sleep(0.5)
        macro_file.write_bytes(backup)


def _run_macro_and_wait(main: Any, pattern_name: str, timeout: float) -> Path:
    data_dir = _macro_file().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    expected = data_dir / f"{Path(pattern_name).stem}.jsm"
    before = {path: path.stat().st_mtime_ns for path in data_dir.glob("*.jsm")}
    start = time.time()
    _select_menu_command(main, 144)  # Analyze -> Auto-Processing -> Run [...]

    def finished() -> Path | None:
        if expected.exists():
            stamp = expected.stat().st_mtime_ns
            if before.get(expected) != stamp and stamp >= int((start - 1) * 1e9):
                return expected
        changed = [
            path
            for path in data_dir.glob("*.jsm")
            if before.get(path) != path.stat().st_mtime_ns
        ]
        if changed:
            return max(changed, key=lambda path: path.stat().st_mtime_ns)
        return None

    result = _wait_for(finished, timeout)
    if not result:
        raise TimeoutError(
            "任务宏运行后没有检测到新的 JSM 命中列表。"
            "请检查 Jade 当前峰位/检索设置是否可用。"
        )
    return result


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_elements(value: str | None, formula: str | None = None) -> list[str]:
    candidates: list[str] = []
    if value:
        candidates.extend(re.split(r"[\s,;+/]+", value.strip()))
    if formula:
        candidates.extend(re.findall(r"[A-Z][a-z]?", formula))
    known = set(ELEMENT_BUTTONS)
    result: list[str] = []
    unknown: list[str] = []
    for candidate in candidates:
        symbol = candidate.strip()
        if not symbol:
            continue
        symbol = symbol[0].upper() + symbol[1:].lower()
        if symbol not in known:
            unknown.append(symbol)
            continue
        if symbol not in result:
            result.append(symbol)
    if unknown:
        raise SystemExit(f"Jade 元素周期表不支持的符号：{', '.join(unknown)}")
    return result


def _chemistry_filter_file() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Microsoft" / "Windows" / "MDI Jade 6" / "jade6.cff"


def _backup_chemistry_filter() -> bytes | None:
    path = _chemistry_filter_file()
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_chemistry_filter(backup: bytes | None) -> None:
    path = _chemistry_filter_file()
    if backup is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(backup)


def _set_chemistry_filter(
    pid: int,
    main: Any,
    elements: list[str],
    timeout: float,
    filter_mode: str = "possible",
) -> None:
    if not elements:
        raise SystemExit(
            "Jade 检索前必须提供元素和化学式。请先询问用户；"
            "如果用户没有，再获取样品信息或研究方向后归纳常规元素和化学式。"
        )
    unsupported = [symbol for symbol in elements if symbol not in ELEMENT_BUTTONS]
    if unsupported:
        raise SystemExit(f"Jade 元素周期表不支持：{', '.join(unsupported)}")
    if filter_mode not in {"possible", "required"}:
        raise SystemExit("filter_mode 只能是 possible 或 required。")

    _reset_workflow_windows(pid)
    _send_menu_command(main, 165)  # PDF -> Chemistry...
    window = _wait_for(lambda: _uia_window(pid, "Current Chemistry"), timeout)
    if not window:
        _invoke_uia_menu(pid, 165, timeout)
        window = _wait_for(lambda: _uia_window(pid, "Current Chemistry"), timeout)
    if not window:
        raise RuntimeError("Jade 没有打开 Current Chemistry 窗口。")
    _click_win32_button(window, "Exclude All")
    time.sleep(0.25)

    client = _gui_modules()["win32gui"].GetClientRect(window.handle)
    if hasattr(client, "right"):
        client_width = client.right - client.left
        client_height = client.bottom - client.top
    else:
        left, top, right, bottom = client
        client_width = right - left
        client_height = bottom - top
    # The dialog is fixed-size in Jade 6.5. Scaling only protects against a
    # non-standard DPI/layout; if it differs substantially, fail rather than
    # clicking the wrong element.
    if not (560 <= client_width <= 650 and 300 <= client_height <= 360):
        raise RuntimeError(
            "Current Chemistry 窗口尺寸异常，无法可靠定位元素按钮。"
            "请在 Jade 中恢复默认窗口大小后重试。"
        )
    scale_x = client_width / 601.0
    scale_y = client_height / 330.0
    click_count = 1 if filter_mode == "possible" else 2
    for symbol in elements:
        base_x, base_y = ELEMENT_BUTTONS[symbol]
        x = int(round(base_x * scale_x))
        y = int(round(base_y * scale_y))
        # Jade cycles: excluded -> possible -> required. A mixed-phase sample
        # usually needs Possible because each phase need not contain every
        # selected element (for example quartz contains only Si).
        for _ in range(click_count):
            _click_client(window, x, y)
            time.sleep(0.18)

    # Save writes the local chemistry filter file. The caller backs this file
    # up and restores it after the search, so the user's own filter is intact.
    target = _chemistry_filter_file()
    before_mtime = target.stat().st_mtime_ns if target.exists() else None
    _click_win32_button(window, "Save")
    save_dialog = _wait_for(
        lambda: _find_window(pid, "Enter File Name to Save"),
        min(timeout, 5.0),
        interval=0.15,
    )
    if not save_dialog:
        raise RuntimeError("Jade 元素筛选没有触发保存窗口。")
    text_box = None
    ok_button = None
    for child in save_dialog.children():
        if child.class_name() == "ThunderRT5TextBox":
            text_box = child
        if _title(child).strip() == "&OK":
            ok_button = child
    if text_box is None or ok_button is None:
        raise RuntimeError("保存化学筛选文件时控件结构异常。")
    win32gui = _gui_modules()["win32gui"]
    win32con = _gui_modules()["win32con"]
    win32gui.SendMessage(
        text_box.handle,
        win32con.WM_SETTEXT,
        0,
        target.name,
    )
    _press_control(ok_button)
    closed = _wait_for(
        lambda: not _find_window(pid, "Enter File Name to Save"),
        min(timeout, 5.0),
        interval=0.15,
    )
    if not closed:
        raise RuntimeError("Jade 化学筛选文件没有保存成功。")
    if not target.exists():
        raise RuntimeError(f"Jade 没有写出化学筛选文件：{target}")
    after_mtime = target.stat().st_mtime_ns
    if before_mtime is not None and after_mtime == before_mtime:
        raise RuntimeError(
            "Jade 化学筛选文件内容没有更新。请确认元素已选中且保存窗口路径正确。"
        )
    # Save has already written the new chemistry filter. Cancel closes this
    # dialog without applying any further global changes.
    _click_win32_button(window, "Cancel")


def _run_find_peaks(pid: int, main: Any, timeout: float) -> None:
    _close_matching(pid, "Peak Search, Labeling & Scaling")
    _send_menu_command(main, 125)  # Analyze -> Find Peaks...
    peak_search = _wait_for(
        lambda: _find_window(pid, "Peak Search, Labeling & Scaling"),
        min(timeout, 10.0),
        interval=0.25,
    )
    if not peak_search:
        try:
            _invoke_uia_menu(pid, 125, timeout)
        except Exception:
            pass
        peak_search = _wait_for(
            lambda: _find_window(pid, "Peak Search, Labeling & Scaling"),
            min(timeout, 10.0),
            interval=0.25,
        )
    if not peak_search:
        raise RuntimeError("Jade 没有打开 Peak Search 窗口。")

    apply_button = None
    close_button = None
    for child in peak_search.descendants():
        title = _title(child).strip()
        if title == "&Apply":
            apply_button = child
        elif title == "&Close":
            close_button = child
    if apply_button is None or close_button is None:
        raise RuntimeError("Peak Search 窗口里没有找到 Apply/Close 按钮。")
    _press_control(apply_button)
    time.sleep(1.5)
    _press_control(close_button)
    time.sleep(0.3)


def _run_search_match(pid: int, main: Any, timeout: float) -> None:
    _reset_workflow_windows(pid)
    time.sleep(0.3)
    _send_menu_command(main, 147)  # Identify -> Search/Match Setup...
    deadline = time.time() + timeout
    setup = None
    while time.time() < deadline:
        for window in _windows(pid):
            if _title(window).strip() != "MDI Jade 6.5":
                continue
            buttons = {
                _title(child).strip().lstrip("&").lower(): child
                for child in window.children()
                if child.class_name() == "ThunderRT5CommandButton"
                and child.is_visible()
            }
            if "yes" in buttons and "no" in buttons and "ignore" not in buttons:
                # Do not alter the pattern; the data-processing decision
                # belongs to the user and must be documented separately.
                _press_control(buttons["no"])
                time.sleep(0.4)
                break
        setup = _uia_window(pid, "Phase ID - Search/Match")
        if setup:
            break
        time.sleep(0.25)
    if not setup:
        _invoke_uia_menu(pid, 147, timeout)
        setup = _wait_for(lambda: _uia_window(pid, "Phase ID - Search/Match"), timeout)
    if not setup:
        raise RuntimeError("Jade 没有打开 Search/Match Setup 窗口。")
    item = None
    for control in setup.descendants():
        if (
            getattr(control.element_info, "control_type", "") == "ListItem"
            and _title(control).strip() == "Use Chemistry Filter"
        ):
            item = control
            break
    if item is None:
        raise RuntimeError("Search/Match Setup 里没有找到 Use Chemistry Filter。")
    _set_list_item_checked(setup, item, True)
    _invoke_uia_button(setup, 7, "OK")
    if not _wait_for(lambda: _find_window(pid, "Search/Match Display"), timeout):
        _dismiss_error_windows(pid)
        raise RuntimeError(
            "Search/Match 没有生成候选列表。请检查 Jade 是否已有峰位、"
            "数据库是否可用，以及化学筛选文件是否能被检索。"
        )


def _find_candidate_list_view(pid: int):
    ListViewWrapper = _gui_modules()["ListViewWrapper"]
    display = _wait_for(lambda: _find_window(pid, "Search/Match Display"), 0.1)
    if not display:
        return None
    for handle in _child_handles(display.handle, "ListView20WndClass"):
        try:
            control = ListViewWrapper(handle)
            columns = [item.get("text", "") for item in control.columns()]
            if "PDF-#" in columns and control.item_count() > 0:
                return display, control
        except Exception:
            continue
    return None


def _read_search_display(pid: int, timeout: float) -> list[dict[str, Any]]:
    found = _wait_for(lambda: _find_candidate_list_view(pid), timeout, interval=0.35)
    if not found:
        raise TimeoutError("没有检测到 Search/Match Display 的候选卡片列表。")
    _, control = found
    try:
        columns = [item.get("text", "") for item in control.columns()]
    except Exception:
        columns = []
    rows: list[dict[str, Any]] = []
    texts = control.texts()
    count = control.column_count()
    if count <= 0:
        return rows
    for index in range(control.item_count()):
        values = texts[index * count : (index + 1) * count]
        joined = "\t".join(values)
        number = PDF_NUMBER_RE.search(joined)
        if not number:
            continue

        def value(index: int, default: str = "") -> str:
            return values[index] if index < len(values) else default

        # Jade's ListView has an unlabeled index column before the visible
        # headers, so data columns are shifted one position from the header.
        fom_text = value(3).strip()
        try:
            fom = float(fom_text)
        except ValueError:
            fom = None
        rows.append(
            {
                "phase": value(1),
                "formula": value(2),
                "fom": fom,
                "pdf_number": number.group("num"),
                "hits": value(7),
                "d_i_count": value(8),
                "i_percent": value(9),
                "two_theta_offset": value(10),
                "space_group": value(13),
            }
        )
    return rows


def _parse_jsm(path: Path) -> list[dict[str, Any]]:
    lines = _read_text(path).splitlines()
    header_index = None
    header = ""
    for index, line in enumerate(lines):
        if "Hits Sorted" in line and "PDF-#" in line:
            header_index = index
            header = line
            break
    if header_index is None:
        raise RuntimeError(f"{path.name} 不是可识别的 Jade JSM 命中列表。")

    def pos(label: str, start: int = 0) -> int:
        value = header.find(label, start)
        return value if value >= 0 else start

    formula_col = pos("Chemical Formula")
    fom_col = pos("FOM", formula_col + 1)
    j_col = pos("J", fom_col + 1)
    d_col = pos("D", j_col + 1)
    pdf_col = pos("PDF-#", d_col + 1)
    hits_col = pos("Hits", pdf_col + 1)
    ndi_col = pos("#d/I", hits_col + 1)
    ipct_col = pos("I%", ndi_col + 1)
    two_theta_col = pos("2T", ipct_col + 1)

    rows: list[dict[str, Any]] = []
    for line in lines[header_index + 1 :]:
        if not line.startswith("[ ]"):
            if rows:
                break
            continue
        # Jade's fixed-width header and data rows can differ by one column.
        # Search the whole row for the card number instead of trusting the
        # header offset for this field.
        match = PDF_NUMBER_RE.search(line)
        if not match:
            continue
        fom_text = line[fom_col:j_col].strip()
        try:
            fom = float(fom_text)
        except ValueError:
            fom = None
        rows.append(
            {
                "phase": line[4:formula_col].strip(),
                "formula": line[formula_col:fom_col].strip(),
                "fom": fom,
                "pdf_number": match.group("num"),
                "hits": line[hits_col:ndi_col].strip(),
                "d_i_count": line[ndi_col:ipct_col].strip(),
                "i_percent": line[ipct_col:two_theta_col].strip(),
            }
        )
    return rows


def _write_candidates(
    rows: list[dict[str, Any]],
    out_dir: Path,
    source: str | Path,
    metadata: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "candidates.json"
    csv_path = out_dir / "candidates.csv"
    payload = {
        "generator": f"jade_phaseid.py v{VERSION}",
        "source": str(source),
        "note": "这些是 Search/Match 候选卡片，不是自动确认的物相。",
        "search": metadata or {},
        "candidates": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = [
        "phase",
        "formula",
        "fom",
        "pdf_number",
        "hits",
        "d_i_count",
        "i_percent",
        "two_theta_offset",
        "space_group",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _normalize_pdf_number(value: str) -> str:
    numbers = re.findall(r"\d{2,5}", value)
    if len(numbers) >= 2:
        return f"{int(numbers[-2]):02d}-{int(numbers[-1]):04d}"
    if len(numbers) == 1 and len(numbers[0]) >= 6:
        text = numbers[0].zfill(7)
        return f"{int(text[:-4]):02d}-{int(text[-4:]):04d}"
    raise ValueError(f"无法识别 PDF 卡片号：{value}")


def _child_handles(root_handle: int, class_name: str) -> list[int]:
    win32gui = _gui_modules()["win32gui"]
    handles: list[int] = []

    def callback(handle, _):
        if win32gui.GetClassName(handle) == class_name:
            handles.append(handle)
        return True

    win32gui.EnumChildWindows(root_handle, callback, None)
    return handles


def _find_retrieval_edit(window: Any):
    edits = []
    for child in window.descendants():
        if child.class_name() != "Edit":
            continue
        text = _title(child).strip()
        rect = child.rectangle()
        if 150 < rect.top < 260:
            edits.append((child, text))

    # On a clean window the card selector is the second combo box in the
    # filter row: subset database | card browser | chemistry filter.
    combos = [
        child
        for child in window.descendants()
        if child.class_name() == "ThunderRT5ComboBox"
        and 150 < child.rectangle().top < 260
        and child.is_visible()
    ]
    combos.sort(key=lambda child: child.rectangle().left)
    if len(combos) >= 2:
        card_combo = combos[1]
        for child, _ in edits:
            if card_combo.rectangle().left <= child.rectangle().left <= card_combo.rectangle().right:
                return child

    # Fall back to an edit that already contains a card-looking value.
    for child, text in edits:
        if PDF_NUMBER_RE.search(text):
            return child

    if edits:
        return edits[0][0]
    raise RuntimeError("PDF 检索窗口里没有找到卡片号输入框。")


def _find_result_list(window: Any, pdf_number: str):
    ListViewWrapper = _gui_modules()["ListViewWrapper"]
    for handle in _child_handles(window.handle, "ListView20WndClass"):
        try:
            control = ListViewWrapper(handle)
            columns = [item.get("text", "") for item in control.columns()]
            if "PDF-#" not in columns or control.item_count() == 0:
                continue
            if pdf_number in "\n".join(control.texts()):
                return control
        except Exception:
            continue
    return None


def _open_card_window(pid: int, retrieval: Any, pdf_number: str, timeout: float) -> Any:
    edit = _find_retrieval_edit(retrieval)
    # Send WM messages so the script also works without an active desktop.
    win32gui = _gui_modules()["win32gui"]
    win32con = _gui_modules()["win32con"]
    win32gui.SendMessage(edit.handle, win32con.WM_SETTEXT, 0, pdf_number)
    for target in (edit, edit.parent()):
        win32gui.SendMessage(
            target.handle,
            win32con.WM_KEYDOWN,
            win32con.VK_RETURN,
            0x001C0001,
        )
        win32gui.SendMessage(
            target.handle,
            win32con.WM_CHAR,
            win32con.VK_RETURN,
            0x001C0001,
        )
        win32gui.SendMessage(
            target.handle,
            win32con.WM_KEYUP,
            win32con.VK_RETURN,
            0xC01C0001,
        )
    result_list = _wait_for(
        lambda: _find_result_list(retrieval, pdf_number),
        timeout,
        interval=0.4,
    )
    if not result_list:
        raise RuntimeError(f"PDF 检索没有返回卡片 {pdf_number}。")

    target_index = None
    for index in range(result_list.item_count()):
        row_text = "\t".join(result_list.texts()[index * result_list.column_count() : (index + 1) * result_list.column_count()])
        if pdf_number in row_text:
            target_index = index
            break
    if target_index is None:
        target_index = 0
    result_list.select(target_index)
    try:
        result_list.item(target_index).ensure_visible()
    except Exception:
        pass

    # The report-view item rectangles from this Jade ListView are offset by
    # roughly one row relative to its hit-test coordinates. Clicking the
    # rectangle's vertical centre therefore opens the previous card. Probe a
    # few coordinates around the requested row and accept only the matching
    # PDF# window.
    rect = result_list.get_item_rect(target_index)
    client = result_list.client_rect()
    row_height = max(1, rect.bottom - rect.top)
    x = max(2, min((rect.left + rect.right) // 2, client.right - 2))
    y_candidates = (
        min(client.bottom - 2, rect.bottom + 1),
        min(client.bottom - 2, rect.bottom + row_height // 2),
        max(2, rect.top + row_height + 1),
        max(2, (rect.top + rect.bottom) // 2),
    )

    def matching_card_window():
        return next(
            (
                window
                for window in _windows(pid)
                if _title(window).startswith("PDF#")
                and pdf_number in _title(window)
            ),
            None,
        )

    for y in dict.fromkeys(y_candidates):
        result_list.double_click_input(coords=(x, int(y)))
        card_window = _wait_for(matching_card_window, min(timeout, 4.0), interval=0.2)
        if card_window:
            return card_window

        # Close a wrong row if the coordinate probe opened the neighbouring
        # card, then try the next calibrated point.
        for window in _windows(pid):
            title = _title(window)
            if title.startswith("PDF#") and pdf_number not in title:
                _post_close(window)
        time.sleep(0.2)

    # Fallback for environments where pywinauto input is unavailable.
    lparam = ((int(y_candidates[0]) & 0xFFFF) << 16) | (x & 0xFFFF)
    for message, modifier in (
        (win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON),
        (win32con.WM_LBUTTONUP, 0),
        (win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON),
        (win32con.WM_LBUTTONUP, 0),
    ):
        win32gui.SendMessage(result_list.handle, message, modifier, lparam)
        time.sleep(0.05)
    card_window = _wait_for(
        matching_card_window,
        timeout,
        interval=0.3,
    )
    if not card_window:
        raise RuntimeError(f"卡片 {pdf_number} 没有打开。")
    return card_window


def _parse_card_text(raw: str, pdf_number: str) -> dict[str, Any]:
    lines = raw.splitlines()
    peaks: list[dict[str, Any]] = []

    def parse_chunk(chunk: str) -> dict[str, Any] | None:
        if len(chunk) < 10:
            return None
        d_text = chunk[0:7].strip()
        intensity_text = re.sub(r"[^0-9.]", "", chunk[7:10])
        hkl = re.sub(r"[^0-9\-\s]", " ", chunk[10:23])
        hkl = re.sub(r"\s+", " ", hkl).strip()
        if not d_text or not intensity_text:
            return None
        try:
            d_value = float(d_text)
            intensity = float(intensity_text)
        except ValueError:
            return None
        if not (0.1 <= d_value <= 50.0) or not (0.0 <= intensity <= 999.0):
            return None
        # Three-digit compact intensities are scaled by ten: 999 -> 100,
        # 551 -> 55.1, 299 -> 29.9. Two-digit values are already percentages.
        if intensity >= 999:
            intensity = 100.0
        elif intensity > 100:
            intensity = round(intensity / 10.0, 1)
        return {"d": d_value, "intensity": intensity, "hkl": hkl}

    for line in lines:
        marker = CARD_MARKER_RE.search(line)
        compact = COMPACT_CARD_MARKER_RE.search(line)
        if marker and marker.group("line").endswith("I"):
            prefix = line[: marker.start("marker")]
            for offset in (0, 23, 46):
                peak = parse_chunk(prefix[offset : offset + 23])
                if peak:
                    peaks.append(peak)
        elif compact and compact.group("marker").endswith("I"):
            prefix = line[: compact.start("marker")]
            if prefix and prefix[-1].isdigit():
                prefix = prefix[:-1]
            for offset in range(0, len(prefix), 23):
                peak = parse_chunk(prefix[offset : offset + 23])
                if peak:
                    peaks.append(peak)

    def first_text_for(marker_suffix: str) -> str:
        for line in lines:
            match = re.search(r"P[0-9A-Z]{6}" + marker_suffix + r"\s*$", line)
            if not match:
                continue
            text = line[: match.start()].strip()
            if text:
                return re.sub(r"\s+", " ", text)
        return ""

    phase = first_text_for("H6") or first_text_for("X6")
    formula = first_text_for("H7") or first_text_for("X7")
    if not phase or not formula:
        compact_phase = ""
        compact_formula = ""
        for line in lines:
            compact = COMPACT_CARD_MARKER_RE.search(line)
            if not compact:
                continue
            suffix = compact.group("marker")[-2:]
            text = line[: compact.start("marker")].strip()
            if suffix.endswith("6"):
                text = re.sub(r"\s+[A-Z]\s*\d+\s*$", "", text).strip()
                text = re.sub(r"\s+P\s*$", "", text).strip()
            if suffix.endswith("6") and text and not compact_phase:
                compact_phase = re.sub(r"\s+", " ", text)
            if suffix.endswith("7") and text and not compact_formula:
                compact_formula = re.sub(r"\s+", "", text)
        phase = phase or compact_phase
        formula = formula or compact_formula
    return {
        "pdf_number": pdf_number,
        "phase": phase or f"PDF {pdf_number}",
        "formula": formula,
        "n_peaks": len(peaks),
        "peaks": peaks,
    }


def _safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(" ._")
    return value[:120] or "PDF_card"


def _write_card(card: dict[str, Any], out_dir: Path) -> Path:
    cards_dir = out_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    target = cards_dir / _safe_filename(
        f"{card['phase']}_{card['pdf_number']}.txt"
    )
    lines = [
        f"# PDF#{card['pdf_number']}",
        f"# phase: {card['phase']}",
        f"# formula: {card.get('formula', '')}",
        "# source: exported from the local licensed Jade PDF database via its GUI",
        "# note: only the d-I peak list is saved; the full database card is not copied.",
        "",
        "d(A)\tI\thkl",
    ]
    for peak in card["peaks"]:
        lines.append(f"{peak['d']:.6f}\t{peak['intensity']:g}\t{peak['hkl']}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _open_pdf_retrieval_window(pid: int, main: Any, timeout: float) -> Any:
    retrieval = _find_window(pid, "PDF Retrievals")
    if retrieval:
        return retrieval

    errors: list[str] = []
    for _ in range(2):
        try:
            _send_menu_command(main, 163)  # PDF -> Retrieval...
        except Exception as exc:
            errors.append(str(exc))
            try:
                _invoke_uia_menu(pid, 163, timeout)
            except Exception as fallback_exc:
                errors.append(str(fallback_exc))
        retrieval = _wait_for(
            lambda: _find_window(pid, "PDF Retrievals"),
            min(timeout, 8.0),
            interval=0.25,
        )
        if retrieval:
            return retrieval
        _dismiss_error_windows(pid)
        _close_matching(pid, "PDF Retrievals")
        time.sleep(0.3)

    detail = f"（{'；'.join(errors)}）" if errors else ""
    raise RuntimeError(f"Jade 没有打开 PDF 检索窗口{detail}。")


def _export_cards(
    pid: int,
    main: Any,
    pdf_numbers: list[str],
    out_dir: Path,
    timeout: float,
) -> list[Path]:
    if not pdf_numbers:
        return []
    _dismiss_error_windows(pid)
    _reset_workflow_windows(pid)
    time.sleep(0.3)
    retrieval = _open_pdf_retrieval_window(pid, main, timeout)

    written: list[Path] = []
    try:
        for requested in pdf_numbers:
            number = _normalize_pdf_number(requested)
            card_window = _open_card_window(pid, retrieval, number, timeout)
            text_boxes = [
                child
                for child in card_window.children()
                if child.class_name() == "ThunderRT5TextBox"
            ]
            if not text_boxes:
                raise RuntimeError(f"卡片 {number} 窗口里没有可读取的数据区。")
            raw = max((_title(child) for child in text_boxes), key=len)
            card = _parse_card_text(raw, number)
            if not card["peaks"]:
                raise RuntimeError(f"卡片 {number} 没有解析出 d-I 峰表。")
            written.append(_write_card(card, out_dir))
            _post_close(card_window)
            time.sleep(0.2)
    finally:
        _post_close(retrieval)
        time.sleep(0.2)
    return written


def cmd_doctor(args: argparse.Namespace) -> int:
    exe = Path(args.jade).expanduser()
    pdf_db = Path(args.pdf_db).expanduser()
    try:
        _gui_modules()
        gui = "OK"
    except SystemExit as exc:
        gui = str(exc)
    pid = _find_jade_pid()
    status = {
        "python": sys.executable,
        "jade_exe": str(exe),
        "jade_exe_exists": exe.exists(),
        "pdf_database": str(pdf_db),
        "pdf_database_exists": pdf_db.exists(),
        "gui_automation": gui,
        "jade_running_pid": pid,
        "macro_file": str(_macro_file()),
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if exe.exists() and pdf_db.exists() and gui == "OK" else 1


def cmd_search(args: argparse.Namespace) -> int:
    jade_exe = Path(args.jade).expanduser().resolve()
    timeout = float(args.timeout)
    elements = _parse_elements(args.elements, args.formula)
    if not elements:
        raise SystemExit(
            "Jade 检索前必须提供元素和化学式。请先向用户询问元素与化学式；"
            "若用户没有，先获取样品信息或研究方向，再查论文和公开资料归纳"
            "该方向的常规元素与化学式。"
        )
    if not args.formula:
        raise SystemExit(
            "缺少化学式。请先向用户询问；若用户没有，先获取样品信息或"
            "研究方向后再归纳常规物相。"
        )

    pid, main = _start_or_find_jade(jade_exe, timeout)
    if args.pattern and not args.no_load:
        main = _load_pattern(main, Path(args.pattern), timeout)
    data_window = _find_data_window(pid)
    if not data_window:
        raise RuntimeError("Jade 当前没有已载入的 XRD 文件。")
    pattern_name = _pattern_from_data_window(data_window)
    if not args.reuse_peaks:
        _run_find_peaks(pid, data_window, timeout)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    backup = _backup_chemistry_filter()
    try:
        _set_chemistry_filter(
            pid,
            main,
            elements,
            timeout,
            filter_mode=args.filter_mode,
        )
        _run_search_match(pid, data_window, timeout)
        rows = _read_search_display(pid, timeout)
        metadata = {
            "sample": pattern_name,
            "elements": elements,
            "formula": args.formula,
            "filter_mode": args.filter_mode,
            "find_peaks": not args.reuse_peaks,
            "note": "元素和化学式由用户提供或经研究背景确认后传入。",
        }
        _write_candidates(rows, out_dir, "Search/Match Display", metadata)
        (out_dir / "search_request.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    finally:
        _restore_chemistry_filter(backup)

    cards = _export_cards(pid, main, args.export_card, out_dir, timeout)
    print(f"样品：{pattern_name}")
    print(f"元素约束：{', '.join(elements)}")
    print(f"化学式：{args.formula}")
    print(f"元素筛选模式：{args.filter_mode}")
    print(f"候选卡片：{len(rows)} 条")
    for row in rows[:10]:
        fom = "?" if row["fom"] is None else f"{row['fom']:.1f}"
        print(f"  FOM {fom:>4}  PDF#{row['pdf_number']}  {row['phase']}  {row['formula']}")
    print(f"候选表：{out_dir / 'candidates.csv'}")
    print(f"检索记录：{out_dir / 'search_request.json'}")
    for card in cards:
        print(f"卡片峰表：{card}")
    print("提醒：以上只是候选卡片；物相归属还需结合峰位、样品背景和文献判断。")
    return 0


def cmd_export_card(args: argparse.Namespace) -> int:
    jade_exe = Path(args.jade).expanduser().resolve()
    timeout = float(args.timeout)
    pid, main = _start_or_find_jade(jade_exe, timeout)
    if args.pattern and not args.no_load:
        main = _load_pattern(main, Path(args.pattern), timeout)
    out_dir = Path(args.out).expanduser().resolve()
    cards = _export_cards(pid, main, args.pdf, out_dir, timeout)
    for card in cards:
        print(card)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jade_phaseid.py",
        description="用 Jade 6.5 自身界面完成 XRD 候选检索和 PDF 卡片 d-I 导出。",
    )
    parser.add_argument("--jade", default=str(DEFAULT_JADE_EXE), help="Jade 6.5 可执行文件")
    parser.add_argument("--timeout", type=float, default=60.0, help="单步等待秒数")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查 Jade、数据库和自动化依赖")
    doctor.add_argument("--pdf-db", default=str(DEFAULT_PDF2_DB))
    doctor.set_defaults(func=cmd_doctor)

    search = sub.add_parser("search", help="寻峰 + Search/Match + 导出候选 JSM")
    search.add_argument("--pattern", help="XRD 原始文件；默认使用 Jade 当前已打开文件")
    search.add_argument("--no-load", action="store_true", help="不要自动载入 --pattern")
    search.add_argument(
        "--reuse-peaks",
        action="store_true",
        help="沿用 Jade 当前峰位，不自动执行 Find Peaks",
    )
    search.add_argument("--out", required=True, help="输出目录")
    search.add_argument(
        "--elements",
        required=True,
        help='用户确认的目标元素，例如 "Si,Fe,Cu,S"',
    )
    search.add_argument(
        "--formula",
        required=True,
        help='目标物相或化学式，例如 "Si + FeS2 + CuFeS2"',
    )
    search.add_argument(
        "--filter-mode",
        choices=("possible", "required"),
        default="possible",
        help=(
            "possible：元素可作为任一所选相的一部分（混相默认）；"
            "required：所有候选相都必须含全部元素（单相或全元素交集样品）"
        ),
    )
    search.add_argument(
        "--export-card",
        action="append",
        default=[],
        metavar="PDF#",
        help="额外导出指定卡片 d-I，可重复；例如 04-0733",
    )
    search.set_defaults(func=cmd_search)

    export = sub.add_parser("export-card", help="按卡片号导出干净 d-I 峰表")
    export.add_argument("--pdf", action="append", required=True, metavar="PDF#")
    export.add_argument("--pattern", help="可选：先载入该 XRD 文件")
    export.add_argument("--no-load", action="store_true")
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export_card)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
