from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.core.management import BaseCommand, call_command, CommandError


class Command(BaseCommand):
    help = (
        "Полный цикл обновления из NACPP:\n"
        "1) nacpp_sync_catalogs — панели, аналиты, биоматериалы, преаналитика и т.д.\n"
        "2) nacpp_sync_prices_csv — обновление цен (по исследованиям и/или панелям)."
    )

    def add_arguments(self, parser):
        # --- общий флаг ---
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Прогнать цены в режиме dry-run (каталоги — в бою, цены — только dry-run).",
        )

        parser.add_argument(
            "--skip-catalogs",
            action="store_true",
            help="Пропустить шаг nacpp_sync_catalogs.",
        )
        parser.add_argument(
            "--skip-prices",
            action="store_true",
            help="Пропустить шаг обновления цен.",
        )

        # --- блок по ценам ---
        parser.add_argument(
            "--services-csv",
            default="data/services_stub.csv",
            help=(
                "CSV с ценами по кодам исследований (первичный прайс). "
                "Если файла нет или он пустой, будет автоматически создана заглушка."
            ),
        )
        parser.add_argument(
            "--services-delimiter",
            default=";",
            help="Разделитель для services CSV (по умолчанию ';').",
        )
        parser.add_argument(
            "--services-encoding",
            default="utf-8",
            help="Кодировка services CSV (по умолчанию utf-8).",
        )
        parser.add_argument(
            "--panel-prices",
            default="data/0148.csv",
            help=(
                "CSV с ценами по Panel.code (например, 0148.csv вида '03.001;2700'). "
                "По умолчанию: data/0148.csv."
            ),
        )
        parser.add_argument(
            "--panel-delimiter",
            default=";",
            help="Разделитель для panel-prices CSV (по умолчанию ';').",
        )
        parser.add_argument(
            "--panel-encoding",
            default=None,
            help="Кодировка panel-prices CSV (по умолчанию как services-encoding).",
        )
        parser.add_argument(
            "--panel-has-header",
            action="store_true",
            help="Если указано, первая строка panel-prices считается заголовком.",
        )
        parser.add_argument(
            "--panel-overwrite",
            action="store_true",
            help="Жёстко перезаписывать существующие цены сервисов ценой панели.",
        )
        parser.add_argument(
            "--currency",
            default="RUB",
            help="Валюта по умолчанию для цен (по умолчанию RUB).",
        )
        parser.add_argument(
            "--create-missing-services",
            action="store_true",
            help="Разрешить nacpp_sync_prices_csv создавать отсутствующие Service по коду.",
        )

    def _ensure_stub_services_csv(self, path: Path, delimiter: str, encoding: str):
        """
        Гарантируем, что services_csv существует и не пустой.
        Если файл отсутствует или пустой — создаём минимальную заглушку:
        code;price\nDUMMY;0
        """
        recreate = False
        if path.exists():
            try:
                if path.stat().st_size <= 0:
                    recreate = True
            except OSError:
                recreate = True
        else:
            recreate = True

        if not recreate:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"code{delimiter}price\n"
        body = f"DUMMY{delimiter}0\n"
        path.write_text(header + body, encoding=encoding)

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        skip_catalogs: bool = options["skip_catalogs"]
        skip_prices: bool = options["skip_prices"]

        verbosity = int(options.get("verbosity", 1))

        # --- 1. Синхронизируем каталоги с NACPP ---
        if not skip_catalogs:
            self.stdout.write(self.style.MIGRATE_HEADING("==> Шаг 1/2: nacpp_sync_catalogs"))
            try:
                call_command("nacpp_sync_catalogs", verbosity=verbosity)
            except Exception as e:
                raise CommandError(f"nacpp_sync_catalogs завершилась с ошибкой: {e}")
        else:
            self.stdout.write(self.style.WARNING("Шаг nacpp_sync_catalogs пропущен (--skip-catalogs)."))

        # --- 2. Обновляем цены через отдельный процесс ---
        if skip_prices:
            self.stdout.write(self.style.WARNING("Шаг обновления цен пропущен (--skip-prices)."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("==> Шаг 2/2: nacpp_sync_prices_csv (subprocess)"))

        services_csv = Path(options["services_csv"])
        services_delimiter = options["services_delimiter"]
        services_encoding = options["services_encoding"]
        currency = options["currency"]
        create_missing_services = options["create_missing_services"]

        panel_prices_path = options["panel_prices"]
        panel_delimiter = options["panel_delimiter"]
        panel_encoding = options["panel_encoding"] or services_encoding
        panel_has_header = options["panel_has_header"]
        panel_overwrite = options["panel_overwrite"]

        # 2.1. Гарантируем, что stub-файл для сервисов валидный
        self._ensure_stub_services_csv(
            path=services_csv,
            delimiter=services_delimiter,
            encoding=services_encoding,
        )

        # 2.2. Проверяем наличие panel-prices
        panel_prices = None
        if panel_prices_path:
            panel_prices = Path(panel_prices_path)
            if not panel_prices.exists():
                raise CommandError(
                    f"Файл с ценами по панелям не найден: {panel_prices}. "
                    f"Либо положи его туда, либо явно передай --panel-prices=..."
                )

        # --- 2.3. Собираем команду, ровно как ты её гоняешь из консоли ---
        cmd = [
            sys.executable,
            "manage.py",
            "nacpp_sync_prices_csv",
            str(services_csv),
            "--encoding", services_encoding,
            "--delimiter", services_delimiter,
            "--currency", currency,
        ]

        if create_missing_services:
            cmd.append("--create-missing")

        if dry_run:
            cmd.append("--dry-run")

        if panel_prices is not None:
            cmd.extend([
                "--panel-prices", str(panel_prices),
                "--panel-encoding", panel_encoding,
                "--panel-delimiter", panel_delimiter,
            ])
            if panel_has_header:
                cmd.append("--panel-has-header")
            if panel_overwrite:
                cmd.append("--panel-overwrite")

        # пробрасываем уровень verbose, если что
        if verbosity and verbosity > 1:
            cmd.extend(["-v", str(verbosity)])

        self.stdout.write(self.style.NOTICE(f"Запускаем: {' '.join(cmd)}"))

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            raise CommandError(f"Не удалось запустить nacpp_sync_prices_csv как subprocess: {e}")

        # логируем stdout/stderr из дочернего процесса
        if result.stdout:
            self.stdout.write(result.stdout)
        if result.stderr:
            self.stderr.write(result.stderr)

        if result.returncode != 0:
            raise CommandError(
                f"nacpp_sync_prices_csv (subprocess) завершилась с кодом {result.returncode}"
            )

        self.stdout.write(self.style.SUCCESS("✅ Полный цикл NACPP-синхронизации завершён."))
