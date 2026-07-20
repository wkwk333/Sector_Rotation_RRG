# -*- coding: utf-8 -*-
"""
console_utf8.py
================
Windowsのコンソール(PowerShell/コマンドプロンプト)は既定でShift-JIS系の
コードページ(932)になっていることが多く、UTF-8で書かれたスクリプトの
print() 出力(日本語)が文字化けする原因になる。

各スクリプトの先頭で `import console_utf8` するだけで、
- コンソールの入出力コードページを UTF-8 (65001) に切り替え
- Python の標準出力/標準エラーの文字コードも UTF-8 に再設定
し、文字化けを防ぐ。Windows以外では何もしない。
"""
import sys

if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
