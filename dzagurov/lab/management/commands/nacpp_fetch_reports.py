import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage
from lab.nacpp_client import NacppClient
from lab.models import Order

class Command(BaseCommand):
    help = "Скачивает печатки (PDF) по заявкам в MEDIA_ROOT/NACPP_REPORTS_DIR/<orderno>/"

    def add_arguments(self, parser):
        parser.add_argument("orderno", nargs="+", help="Номера заявок")

    def handle(self, *args, **opts):
        client = NacppClient()
        try:
            base_dir = Path(settings.MEDIA_ROOT) / settings.NACPP_REPORTS_DIR
            base_dir.mkdir(parents=True, exist_ok=True)

            for num in opts["orderno"]:
                meta = client.get_report_pdf_bundle(num, with_logo=True)
                # meta — JSON со списком файлов/URL-ов. Пройдёмся и сохраним.
                order_dir = base_dir / num
                order_dir.mkdir(parents=True, exist_ok=True)

                files_saved = 0
                # ожидаем структуру вида {"files":[{"name":"...", "url":"..."}, ...]} или аналогичную
                items = meta.get("files") or meta.get("reports") or []
                for f in items:
                    url = f.get("url") or f.get("href")
                    name = f.get("name") or os.path.basename(url or "report.pdf")
                    if not url:
                        continue
                    r = client.s.get(url, timeout=settings.NACPP_HTTP_TIMEOUT)
                    r.raise_for_status()
                    path = order_dir / name
                    path.write_bytes(r.content)
                    files_saved += 1

                self.stdout.write(self.style.SUCCESS(f"{num}: сохранено файлов — {files_saved}"))
        finally:
            client.logout()
