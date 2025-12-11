from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from lab.models import Service, Panel


def _to_decimal(v) -> Optional[Decimal]:
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


class Command(BaseCommand):
    help = (
        "Синхронизирует цены Service из CSV: "
        "1) по коду исследования (Service.code), "
        "2) опционально — по коду панели (Panel.code)."
    )

    # Варианты заголовков, которые часто встречаются в выгрузках
    CODE_HEADERS = {
        "code", "код", "код_исследования", "service_code", "test_code",
        "panel_code", "Код", "Код_исследования"
    }
    PRICE_HEADERS = {
        "price", "cost", "цена", "стоимость", "amount", "Price", "Стоимость"
    }
    CURRENCY_HEADERS = {
        "currency", "валюта", "Currency", "Валюта"
    }

    def add_arguments(self, parser):
        # --- основной CSV по исследованиям ---
        parser.add_argument("csv_path", help="Путь к CSV-файлу с ценами по кодам исследований")
        parser.add_argument(
            "--encoding",
            default="utf-8",
            help="Кодировка основного файла (по умолчанию utf-8)",
        )
        parser.add_argument(
            "--delimiter",
            default=";",
            help="Разделитель основного CSV (по умолчанию ';')",
        )
        parser.add_argument(
            "--currency",
            default="RUB",
            help="Валюта по умолчанию, если нет колонки currency (по умолчанию RUB)",
        )
        parser.add_argument(
            "--col-code",
            default=None,
            help="Имя колонки для кода исследования (override авто-детекции)",
        )
        parser.add_argument(
            "--col-price",
            default=None,
            help="Имя колонки для цены (override авто-детекции)",
        )
        parser.add_argument(
            "--col-currency",
            default=None,
            help="Имя колонки для валюты (override авто-детекции)",
        )
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Создавать Service, если по коду не найден (иначе — только обновлять)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Пробный прогон без записи в базу",
        )

        # --- второй CSV по панелям ---
        parser.add_argument(
            "--panel-prices",
            default=None,
            help="Путь к CSV с ценами по коду панели (Panel.code). Формат: код;цена",
        )
        parser.add_argument(
            "--panel-encoding",
            default=None,
            help="Кодировка файла панелей (по умолчанию как --encoding)",
        )
        parser.add_argument(
            "--panel-delimiter",
            default=";",
            help="Разделитель CSV-файла панелей (по умолчанию ';')",
        )
        parser.add_argument(
            "--panel-has-header",
            action="store_true",
            help="Если указан, первая строка файла панелей считается заголовком",
        )
        parser.add_argument(
            "--panel-overwrite",
            action="store_true",
            help="Переписывать существующие цены сервисов ценой панели "
                 "(по умолчанию заполняем только пустые/нулевые).",
        )

    # ------------------ утилиты ------------------

    def _detect_columns(
        self,
        headers: List[str],
        override_code: Optional[str],
        override_price: Optional[str],
        override_currency: Optional[str],
    ) -> Tuple[str, str, Optional[str]]:
        def find(candidates: set[str]) -> Optional[str]:
            if not headers:
                return None

            # точное совпадение
            for h in headers:
                if h in candidates:
                    return h

            # без регистра/пробелов/лишних символов (включая BOM)
            lowered = {h.lower().strip().lstrip("\ufeff"): h for h in headers}
            for cand in candidates:
                k = cand.lower().strip()
                if k in lowered:
                    return lowered[k]
            return None

        col_code = override_code or find(self.CODE_HEADERS)
        col_price = override_price or find(self.PRICE_HEADERS)
        col_currency = override_currency or find(self.CURRENCY_HEADERS)

        if not col_code or not col_price:
            raise CommandError(
                f"Не найден(ы) необходимые столбцы. "
                f"Обнаруженные заголовки: {headers}. "
                f"Укажи --col-code и/или --col-price, либо поправь выгрузку."
            )
        return col_code, col_price, col_currency

    def _open_services_dictreader(
        self,
        p: Path,
        encoding: str,
        delimiter: str,
    ) -> csv.DictReader:
        """
        Очень прямолинейное чтение services CSV:
        - фиксированный разделитель,
        - DictReader,
        - без Sniffer.
        """
        text = p.read_text(encoding=encoding)
        lines = text.splitlines()
        if not lines:
            raise CommandError(f"Файл {p} пустой.")

        class SimpleDialect(csv.excel):
            pass

        SimpleDialect.delimiter = delimiter

        reader = csv.DictReader(lines, dialect=SimpleDialect)

        # подчистим BOM в первом заголовке, если он есть
        if reader.fieldnames:
            reader.fieldnames[0] = reader.fieldnames[0].lstrip("\ufeff")

        return reader

    def _load_panel_prices(
        self,
        path: Path,
        encoding: str,
        delimiter: str,
        has_header: bool,
    ) -> Tuple[Dict[str, Decimal], int]:
        """
        Простая загрузка вида:
            03.001;2700
            03.003;1550
        или
            panel_code;price;[currency]
        """
        panel_prices: Dict[str, Decimal] = {}
        invalid = 0

        with path.open(encoding=encoding, newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            if has_header:
                next(reader, None)

            for row in reader:
                if not row or len(row) < 2:
                    invalid += 1
                    continue

                raw_code = row[0] or ""
                code = raw_code.strip().lstrip("\ufeff")
                price = _to_decimal(row[1])
                if not code or price is None:
                    invalid += 1
                    continue

                panel_prices[code] = price

        return panel_prices, invalid

    def _apply_service_prices(
        self,
        rows_by_code: Dict[str, Dict[str, object]],
        default_currency: str,
        create_missing: bool,
        dry_run: bool,
    ) -> Dict[str, int]:
        if not rows_by_code:
            return {
                "rows": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "invalid": 0,
            }

        codes = list(rows_by_code.keys())

        services_map: Dict[str, Service] = Service.objects.in_bulk(codes, field_name="code")
        panels_map: Dict[str, Panel] = Panel.objects.in_bulk(codes, field_name="code")

        to_update: List[Service] = []
        to_create: List[Service] = []
        updated, created, unchanged = 0, 0, 0

        for code, payload in rows_by_code.items():
            price: Decimal = payload["price"]
            currency: Optional[str] = payload["currency"]

            svc = services_map.get(code)
            if svc is None:
                if not create_missing:
                    continue
                svc = Service(
                    code=code,
                    name=code,
                    cost=price,
                    currency=(currency or default_currency)[:8],
                    panel=panels_map.get(code),
                )
                to_create.append(svc)
                continue

            changed = False
            if svc.cost != price:
                svc.cost = price
                changed = True
            if currency and svc.currency != currency:
                svc.currency = currency
                changed = True

            if svc.panel_id is None and code in panels_map:
                svc.panel = panels_map[code]
                changed = True

            if changed:
                to_update.append(svc)
            else:
                unchanged += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN (services): изменения не записаны."))
            self.stdout.write(
                f"[Services] Строк: {len(rows_by_code)} | "
                f"Создаём: {len(to_create)} | Обновляем: {len(to_update)} | Без изменений: {unchanged}"
            )
        else:
            if to_create:
                Service.objects.bulk_create(to_create, batch_size=1000)
                created = len(to_create)
            if to_update:
                Service.objects.bulk_update(to_update, ["cost", "currency", "panel"], batch_size=1000)
                updated = len(to_update)

        return {
            "rows": len(rows_by_code),
            "created": created if not dry_run else len(to_create),
            "updated": updated if not dry_run else len(to_update),
            "unchanged": unchanged,
            "invalid": 0,
        }

    def _apply_panel_prices_to_services(
        self,
        panel_prices: Dict[str, Decimal],
        overwrite: bool,
        default_currency: str,
        dry_run: bool,
    ) -> Dict[str, int]:
        if not panel_prices:
            return {
                "panels": 0,
                "services_created": 0,
                "services_updated": 0,
                "services_skipped": 0,
                "panels_without_match": 0,
            }

        panel_codes = list(panel_prices.keys())

        panels_qs = Panel.objects.filter(code__in=panel_codes)
        panels_by_code = {p.code: p for p in panels_qs}

        panel_for_csv_code: Dict[str, Panel] = {}
        for csv_code in panel_codes:
            panel = panels_by_code.get(csv_code)
            if panel:
                panel_for_csv_code[csv_code] = panel

        services_qs = Service.objects.filter(code__in=panel_codes)
        services_by_code: Dict[str, Service] = {s.code: s for s in services_qs}

        to_create: List[Service] = []
        to_update: List[Service] = []

        created = updated = skipped = 0
        panels_without_match = 0

        for csv_code, price in panel_prices.items():
            panel = panel_for_csv_code.get(csv_code)
            if not panel:
                panels_without_match += 1
                continue

            svc = services_by_code.get(csv_code)

            if svc is None:
                svc = Service(
                    code=csv_code,
                    name=panel.name or csv_code,
                    panel=panel,
                    cost=price,
                    currency=default_currency,
                )
                to_create.append(svc)
                continue

            current_cost = svc.cost or Decimal("0")

            if not overwrite and current_cost != 0:
                skipped += 1
                continue

            if current_cost == price:
                skipped += 1
                continue

            svc.cost = price
            if svc.panel_id is None:
                svc.panel = panel
            if not svc.currency:
                svc.currency = default_currency

            to_update.append(svc)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN (panels): изменения по панелям не записаны."))
            self.stdout.write(
                f"[Panels] Панелей с ценой: {len(panel_prices)} | "
                f"Мапятся на Panel: {len(panel_for_csv_code)} | "
                f"Создаём Service: {len(to_create)} | "
                f"Обновляем Service: {len(to_update)} | "
                f"Пропущено Service: {skipped} | "
                f"Панелей без матча: {panels_without_match}"
            )
        else:
            if to_create:
                Service.objects.bulk_create(to_create, batch_size=1000)
                created = len(to_create)
            if to_update:
                Service.objects.bulk_update(to_update, ["cost", "currency", "panel"], batch_size=1000)
                updated = len(to_update)

        return {
            "panels": len(panel_prices),
            "services_created": created if not dry_run else len(to_create),
            "services_updated": updated if not dry_run else len(to_update),
            "services_skipped": skipped,
            "panels_without_match": panels_without_match,
        }

    # ------------------ handle ------------------

    @transaction.atomic
    def handle(self, *args, **opts):
        csv_path = Path(opts["csv_path"])
        if not csv_path.exists():
            raise CommandError(f"Файл не найден: {csv_path}")

        encoding = opts["encoding"]
        delimiter = opts["delimiter"] or ";"
        default_currency = (opts["currency"] or "RUB")[:8]
        dry_run = opts["dry_run"]
        create_missing = opts["create_missing"]

        reader = self._open_services_dictreader(csv_path, encoding, delimiter)
        headers = reader.fieldnames or []
        if not headers:
            raise CommandError("В основном файле отсутствуют заголовки.")

        col_code, col_price, col_currency = self._detect_columns(
            headers,
            opts.get("col_code"),
            opts.get("col_price"),
            opts.get("col_currency"),
        )

        rows_by_code: Dict[str, Dict[str, object]] = {}
        invalid_rows = 0

        for row in reader:
            raw_code = (row.get(col_code) or "")
            code = raw_code.strip().lstrip("\ufeff")
            price = _to_decimal(row.get(col_price))
            currency = (row.get(col_currency) or "").strip() if col_currency else ""

            if not code or price is None:
                invalid_rows += 1
                continue

            rows_by_code[code] = {
                "code": code,
                "price": price,
                "currency": (currency or default_currency)[:8] if currency or default_currency else None,
            }

        svc_stats = self._apply_service_prices(
            rows_by_code=rows_by_code,
            default_currency=default_currency,
            create_missing=create_missing,
            dry_run=dry_run,
        )

        panel_path_arg = opts.get("panel_prices")
        panel_stats = {
            "panels": 0,
            "services_created": 0,
            "services_updated": 0,
            "services_skipped": 0,
            "panels_without_match": 0,
        }
        panel_invalid = 0

        if panel_path_arg:
            panel_path = Path(panel_path_arg)
            if not panel_path.exists():
                raise CommandError(f"Файл панелей не найден: {panel_path}")

            panel_encoding = opts.get("panel_encoding") or encoding
            panel_delimiter = opts.get("panel_delimiter") or ";"
            panel_has_header = opts.get("panel_has_header", False)
            panel_overwrite = opts.get("panel_overwrite", False)

            panel_prices, panel_invalid = self._load_panel_prices(
                panel_path,
                encoding=panel_encoding,
                delimiter=panel_delimiter,
                has_header=panel_has_header,
            )

            panel_stats = self._apply_panel_prices_to_services(
                panel_prices=panel_prices,
                overwrite=panel_overwrite,
                default_currency=default_currency,
                dry_run=dry_run,
            )

        prefix = "[DRY-RUN] " if dry_run else ""

        summary = (
            f"{prefix}CSV-синхронизация завершена.\n"
            f"- Исследования (Service): строк={svc_stats['rows']}, "
            f"создано={svc_stats['created']}, обновлено={svc_stats['updated']}, "
            f"без изменений={svc_stats['unchanged']}, невалидных={invalid_rows}.\n"
        )

        if panel_path_arg:
            summary += (
                f"- Панели (Panel.code): панелей с ценой={panel_stats['panels']}, "
                f"создано сервисов={panel_stats['services_created']}, "
                f"обновлено сервисов={panel_stats['services_updated']}, "
                f"пропущено сервисов={panel_stats['services_skipped']}, "
                f"панелей без матча={panel_stats['panels_without_match']}, "
                f"невалидных строк панелей={panel_invalid}."
            )

        if (
            not dry_run
            and svc_stats["created"] == 0
            and svc_stats["updated"] == 0
            and panel_stats["services_created"] == 0
            and panel_stats["services_updated"] == 0
        ):
            self.stdout.write(self.style.WARNING("✔ Данных к изменению не оказалось.\n" + summary))
        else:
            self.stdout.write(self.style.SUCCESS("✅ " + summary))
