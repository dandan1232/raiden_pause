import win32gui


def dump_child_windows(hwnd: int, depth: int = 0, max_depth: int = 6) -> None:
    if depth > max_depth:
        return
    try:
        cls = win32gui.GetClassName(hwnd)
    except Exception:
        cls = ""
    try:
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        title = ""
    print(f"depth={depth} class={cls} handle={hwnd} title={title!r}")

    def _enum_child(child_hwnd, _):
        dump_child_windows(child_hwnd, depth + 1, max_depth)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _enum_child, None)
    except Exception:
        return


def main() -> None:
    handles = []

    def _enum_top(hwnd, _):
        handles.append(hwnd)
        return True

    win32gui.EnumWindows(_enum_top, None)

    for hwnd in handles:
        try:
            cls = win32gui.GetClassName(hwnd)
        except Exception:
            cls = ""
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = ""
        if any(key in cls for key in ["Tray", "Notify", "Toolbar", "Shell_TrayWnd"]):
            print(f"top class={cls} handle={hwnd} title={title!r}")
            dump_child_windows(hwnd)


if __name__ == "__main__":
    main()
