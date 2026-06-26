"""
Central message strings for the Bilibili downloader application.
All user-facing Chinese strings are defined here as constants
for easy maintenance and consistency across the UI.
"""


class Messages:
    # ── Window / Header titles ──
    WINDOW_SEARCH_HEADER = "搜索"
    WINDOW_ERROR_TITLE = "搜索失败"

    # ── Button labels ──
    BUTTON_PARSE_DOWNLOAD = "解析下载"
    BUTTON_VIEW_HOME = "查看主页"
    BUTTON_SEARCH = "搜索"
    BUTTON_SEARCH_VIDEO = "搜索视频"
    BUTTON_SEARCH_UPLOADER = "搜索UP主"
    BUTTON_LOAD_MORE = "加载更多"

    # ── Hints / Descriptions ──
    HINT_SEARCH_DESC = "搜索 Bilibili 视频或UP主，点击「解析下载」或「查看主页」"
    HINT_EMPTY = "输入关键词搜索Bilibili视频或UP主"
    HINT_RESULTS_LABEL = "搜索结果"

    # ── Placeholder texts ──
    PLACEHOLDER_SEARCH = "输入关键词搜索B站视频或UP主..."

    # ── Loading messages ──
    LOADING_SEARCHING = "正在搜索..."
    LOADING_VIDEO = "正在搜索视频..."
    LOADING_UPLOADER = "正在搜索UP主..."

    # ── Error messages ──
    ERROR_EMPTY_KEYWORD = "请输入搜索关键词"
    ERROR_SEARCH_FAILED = "搜索失败: {}"

    # ── Fallback / Default values ──
    FALLBACK_TITLE = "无标题"
    FALLBACK_NAME = "未知"
    FALLBACK_SIGN = "这个人很懒，什么都没写"

    # ── Dynamic labels (used in conditional display logic) ──
    LABEL_VIDEO = "视频"
    LABEL_UPLOADER = "UP主"

    # ── Format templates (call .format() with dynamic values) ──
    FORMAT_META = "{} · {}次播放 · {}"
    FORMAT_UPLOADER_STATS = "粉丝 {} · {} 视频 · Lv.{}"
    FORMAT_LOAD_MORE = "加载更多（{}/{}）"
    FORMAT_STATUS = "共 {} 个{}，已加载 {}"


M = Messages()
