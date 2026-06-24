# Desktop Downloader

多平台视频下载器，支持 **Bilibili** 视频、UP 主空间、UP 主合集/列表的批量解析与下载。基于 PySide6 + qfluentwidgets 构建，拥有现代化的 Fluent Design 界面。

## 功能

- **视频解析** — 粘贴链接一键解析，自动获取画质、大小、时长等信息
- **多 P 下载** — 支持选择多 P 视频的指定分 P 下载
- **批量解析** — 支持 UP 主空间和合集页的批量解析，以卡片形式展示所有视频
- **下载管理** — 支持多任务并行下载、暂停/继续、速度限制、等待队列
- **下载列表** — 区分「正在下载」和「等待下载」，一键全部暂停/取消/开始
- **剪贴板监控** — 自动检测剪贴板中的视频链接并跳转
- **登录集成** — 支持 Bilibili 扫码登录以获取更高的下载画质
- **下载历史** — 记录所有已完成下载，支持重新下载和打开所在目录
- **主题切换** — 支持浅色/深色/跟随系统主题
- **FFmpeg 合并** — 自动合并音视频流，内置 FFmpeg

## 截图

![主界面](screenshots/home.png)
*主页 — 视频解析与下载入口*

![下载列表](screenshots/download.png)
*下载列表 — 管理所有下载任务*

![设置页](screenshots/settings.png)
*设置 — 自定义下载路径、并发数、速度限制等*

## 快速开始

### 前置依赖

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/)（已包含在 `bin/` 目录中）

### 安装

```bash
git clone https://github.com/SuiYueMengHen/desktop-downloader.git
cd desktop-downloader
pip install -r requirements.txt
python main.py
```

### 打包为独立应用

```bash
pip install pyinstaller
pyinstaller "Desktop Downloader.spec"
```

构建产物位于 `dist/Desktop Downloader.app`。可用 `create-dmg` 或 `hdiutil` 进一步打包为 `.dmg`。

```bash
hdiutil create -volname "Desktop Downloader v1.0.1-alpha.1" \
  -srcfolder "dist/Desktop Downloader.app" \
  -ov -format UDZO \
  "Desktop Downloader v1.0.1-alpha.1.dmg"
```

## 使用说明

1. 启动应用后，在主页输入框粘贴 Bilibili 视频/UP 主/合集链接，点击「解析」
2. 解析完成后选择画质和分 P（如有），点击「下载」
3. 切换到「下载列表」查看下载进度
4. 在「设置」中可调整下载路径、并发数、速度限制和剪贴板监控

## 技术栈

| 类别       | 技术                                     |
| ---------- | ---------------------------------------- |
| GUI 框架   | PySide6 (Qt for Python)                  |
| UI 组件库  | qfluentwidgets (Fluent Design)           |
| 视频解析   | bilibili-api-python, yt-dlp              |
| 网络请求   | httpx                                    |
| 音视频合并 | FFmpeg                                   |
| 打包工具   | PyInstaller                              |

## 项目结构

```
desktop-downloader/
├── app/
│   ├── __init__.py          # 版本号
│   ├── main_window.py       # 主窗口 + 导航
│   ├── config.py            # 配置管理
│   ├── download_manager.py  # 下载管理器
│   ├── clipboard_monitor.py # 剪贴板监控
│   ├── cookie_manager.py    # Cookie / 登录管理
│   ├── history_manager.py   # 下载历史记录
│   ├── notification.py      # 系统通知
│   ├── platforms/           # 平台解析器（bilibili 等）
│   ├── ui/                  # UI 页面
│   │   ├── home_page.py
│   │   ├── download_page.py
│   │   ├── settings_page.py
│   │   ├── history_page.py
│   │   ├── up_page.py
│   │   ├── collection_page.py
│   │   ├── login_dialog.py
│   │   └── styles.py
│   └── utils/               # 工具函数
├── bin/
│   └── ffmpeg               # 内置 FFmpeg
├── main.py                  # 入口
├── requirements.txt
└── Desktop Downloader.spec  # PyInstaller 打包配置
```

## 许可证

[MIT](LICENSE)
