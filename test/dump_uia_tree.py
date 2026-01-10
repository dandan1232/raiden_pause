from pywinauto import Desktop


def dump_tree(elem, depth: int = 0, max_depth: int = 5) -> None:
    if depth > max_depth:
        return
    try:
        name = elem.window_text()
    except Exception:
        name = ""
    try:
        ctrl_type = elem.friendly_class_name()
    except Exception:
        ctrl_type = ""
    try:
        auto_id = getattr(elem.element_info, "automation_id", "")
    except Exception:
        auto_id = ""
    print(f"{'  '*depth}{ctrl_type} name={name!r} auto_id={auto_id!r}")
    try:
        children = elem.children()
    except Exception:
        return
    for child in children:
        dump_tree(child, depth + 1, max_depth)


def main() -> None:
    # Adjust keyword if needed.
    title_keywords = ["雷神加速器", "Leishen", "Raiden"]
    wins = Desktop(backend="uia").windows(visible_only=False)
    for win in wins:
        try:
            title = win.window_text() or ""
        except Exception:
            title = ""
        if any(k in title for k in title_keywords):
            print(f"Window: {title!r}")
            dump_tree(win)


if __name__ == "__main__":
    main()
