from pathlib import Path

import flet as ft

from app.core.update_check import GITHUB_OWNER, GITHUB_REPO

ISSUES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues"


def build_contact_view(page: ft.Page, db_path: Path) -> ft.Control:
    """お問い合わせ画面を構築する。GitHub Issuesページへのリンクのみのシンプルな内容。"""

    async def open_issues_page(e: ft.Event[ft.Button]) -> None:
        await ft.UrlLauncher().launch_url(ISSUES_URL)

    return ft.Column(
        [
            ft.Text("お問い合わせ", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("不具合報告・ご要望は、GitHub Issuesページまでお願いします。"),
            ft.Button(
                content="GitHub Issuesページを開く",
                icon=ft.Icons.OPEN_IN_NEW,
                on_click=open_issues_page,
            ),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
