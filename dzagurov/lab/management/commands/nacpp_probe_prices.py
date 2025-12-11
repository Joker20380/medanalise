# lab/management/commands/nacpp_probe_prices.py
from __future__ import annotations

import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from lab.nacpp_client import NacppClient

CANDIDATE_PATHS = [
    "/price", "/prices", "/pricelist", "/services", "/catalog", "/panels",
    "/lk/prices", "/lk/price", "/lk/services",
    "/uslugi", "/uslugi/ceny", "/stoimost", "/prajs", "/prajs-list"
]

MONEY_RE = re.compile(r"([\d\s]+[.,]\d{2}|\d+)\s*(?:р|руб|rub|₽)\b", re.I)

class Command(BaseCommand):
    help = "Проба страниц с прайсом: скачивает HTML, ищет ценовые паттерны, сохраняет дампы"

    def add_arguments(self, parser):
        parser.add_argument("--extra", nargs="*", help="Доп. относительные пути, например /lk/prajs")

    def handle(self, *args, **opts):
        out_dir = Path(settings.MEDIA_ROOT) / "nacpp_price_probe"
        out_dir.mkdir(parents=True, exist_ok=True)

        client = NacppClient()
        total = 0
        hits = 0
        try:
            paths = list(CANDIDATE_PATHS)
            extra = opts.get("extra") or []
            for p in extra:
                if not p.startswith("/"):
                    p = "/" + p
                paths.append(p)

            self.stdout.write(f"→ base: {client.base}")
            for rel in paths:
                url = client.base + rel
                try:
                    r = client.s.get(url, timeout=client.timeout, allow_redirects=True)
                    total += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"{rel}: error {e}"))
                    continue

                body = (r.text or "")
                size = len(body)
                if r.status_code == 200 and size:
                    (out_dir / (rel.strip("/").replace("/", "_") or "root")).with_suffix(".html").write_text(
                        body, encoding="utf-8"
                    )
                    found = bool(MONEY_RE.search(body))
                    mark = "💰" if found else "—"
                    if found:
                        hits += 1
                    self.stdout.write(f"{mark} {rel} :: 200, {size} bytes, saved")
                else:
                    self.stdout.write(f"— {rel} :: {r.status_code}, {size} bytes")

            if hits == 0:
                self.stdout.write(self.style.WARNING(
                    "❌ Не нашли ценовых паттернов на типовых страницах. "
                    "Дай точный URL страницы с ценами — подстрою парсер."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"✅ Найдены страницы с ценовыми паттернами: {hits}. "
                    f"Посмотри файлы в {out_dir} и скинь точный URL."
                ))
        finally:
            client.logout()
