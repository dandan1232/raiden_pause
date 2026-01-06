"""
Simple watchdog to pause Leishen Accelerator when games/Steam exit.

Requirements (install in your venv):
  pip install psutil pyautogui pillow opencv-python win10toast

Behavior:
- Polls for configured game processes (or Steam) every few seconds.
- When none are running, it tries to find and click the red "暂停时长" button.
- If the button is not found, it shows a Windows toast reminder.

Assets:
- Place button templates under ./assets/
  - start_button.png (red “暂停时长” when acceleration is ON)
  - unstart_button.png (gray “开启时长” when acceleration is OFF)
  - Full screenshots are optional for debugging.

Run:
  python raiden_pause.py
Optionally register as a startup task or launch alongside Steam.
"""

import os
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, TYPE_CHECKING, Any

import psutil

try:
    import pyautogui
except ImportError:
    pyautogui = None
try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None

if TYPE_CHECKING:
    from pyautogui import Box as PyAutoGuiBox
else:
    PyAutoGuiBox = Any

try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

try:
    import win32con
    import win32gui
except ImportError:
    win32con = None
    win32gui = None


# ---- Configuration ----

# Window title keywords to locate Leishen; adjust if你的标题不同.
WINDOW_TITLE_KEYWORDS = ["雷神加速器"]

# Add/adjust process names (lowercase). If any are running, we consider "in game".
WATCH_PROCESSES = {
    "steam.exe",
    "r5apex.exe",        # Apex Legends
    "tslgame.exe",       # PUBG
    "forzahorizon5.exe", # Forza Horizon 5
    "gtav.exe",          # GTA V
    "easportsfc24.exe",  # EA SPORTS FC example; adjust to your actual exe
    "notepad.exe",
}

# How often to poll for processes (seconds).
POLL_INTERVAL = 5

# Template matching confidence; requires OpenCV if set < 1.0.
MATCH_CONFIDENCE = 0.9

# Paths to template images.
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
START_BUTTON = ASSETS_DIR / "start_button.png"     # red “暂停时长”
UNSTART_BUTTON = ASSETS_DIR / "unstart_button.png" # gray “开启时长” (used for detection only)


# ---- Helpers ----

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def notify(title: str, msg: str) -> None:
    if ToastNotifier:
        try:
            ToastNotifier().show_toast(title, msg, duration=5, threaded=True)
            return
        except Exception as exc:  # pylint: disable=broad-except
            log(f"Toast failed: {exc}")
    # Fallback to stdout.
    log(f"NOTIFY: {title} - {msg}")


def any_process_running(names: Iterable[str]) -> bool:
    target = {n.lower() for n in names}
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name and name.lower() in target:
            return True
    return False


def find_raiden_window() -> Optional[int]:
    if not win32gui:
        return None
    matches: List[int] = []

    def _enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        low = title.lower()
        for kw in WINDOW_TITLE_KEYWORDS:
            if kw.lower() in low:
                matches.append(hwnd)
                break

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception as exc:  # pylint: disable=broad-except
        log(f"EnumWindows failed: {exc}")
        return None
    return matches[0] if matches else None


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    if not win32gui:
        return None
    try:
        rect = win32gui.GetWindowRect(hwnd)
        if rect:
            return rect  # left, top, right, bottom
    except Exception as exc:  # pylint: disable=broad-except
        log(f"GetWindowRect failed: {exc}")
    return None


def bring_window_to_front(hwnd: int) -> Optional[int]:
    if not win32gui or not win32con:
        return None
    prev = win32gui.GetForegroundWindow()
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.2)  # give Windows a moment
    except Exception as exc:  # pylint: disable=broad-except
        log(f"SetForegroundWindow failed: {exc}")
    return prev


def restore_foreground(hwnd: Optional[int]) -> None:
    if not hwnd or not win32gui:
        return
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:  # pylint: disable=broad-except
        pass


def locate_button(templates: List[Path], region: Optional[Tuple[int, int, int, int]] = None) -> Optional[PyAutoGuiBox]:
    if not pyautogui:
        log("pyautogui not installed; cannot locate button.")
        return None
    use_confidence = MATCH_CONFIDENCE < 1.0 and cv2 is not None
    if MATCH_CONFIDENCE < 1.0 and cv2 is None:
        log("OpenCV not installed; falling back to default template matching.")
    for tpl in templates:
        if not tpl.exists():
            log(f"Template not found: {tpl}")
            continue
        try:
            if use_confidence:
                box = pyautogui.locateOnScreen(
                    str(tpl),
                    confidence=MATCH_CONFIDENCE,
                    region=region,
                )
            else:
                box = pyautogui.locateOnScreen(
                    str(tpl),
                    region=region,
                )
            if box:
                log(f"Found button via template: {tpl.name} at {box}")
                return box
        except Exception as exc:  # pylint: disable=broad-except
            log(f"locateOnScreen failed for {tpl}: {exc}")
    return None


def click_center(box: PyAutoGuiBox) -> bool:
    if not pyautogui:
        return False
    try:
        x, y = pyautogui.center(box)
        pyautogui.click(x, y)
        log(f"Clicked at ({x}, {y})")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        log(f"Click failed: {exc}")
        return False


def try_pause_accelerator() -> None:
    log("Trying to pause accelerator...")
    if not pyautogui:
        notify("雷神加速器", "未安装 pyautogui，无法自动点击，请手动暂停。")
        return

    hwnd = find_raiden_window()
    region = None
    prev_foreground = None
    if hwnd:
        region_rect = get_window_rect(hwnd)
        if region_rect:
            left, top, right, bottom = region_rect
            region = (left, top, right - left, bottom - top)
        prev_foreground = bring_window_to_front(hwnd)

    try:
        box = locate_button([START_BUTTON], region=region)
        if box:
            if click_center(box):
                notify("雷神加速器", "检测到游戏关闭，已尝试点击“暂停时长”。")
            else:
                notify("雷神加速器", "按钮找到但点击失败，请手动暂停。")
            return

        # If only unstart/gray button is visible, it likely is already paused.
        box_unstart = locate_button([UNSTART_BUTTON], region=region)
        if box_unstart:
            log("Looks already paused (gray button visible).")
            notify("雷神加速器", "看起来已经暂停，无需操作。")
            return

        if hwnd:
            notify("雷神加速器", "未找到按钮，尝试把雷神窗口切到前台再试一次。")
        else:
            notify("雷神加速器", "未找到暂停按钮，也未找到雷神窗口，请手动暂停。")
    finally:
        restore_foreground(prev_foreground)


def main() -> None:
    if not ASSETS_DIR.exists():
        log(f"Assets folder missing: {ASSETS_DIR}")
        sys.exit(1)

    log("Raiden pause watcher started.")
    log(f"Watching processes: {sorted(WATCH_PROCESSES)}")
    state_in_game = False

    while True:
        try:
            running = any_process_running(WATCH_PROCESSES)
            if running and not state_in_game:
                log("Detected game/Steam running.")
                state_in_game = True
            elif not running and state_in_game:
                log("Detected all watched processes stopped.")
                try_pause_accelerator()
                state_in_game = False
        except KeyboardInterrupt:
            log("Exiting by user.")
            break
        except Exception as exc:  # pylint: disable=broad-except
            log(f"Loop error: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
