"""
Simple watchdog to pause Leishen Accelerator when games/Steam exit.

Requirements (install in your venv):
  pip install psutil pyautogui pillow opencv-python win10toast pywinauto pywin32 wmi winsdk

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
import html
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, TYPE_CHECKING, Any

import psutil
try:
    import wmi  # type: ignore
except ImportError:
    wmi = None

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
    from pywinauto import Application as UIAApplication
    from pywinauto import Desktop as UIADesktop
except ImportError:
    UIAApplication = None
    UIADesktop = None

try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

TOAST_BACKEND = None
try:
    from winsdk.windows.ui.notifications import ToastNotificationManager, ToastNotification
    from winsdk.windows.data.xml.dom import XmlDocument
    TOAST_BACKEND = "winsdk"
except ImportError:
    try:
        from winrt.windows.ui.notifications import ToastNotificationManager, ToastNotification
        from winrt.windows.data.xml.dom import XmlDocument
        TOAST_BACKEND = "winrt"
    except ImportError:
        ToastNotificationManager = None
        ToastNotification = None
        XmlDocument = None

TOAST_SDK_AVAILABLE = all((ToastNotificationManager, ToastNotification, XmlDocument))
TOAST_FALLBACK_LOGGED = False
TOAST_ERROR_LOGGED = False

try:
    import win32con
    import win32gui
except ImportError:
    win32con = None
    win32gui = None


# ---- Configuration ----

# Window title keywords to locate Leishen; adjust if你的标题不同.
WINDOW_TITLE_KEYWORDS = ["雷神加速器", "Leishen", "Raiden"]

# Main process name for Leigod/Raiden (used for UIA fallback when minimized).
RAIDEN_PROCESS_NAME = "leigod.exe"

# Tray icon text keywords (used to restore from system tray).
TRAY_ICON_KEYWORDS = ["雷神", "Leishen", "Raiden", "leigod"]

# Add/adjust process names (lowercase). If any are running, we consider "in game".
WATCH_PROCESSES = {
    "steam.exe",
    "r5apex.exe",        # Apex Legends
    "tslgame.exe",       # PUBG
    "forzahorizon5.exe", # Forza Horizon 5
    "gtav.exe",          # GTA V
    "easportsfc24.exe",  # EA SPORTS FC example; adjust to your actual exe
}

# How often to poll for processes (seconds).
POLL_INTERVAL = 5

# WMI event wait timeout (milliseconds) when running event-driven watcher.
WMI_TIMEOUT_MS = 1000
# Consecutive WMI errors before falling back to polling.
WMI_ERROR_LIMIT = 5

# UI timing (seconds); reduce to lower latency if stable.
FOREGROUND_DELAY = 0.1
TRAY_CLICK_DELAY = 0.2
UIA_RETRY_DELAY = 0.2
# Fixed-position button matching (relative to window top-left).
BUTTON_CENTER_REL = (2539, 367)  # (x, y)
BUTTON_REGION_HALF = (220, 80)   # half width/height around center

# Screenshot matching tuning.
ENABLE_UNSTART_CHECK = False

# Template matching confidence; requires OpenCV if set < 1.0.
MATCH_CONFIDENCE = 0.9

# Debug: dump tray icon texts when not found.
TRAY_DEBUG_DUMP = False
# Debug: log notify calls.
NOTIFY_DEBUG = True
# Debug: send a test toast on startup.
NOTIFY_SELF_TEST = True
# Paths to template images.
if getattr(sys, "frozen", False):
    # PyInstaller uses a temp unpack dir exposed via sys._MEIPASS.
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
else:
    BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
TOAST_APP_ID = "RaidenPause.NotEatTime"
TOAST_SHORTCUT_NAME = "\u4e0d\u51c6\u5403\u6211\u65f6\u957f--v1.0"
LEGACY_SHORTCUT_NAMES = [
    "\u4e0d\u51c6\u5403\u6211\u65f6\u957f",
    "\u4e0d\u51c6\u5403\u6211\u65f6\u957f--V1.0",
]
TOAST_ICON_ICO = ASSETS_DIR / "logo.ico"
TOAST_ICON_PNG = ASSETS_DIR / "logo.png"
START_BUTTON = ASSETS_DIR / "start_button.png"     # red “暂停时长”
UNSTART_BUTTON = ASSETS_DIR / "unstart_button.png" # gray “开启时长” (used for detection only)


# ---- Helpers ----

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def xml_escape(text: str) -> str:
    return html.escape(text, quote=True)


def set_current_process_app_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pylint: disable=broad-except
        return
    try:
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [wintypes.LPCWSTR]
        set_app_id.restype = ctypes.HRESULT
        hr = set_app_id(TOAST_APP_ID)
        if NOTIFY_DEBUG and hr not in (0, None):
            log(f"SetCurrentProcessExplicitAppUserModelID failed: 0x{hr & 0xFFFFFFFF:08X}")
    except Exception:  # pylint: disable=broad-except
        return


def register_toast_app_id() -> None:
    if os.name != "nt":
        return
    try:
        import winreg
    except Exception:  # pylint: disable=broad-except
        return

    icon_uri = None
    if TOAST_ICON_ICO.exists():
        icon_uri = TOAST_ICON_ICO.resolve().as_uri()
    key_path = f"Software\\Classes\\AppUserModelId\\{TOAST_APP_ID}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, TOAST_SHORTCUT_NAME)
            if icon_uri:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon_uri)
    except Exception:  # pylint: disable=broad-except
        return


def ensure_toast_shortcut() -> None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    shortcut_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut_path = shortcut_dir / f"{TOAST_SHORTCUT_NAME}.lnk"
    try:
        shortcut_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # pylint: disable=broad-except
        return
    for name in LEGACY_SHORTCUT_NAMES:
        if name == TOAST_SHORTCUT_NAME:
            continue
        legacy_path = shortcut_dir / f"{name}.lnk"
        try:
            if legacy_path.exists():
                legacy_path.unlink()
                if NOTIFY_DEBUG:
                    log(f"Removed legacy toast shortcut: {legacy_path}")
        except Exception:  # pylint: disable=broad-except
            pass

    try:
        from win32com.client import Dispatch  # type: ignore
        from win32com.propsys import propsys, pscon  # type: ignore
    except Exception:  # pylint: disable=broad-except
        return

    try:
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = f"\"{Path(__file__).resolve()}\""
        shortcut.WorkingDirectory = str(BASE_DIR)
        if TOAST_ICON_ICO.exists():
            shortcut.IconLocation = str(TOAST_ICON_ICO.resolve())
        shortcut.save()
        try:
            store = propsys.SHGetPropertyStoreFromParsingName(
                str(shortcut_path),
                None,
                propsys.GPS_READWRITE,
            )
            store.SetValue(pscon.PKEY_AppUserModel_ID, TOAST_APP_ID)
            store.Commit()
        except Exception:  # pylint: disable=broad-except
            pass
    except Exception:  # pylint: disable=broad-except
        pass


def notify_winrt(title: str, msg: str) -> bool:
    if not TOAST_SDK_AVAILABLE:
        return False
    set_current_process_app_id()
    register_toast_app_id()
    ensure_toast_shortcut()
    image_tag = ""
    icon_path = TOAST_ICON_PNG if TOAST_ICON_PNG.exists() else TOAST_ICON_ICO
    if icon_path.exists():
        image_tag = (
            '<image placement="appLogoOverride" hint-crop="circle" '
            f'src="{icon_path.resolve().as_uri()}"/>'
        )
    toast_xml = (
        "<toast>"
        "<visual>"
        "<binding template=\"ToastGeneric\">"
        f"<text>{xml_escape(title)}</text>"
        f"<text>{xml_escape(msg)}</text>"
        f"{image_tag}"
        "</binding>"
        "</visual>"
        "</toast>"
    )
    try:
        doc = XmlDocument()
        doc.load_xml(toast_xml)
        notifier = ToastNotificationManager.create_toast_notifier(TOAST_APP_ID)
        notifier.show(ToastNotification(doc))
        if NOTIFY_DEBUG:
            log(f"Win toast sent via {TOAST_BACKEND}.")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        global TOAST_ERROR_LOGGED
        if not TOAST_ERROR_LOGGED:
            log(f"Windows toast failed: {exc}")
            TOAST_ERROR_LOGGED = True
        return False


def notify(title: str, msg: str) -> None:
    global TOAST_FALLBACK_LOGGED
    if NOTIFY_DEBUG:
        log(f"Notify call: {title} - {msg}")
    if notify_winrt(title, msg):
        return
    if not TOAST_SDK_AVAILABLE and not TOAST_FALLBACK_LOGGED:
        log("Windows toast SDK unavailable; using win10toast fallback.")
        TOAST_FALLBACK_LOGGED = True
    if ToastNotifier:
        try:
            icon_path = None
            if TOAST_ICON_ICO.exists():
                icon_path = str(TOAST_ICON_ICO)
            ToastNotifier().show_toast(title, msg, icon_path=icon_path, duration=5, threaded=True)
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


def get_watched_process_counts(names: Iterable[str]) -> dict:
    counts: dict = {}
    target = {n.lower() for n in names}
    if not target:
        return counts
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if not name:
            continue
        low = name.lower()
        if low in target:
            counts[low] = counts.get(low, 0) + 1
    return counts


def total_watched_count(counts: dict) -> int:
    return sum(counts.values())


def extract_event_process_name(evt: Any) -> str:
    for attr in ("ProcessName", "Caption", "Name"):
        try:
            val = getattr(evt, attr, None)
        except Exception:  # pylint: disable=broad-except
            val = None
        if val:
            return str(val)
    try:
        target = getattr(evt, "TargetInstance", None)
        if target:
            for attr in ("Name", "Caption"):
                try:
                    val = getattr(target, attr, None)
                except Exception:  # pylint: disable=broad-except
                    val = None
                if val:
                    return str(val)
    except Exception:  # pylint: disable=broad-except
        pass
    return ""


def get_process_pids(name: str) -> List[int]:
    pids: List[int] = []
    low = name.lower()
    for proc in psutil.process_iter(["name", "pid"]):
        pname = proc.info.get("name")
        if pname and pname.lower() == low:
            pids.append(proc.info["pid"])
    return pids


def tray_name_matches(name: str) -> bool:
    low = name.lower()
    return any(kw.lower() in low for kw in TRAY_ICON_KEYWORDS)


def restore_window_by_process(name: str) -> bool:
    if not win32gui or not win32con:
        return False
    pids = set(get_process_pids(name))
    if not pids:
        return False
    candidates: List[int] = []

    def _enum_handler(hwnd, _):
        try:
            _, pid = win32gui.GetWindowThreadProcessId(hwnd)
        except Exception:  # pylint: disable=broad-except
            return
        if pid in pids:
            candidates.append(hwnd)

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception:  # pylint: disable=broad-except
        return False

    for hwnd in candidates:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
            except (TypeError, Exception):  # pylint: disable=broad-except
                pass
            try:
                win32gui.BringWindowToTop(hwnd)
            except (TypeError, Exception):  # pylint: disable=broad-except
                pass
            return True
        except Exception:  # pylint: disable=broad-except
            continue
    return False


def find_raiden_window() -> Optional[int]:
    if not win32gui:
        return None
    visible: List[int] = []
    hidden: List[int] = []

    def _enum_handler(hwnd, _):
        title = win32gui.GetWindowText(hwnd) or ""
        low = title.lower()
        for kw in WINDOW_TITLE_KEYWORDS:
            if kw.lower() in low:
                if win32gui.IsWindowVisible(hwnd):
                    visible.append(hwnd)
                else:
                    hidden.append(hwnd)
                break

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception as exc:  # pylint: disable=broad-except
        log(f"EnumWindows failed: {exc}")
        return None
    if visible:
        return visible[0]
    return hidden[0] if hidden else None


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
        # Foreground focus can fail due to Windows restrictions; treat as best-effort.
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
        except (TypeError, Exception):  # pylint: disable=broad-except
            pass
        try:
            win32gui.BringWindowToTop(hwnd)
        except (TypeError, Exception):  # pylint: disable=broad-except
            pass
        try:
            win32gui.SetForegroundWindow(hwnd)
        except (TypeError, Exception):  # pylint: disable=broad-except
            pass
        time.sleep(FOREGROUND_DELAY)
    except Exception as exc:  # pylint: disable=broad-except
        pass
    return prev


def restore_foreground(hwnd: Optional[int]) -> None:
    if not hwnd or not win32gui:
        return
    try:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except (TypeError, Exception):  # pylint: disable=broad-except
            pass
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


def get_fixed_button_region(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    rect = get_window_rect(hwnd)
    if not rect:
        return None
    left, top, right, bottom = rect
    center_x = left + BUTTON_CENTER_REL[0]
    center_y = top + BUTTON_CENTER_REL[1]
    half_w, half_h = BUTTON_REGION_HALF
    region_left = max(left, center_x - half_w)
    region_top = max(top, center_y - half_h)
    region_right = min(right, center_x + half_w)
    region_bottom = min(bottom, center_y + half_h)
    width = max(0, region_right - region_left)
    height = max(0, region_bottom - region_top)
    if width <= 0 or height <= 0:
        return None
    return (region_left, region_top, width, height)


def try_restore_from_tray_win32() -> bool:
    if not UIADesktop:
        log("未安装 pywinauto，无法从托盘恢复。")
        return False
    if not win32gui:
        return False
    try:
        desktop = UIADesktop(backend="win32")
    except Exception:  # pylint: disable=broad-except
        return False

    toolbars = []
    try:
        taskbar = desktop.window(class_name="Shell_TrayWnd")
        tray = taskbar.child_window(class_name="TrayNotifyWnd")
        pager = tray.child_window(class_name="SysPager")
        toolbars.append(pager.child_window(class_name="ToolbarWindow32"))
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        overflow = desktop.window(class_name="NotifyIconOverflowWindow")
        toolbars.append(overflow.child_window(class_name="ToolbarWindow32"))
    except Exception:  # pylint: disable=broad-except
        pass

    dumped: List[str] = []
    for toolbar in toolbars:
        try:
            count = toolbar.button_count()
        except Exception:  # pylint: disable=broad-except
            continue
        for i in range(count):
            try:
                btn = toolbar.get_button(i)
            except Exception:  # pylint: disable=broad-except
                continue
            texts: List[str] = []
            try:
                text = btn.text()
                if text:
                    texts.append(text)
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                texts.extend([t for t in btn.texts() if t])
            except Exception:  # pylint: disable=broad-except
                pass
            name = " ".join(texts)
            if name:
                dumped.append(name)
            if not name:
                continue
            if tray_name_matches(name):
                try:
                    btn.click_input()
                    log("Clicked tray icon via win32 toolbar.")
                    time.sleep(TRAY_CLICK_DELAY)
                    return True
                except Exception:  # pylint: disable=broad-except
                    continue
    return False


def try_restore_from_tray_uia_roots() -> bool:
    if not UIADesktop:
        log("未安装 pywinauto，无法从托盘恢复。")
        return False
    root_classes = [
        "SystemTray_Main",
        "CTrayUIMgr_ClassName",
        "Electron_NotifyIconHostWindow",
        "Chrome_StatusTrayWindow",
        "Chrome_StatusTrayWindow21024125",
        "WPETrayWindow",
        "Qt51514WxTrayIconMessageWindowClass",
        "Qt51513TrayIconMessageWindowClass",
    ]
    desktop = UIADesktop(backend="uia")
    for cls in root_classes:
        try:
            win = desktop.window(class_name=cls)
        except Exception:  # pylint: disable=broad-except
            continue
        if not win.exists(timeout=0.5):
            continue
        try:
            buttons = win.descendants(control_type="Button")
        except Exception:  # pylint: disable=broad-except
            buttons = []
        dumped: List[str] = []
        for btn in buttons:
            try:
                name = btn.window_text() or getattr(btn.element_info, "name", "") or ""
            except Exception:  # pylint: disable=broad-except
                name = ""
            if name:
                dumped.append(name)
            if name and tray_name_matches(name):
                try:
                    btn.click_input()
                    log(f"Clicked tray icon via UIA root: {cls}")
                    time.sleep(TRAY_CLICK_DELAY)
                    return True
                except Exception:  # pylint: disable=broad-except
                    continue
    return False


def try_restore_from_tray_overflow_uia() -> bool:
    if not UIAApplication or not UIADesktop:
        log("未安装 pywinauto，无法从托盘恢复。")
        return False

    try:
        app = UIAApplication(backend="uia").connect(path="explorer.exe")
        taskbar = app.window(class_name="Shell_TrayWnd")
    except Exception:  # pylint: disable=broad-except
        return False

    clicked = False
    try:
        try:
            taskbar["显示隐藏的图标"].wrapper_object().click()
            clicked = True
        except Exception:  # pylint: disable=broad-except
            chevron_keywords = [
                "notification chevron",
                "notification",
                "chevron",
                "overflow",
                "隐藏",
                "通知区域",
            ]
            for btn in taskbar.descendants(control_type="Button"):
                name = (btn.window_text() or getattr(btn.element_info, "name", "") or "").lower()
                if not name:
                    continue
                if any(k in name for k in chevron_keywords):
                    try:
                        btn.click_input()
                        clicked = True
                        break
                    except Exception:  # pylint: disable=broad-except
                        continue
    except Exception:  # pylint: disable=broad-except
        return False

    if not clicked:
        return False

    try:
        overflow = UIADesktop(backend="uia").window(class_name="NotifyIconOverflowWindow")
        has_overflow = overflow.exists(timeout=1)
    except Exception:  # pylint: disable=broad-except
        has_overflow = False

    containers = [overflow] if has_overflow else [taskbar]
    for container in containers:
        try:
            buttons = container.descendants(control_type="Button")
        except Exception:  # pylint: disable=broad-except
            buttons = []
        for btn in buttons:
            try:
                name = btn.window_text() or getattr(btn.element_info, "name", "") or ""
            except Exception:  # pylint: disable=broad-except
                name = ""
            text_blob = f"{name} {btn!s}".lower()
            if name and tray_name_matches(name) or tray_name_matches(text_blob):
                try:
                    btn.click_input()
                    log("Clicked tray icon via overflow window.")
                    time.sleep(TRAY_CLICK_DELAY)
                    return True
                except Exception:  # pylint: disable=broad-except
                    continue
    return False


def try_pause_accelerator() -> None:
    log("Trying to pause accelerator...")
    try:
        restored = False
        log("步骤：UIA 托盘根窗口")
        if try_restore_from_tray_uia_roots():
            restored = True
        else:
            log("步骤：展开隐藏图标托盘")
            if try_restore_from_tray_overflow_uia():
                restored = True
            else:
                log("步骤：Win32 托盘恢复")
                if try_restore_from_tray_win32():
                    restored = True

        if not restored:
            log("步骤：按进程恢复窗口")
            if restore_window_by_process(RAIDEN_PROCESS_NAME):
                restored = True
        if restored:
            time.sleep(UIA_RETRY_DELAY)

        if not pyautogui:
            notify("雷神加速器", "未安装 pyautogui，无法自动点击，请手动暂停。")
            return
    except Exception as exc:  # pylint: disable=broad-except
        log(f"暂停流程异常: {exc}")
        notify("雷神加速器", "暂停流程异常，稍后将重试。")
        return

    hwnd = find_raiden_window()
    if not hwnd:
        if restore_window_by_process(RAIDEN_PROCESS_NAME):
            time.sleep(UIA_RETRY_DELAY)
            hwnd = find_raiden_window()
    region = None
    prev_foreground = None
    if hwnd:
        region = get_fixed_button_region(hwnd)
        prev_foreground = bring_window_to_front(hwnd)

    try:
        box = locate_button([START_BUTTON], region=region) if region else None
        if not box:
            box = locate_button([START_BUTTON], region=None)
        if box:
            if click_center(box):
                notify("雷神加速器", "检测到游戏关闭，已尝试点击“暂停时长”。")
            else:
                notify("雷神加速器", "按钮找到但点击失败，请手动暂停。")
            return

        if ENABLE_UNSTART_CHECK and region:
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


def poll_watch_loop(state_in_game: bool = False) -> None:
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


def wmi_watch_loop() -> bool:
    if not wmi:
        log("Python wmi package not installed; falling back to polling.")
        return False
    try:
        conn = wmi.WMI()
        start_watcher = conn.Win32_Process.watch_for("creation")
        stop_watcher = conn.Win32_Process.watch_for("deletion")
    except Exception as exc:  # pylint: disable=broad-except
        log(f"WMI watcher init failed: {exc}")
        return False

    target_names = {n.lower() for n in WATCH_PROCESSES}
    counts = get_watched_process_counts(target_names)
    state_in_game = total_watched_count(counts) > 0
    if state_in_game:
        log("Detected game/Steam running (initial via WMI).")
    else:
        log("Initial state: idle (no watched processes).")

    error_streak = 0
    while True:
        try:
            start_evt = None
            stop_evt = None
            try:
                start_evt = start_watcher(timeout_ms=WMI_TIMEOUT_MS)
            except wmi.x_wmi_timed_out:  # type: ignore[attr-defined]
                start_evt = None
            try:
                stop_evt = stop_watcher(timeout_ms=WMI_TIMEOUT_MS)
            except wmi.x_wmi_timed_out:  # type: ignore[attr-defined]
                stop_evt = None
            error_streak = 0

            if start_evt:
                name = extract_event_process_name(start_evt)
                low = name.lower() if name else ""
                if low in target_names:
                    counts[low] = counts.get(low, 0) + 1
                    if not state_in_game:
                        log("Detected game/Steam running. (WMI)")
                        state_in_game = True
                    continue

            if stop_evt:
                name = extract_event_process_name(stop_evt)
                low = name.lower() if name else ""
                if low in target_names:
                    if counts.get(low, 0) > 0:
                        counts[low] -= 1
                        if counts[low] <= 0:
                            counts.pop(low)
                    if total_watched_count(counts) == 0 and state_in_game:
                        log("Detected all watched processes stopped. (WMI)")
                        try_pause_accelerator()
                        state_in_game = False
                    continue
        except KeyboardInterrupt:
            log("Exiting by user.")
            break
        except Exception as exc:  # pylint: disable=broad-except
            error_streak += 1
            log(f"WMI watch loop error ({error_streak}/{WMI_ERROR_LIMIT}): {exc}")
            if error_streak >= WMI_ERROR_LIMIT:
                log("WMI unstable; falling back to polling.")
                return False
            time.sleep(1)
    return True


def main() -> None:
    if not ASSETS_DIR.exists():
        log(f"Assets folder missing: {ASSETS_DIR}")
        sys.exit(1)

    set_current_process_app_id()
    if TOAST_SDK_AVAILABLE:
        register_toast_app_id()
        ensure_toast_shortcut()
        if NOTIFY_SELF_TEST:
            notify("❤酱酱~~", "hi~~~我来啦！！祝你今天全win！！")

    log("Raiden pause watcher started.")
    log(f"Watching processes: {sorted(WATCH_PROCESSES)}")
    if not wmi_watch_loop():
        poll_watch_loop()


if __name__ == "__main__":
    main()
