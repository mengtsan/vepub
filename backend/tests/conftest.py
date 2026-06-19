"""共用 pytest 設定：把 backend 根目錄加進 sys.path。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
