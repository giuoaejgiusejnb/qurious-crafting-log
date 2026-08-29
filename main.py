"""exe化（flet build）用のエントリポイント。実体は app/main.py にある。"""

import flet as ft

from app.main import main

if __name__ == "__main__":
    ft.run(main)
