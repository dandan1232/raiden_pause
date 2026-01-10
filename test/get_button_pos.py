import time
import win32gui

try:
    import pyautogui
except ImportError:
    pyautogui = None


WINDOW_TITLE_KEYWORDS = ["雷神加速器", "Leishen", "Raiden"]


def find_window() -> int:
    result = 0

    def _enum(hwnd, _):
        nonlocal result
        title = win32gui.GetWindowText(hwnd) or ""
        low = title.lower()
        if any(k.lower() in low for k in WINDOW_TITLE_KEYWORDS):
            result = hwnd
            return False
        return True

    win32gui.EnumWindows(_enum, None)
    return result


def main() -> None:
    if pyautogui is None:
        print("pyautogui 未安装，请先安装后再运行。")
        return

    print("请先把雷神加速器窗口显示出来。")
    time.sleep(1)

    hwnd = find_window()
    if not hwnd:
        print("未找到雷神加速器窗口。")
        return

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    print(f"窗口位置: left={left}, top={top}, right={right}, bottom={bottom}")
    print("把鼠标移动到“暂停/开启时长”按钮中心，按 Enter 记录坐标...")

    input()
    x, y = pyautogui.position()
    rel_x = x - left
    rel_y = y - top
    print(f"屏幕坐标: ({x}, {y})")
    print(f"相对窗口坐标: ({rel_x}, {rel_y})")


if __name__ == "__main__":
    main()
