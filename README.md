# 雷神加速器自动暂停脚本

检测游戏/Steam 进程退出后，自动提示并尝试点击雷神加速器的“暂停/开启时长”按钮，减少无效时长消耗。

## 功能概览

- 监听 Steam / EA / 多款游戏进程
- 进程全部退出时触发自动暂停流程
- 通过模板匹配定位按钮并模拟点击
- Windows 通知提示执行结果

## 环境要求

- Windows 10/11
- Python 3.9+

依赖：

```
pip install psutil pyautogui pillow opencv-python win10toast pywin32
```

## 资源文件

将按钮模板放到 `assets/`：

- `assets/start_button.png`：加速中（红色“暂停时长”）
- `assets/unstart_button.png`：已暂停（灰色“开启时长”）

可按需补充全屏截图用于调试（非必需）。

## 运行方式

```
python raiden_pause.py
```

建议加入开机自启或随 Steam 启动。

## 配置说明

在 `raiden_pause.py` 顶部可调整：

- `WINDOW_TITLE_KEYWORDS`：雷神窗口标题关键字
- `WATCH_PROCESSES`：需要监听的进程名（小写）
- `POLL_INTERVAL`：轮询间隔（秒）
- `MATCH_CONFIDENCE`：模板匹配阈值

## 使用流程（V1）

1. 游戏/Steam 进程退出
2. 弹出通知提醒
3. 自动尝试切换到雷神窗口
4. 截屏识别“暂停时长”按钮并点击
5. 二次通知提示结果

## 已知限制

- 需要用户首次提供按钮模板截图
- 按钮样式变化会影响识别
- 多显示器支持计划在 2.0 版本加入


