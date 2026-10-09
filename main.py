if __name__ == '__main__':
    try:
        from captioner.ui import main
        raise SystemExit(main())
    except Exception:
        # A windowed executable has no stderr. Preserve actionable startup
        # errors without recording audio, captions or credentials.
        import ctypes
        import os
        from pathlib import Path
        import traceback
        folder=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'LocalCaptions'
        folder.mkdir(parents=True,exist_ok=True)
        report=folder/'startup-error.log'
        report.write_text(traceback.format_exc(),encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None,f'启动失败，详细原因已保存至：\n{report}\n请检查依赖安装，或运行 start-debug.cmd。','听见 · 启动失败',0x10)
        raise SystemExit(1)
