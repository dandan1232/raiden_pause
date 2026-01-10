#!/usr/bin/env python
# @File     : test.py
# @Author   : 念安
# @Time     : 2026-01-10 20:18
# @Verison  : V1.0
# @Desctrion:

from pywinauto.application import Application
from pywinauto import Desktop
import time

app = Application(backend="uia").connect(path="explorer.exe")
taskBar = app.window(class_name="Shell_TrayWnd")
trayIcon = taskBar["显示隐藏的图标"].wrapper_object()
trayIcon.click()

time.sleep(0.25)

trayWindow = Desktop(backend="uia").window(class_name="NotifyIconOverflowWindow")
if trayWindow.exists(timeout=3):
    trayWindow.wait("visible", timeout=30, retry_interval=3)
else:
    # Some systems keep tray icons visible without an overflow window.
    trayWindow = taskBar

breakLoop: bool = False
for notification_area in trayWindow.children():
    for app_in_tray in notification_area.children():
        if "leigod" in str(app_in_tray).lower():
            app_in_tray.click_input()
            breakLoop = True
            break
    if breakLoop:
        break
