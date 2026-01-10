from pywinauto import Desktop
import psutil


def main() -> None:
    title_re = ".*(雷神加速器|Leishen|Raiden).*"
    wins = Desktop(backend="uia").windows(title_re=title_re, visible_only=False)

    print(f"matched windows: {len(wins)}")
    for win in wins:
        try:
            handle = win.handle
        except Exception:
            handle = None
        try:
            pid = win.process_id()
        except Exception:
            pid = None
        try:
            title = win.window_text()
        except Exception:
            title = ""
        try:
            pname = psutil.Process(pid).name() if pid else ""
        except Exception:
            pname = ""
        print(f"handle={handle} pid={pid} pname={pname} title={title!r}")


if __name__ == "__main__":
    main()
