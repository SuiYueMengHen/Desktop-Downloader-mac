# -*- mode: python ; coding: utf-8 -*-
# v1.0.2-alpha.2 — Startup splash, batch import redesign, performance & UI polish
# Changes: SplashOverlay FluentUI splash animation, BatchImportDialog redesign,
#           theme-aware card hover, history multi-P card polish, smoother progress rings


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('bin/ffmpeg', 'bin')],
    hiddenimports=['PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtXml', 'bilibili_api', 'bilibili_api.video', 'bilibili_api.user', 'bilibili_api.search', 'bilibili_api.clients', 'bilibili_api.clients.HTTPXClient', 'bilibili_api.exceptions', 'yt_dlp', 'yt_dlp.extractor', 'yt_dlp.downloader', 'yt_dlp.postprocessor', 'yt_dlp.extractor.bilibili'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas', 'sympy',
        'IPython', 'notebook', 'jupyter',
        'PIL.ImageShow', 'PIL.ImageGrab', 'PIL.ImageQt', 'PIL.WebP',
        'PIL.ImagePalette', 'PIL.ImImagePlugin', 'PIL.PcdImagePlugin',
        'PIL.PcxImagePlugin', 'PIL.FpxImagePlugin', 'PIL.GbrImagePlugin',
        'PIL.MicImagePlugin', 'PIL.MpoImagePlugin', 'PIL.PalmImagePlugin',
        'PIL.PixarImagePlugin', 'PIL.WmfImagePlugin', 'PIL.XbmImagePlugin',
        'PIL.XpmImagePlugin', 'PIL.FtexPlugin', 'PIL.SgiImagePlugin',
        'PIL.TgaImagePlugin', 'PIL.IcnsImagePlugin', 'PIL.BufrStubImagePlugin',
        'PIL.CurImagePlugin', 'PIL.DcxImagePlugin', 'PIL.DdsImagePlugin',
        'PIL.EpsImagePlugin', 'PIL.FitsStubImagePlugin', 'PIL.FliImagePlugin',
        'PIL.FtexImagePlugin', 'PIL.GdImagePlugin',
        'PIL.Hdf5StubImagePlugin', 'PIL.IptcImagePlugin',
        'PIL.Jpeg2KImagePlugin', 'PIL.McIdasImagePlugin', 'PIL.MpegImagePlugin',
        'PIL.MspImagePlugin', 'PIL.PaletteFile', 'PIL.PdfParser',
        'PIL.PpmImagePlugin', 'PIL.PsdImagePlugin',
        'PIL.SgiImagePlugin', 'PIL.SunImagePlugin',
        'PIL.WalImageFile', 'PIL.XbmImagePlugin', 'PIL.XpmImagePlugin',
        'unittest', 'setuptools', 'pip', 'pdb', 'venv',
        'ensurepip', 'lib2to3', 'cProfile', 'pytest',
        'turtle', 'turtledemo', 'curses', 'nis', 'ossaudiodev',
        'tkinter.test', 'tkinter.tix',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Desktop Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/tmp/DesktopDownloader.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='Desktop Downloader',
)
app = BUNDLE(
    coll,
    name='Desktop Downloader.app',
    icon='/tmp/DesktopDownloader.icns',
    bundle_identifier='com.desktop-downloader.app',
)
