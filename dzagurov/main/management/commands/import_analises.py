import json
import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from main.models import Analise, Category, Material, ResultKind


# --- utils -------------------------------------------------------------------
def norm(s: str) -> str:
    return (s or "").strip().lower()


def _norm_key(s: str) -> str:
    # нормализация заголовков: lower + trim + схлопывание двойных пробелов
    return (s or "").strip().lower().replace("  ", " ")


def normalize_row_keys(row: dict) -> dict:
    # приводим все ключи строки к нормализованному виду
    return {_norm_key(k): v for k, v in row.items()}


# алиасы заголовков в НИЖНЕМ регистре
RUS_COLS = {
    "code": ["код исследования", "код \nисследования", "code"],
    "name": ["наименование исследования", "наименование", "name"],
    "category": [
        "категория",
        "категория анализа",
        "категория исследований",
        "раздел",
        "подраздел",
        "группа",
        "rubric",
        "category",
    ],
    "material": ["используемый  материал", "материал", "material"],
    "result": ["результат исследования", "result"],
    "tat": ["срок* (рабочие дни)", "срок (рабочие дни)", "срок", "tat_days", "tat"],
    "urgent": ["возможность срочного выполнения", "срочно", "срочность", "urgent"],
    "price": ["цена", "стоимость", "price"],
    "description": ["описание", "description"],
    "preparation": ["подготовка", "preparation"],
    "clinical_info": ["клиническая информация", "clinical_info"],
    "interpretation": ["интерпритация результатов", "интерпретация результатов", "interpretation"],
}


def pick(row_norm_keys: dict, keys, default=""):
    """
    Читает значение по списку алиасов. Ожидает, что ключи row уже нормализованы _norm_key().
    """
    for k in keys:
        kk = _norm_key(k)
        if kk in row_norm_keys and row_norm_keys[kk] not in (None, ""):
            return row_norm_keys[kk]
    return default


def normalize_result_kind(raw: str | None) -> str:
    if not raw:
        return ResultKind.OTHER
    r = str(raw).strip().lower()
    if r.startswith("кол") or "абс" in r or "%" in r:
        return ResultKind.QUANTITATIVE
    if r.startswith("кач"):
        return ResultKind.QUALITATIVE
    if "заключ" in r:
        return ResultKind.CONCLUSION
    if "комплекс" in r:
        return ResultKind.COMPLEX
    if "/" in r or "+" in r:
        return ResultKind.MIXED
    return ResultKind.OTHER


def parse_tat(raw: str | None) -> tuple[int | None, str]:
    if not raw:
        return None, ""
    s = str(raw).strip()
    try:
        return int(s), ""
    except ValueError:
        digits = "".join(ch for ch in s if ch.isdigit())
        return (int(digits) if digits else None), s


def to_decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    val = str(raw).replace(" ", "").replace(",", ".")
    try:
        return Decimal(val)
    except InvalidOperation:
        return None


# --- command -----------------------------------------------------------------
class Command(BaseCommand):
    help = (
        "Импорт/апдейт анализов из CSV/JSON. Ожидаются русские заголовки из выгрузки.\n"
        "Идентификация по 'Код исследования'."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Путь к CSV/JSON файлу")
        parser.add_argument(
            "--format",
            choices=["csv", "json"],
            help="Формат файла. Если не указан — определяется по расширению",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8",
            help="Кодировка входного файла (по умолчанию utf-8)",
        )
        parser.add_argument(
            "--delimiter",
            default=",",
            help="Разделитель CSV (по умолчанию ',')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать, что будет создано/обновлено, без записи",
        )
        parser.add_argument(
            "--category-fallback",
            action="store_true",
            help="Если категория не указана, автоматически создать 'Без категории' и привязать к ней",
        )
        parser.add_argument(
            "--category-column",
            type=str,
            help="Явное имя колонки категории (перебивает авто-детект алиасов)",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"]).expanduser()
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")

        fmt = opts.get("format") or path.suffix.lstrip(".").lower()
        if fmt not in {"csv", "json"}:
            raise CommandError("Не удалось определить формат. Укажите --format csv|json")

        rows_raw = self._load_rows(path, fmt, opts["encoding"], opts["delimiter"])
        if not rows_raw:
            self.stdout.write(self.style.WARNING("Данных нет — нечего импортировать"))
            return

        # Нормализуем ключи у каждой строки
        rows = [normalize_row_keys(r) for r in rows_raw]

        created = updated = skipped = 0
        fallback_category = None
        explicit_cat_col = _norm_key(opts.get("category_column") or "")

        with transaction.atomic():
            for rowsrc in rows:
                code = str(pick(rowsrc, RUS_COLS["code"])).strip()
                if not code:
                    skipped += 1
                    continue

                name = str(pick(rowsrc, RUS_COLS["name"])).strip()
                # категория: либо явно указанная колонка, либо алиасы
                if explicit_cat_col:
                    cat_name = str(rowsrc.get(explicit_cat_col, "")).strip()
                else:
                    cat_name = str(pick(rowsrc, RUS_COLS["category"], "")).strip()
                mat_name = str(pick(rowsrc, RUS_COLS["material"], "")).strip()
                result_raw = str(pick(rowsrc, RUS_COLS["result"], "")).strip()
                tat_raw = str(pick(rowsrc, RUS_COLS["tat"], "")).strip()
                urgent_raw = str(pick(rowsrc, RUS_COLS["urgent"], "")).strip().lower()
                price_raw = str(pick(rowsrc, RUS_COLS["price"], "")).strip()
                description = str(pick(rowsrc, RUS_COLS["description"], ""))
                preparation = str(pick(rowsrc, RUS_COLS["preparation"], ""))
                clinical_info = str(pick(rowsrc, RUS_COLS["clinical_info"], ""))
                interpretation = str(pick(rowsrc, RUS_COLS["interpretation"], ""))

                # --- Category (уникальность по name_hash, полное имя в full_name)
                category = None
                if cat_name:
                    cat_base = cat_name.strip()
                    cat_hash = hashlib.sha256(norm(cat_base).encode("utf-8")).hexdigest()
                    category, _ = Category.objects.get_or_create(
                        name_hash=cat_hash,
                        defaults={
                            "full_name": cat_base,          # полный текст
                            "name": cat_base[:255],         # короткий лейбл для UI
                        },
                    )
                elif opts.get("category_fallback"):
                    if not fallback_category:
                        base = "Без категории"
                        base_hash = hashlib.sha256(norm(base).encode("utf-8")).hexdigest()
                        fallback_category, _ = Category.objects.get_or_create(
                            name_hash=base_hash,
                            defaults={
                                "full_name": base,
                                "name": base,
                            },
                        )
                    category = fallback_category

                # --- Material (уникальность по name_hash, полное имя в full_name)
                material = None
                if mat_name:
                    mat_base = mat_name.strip()
                    mat_hash = hashlib.sha256(norm(mat_base).encode("utf-8")).hexdigest()
                    material, _ = Material.objects.get_or_create(
                        name_hash=mat_hash,
                        defaults={
                            "full_name": mat_base,         # полный текст
                            "name": mat_base[:255],        # короткий лейбл
                            # normalized_name не передаём — посчитает save()
                        },
                    )

                tat_days, tat_note = parse_tat(tat_raw)
                urgent = None
                if urgent_raw:
                    urgent = urgent_raw in {"да", "yes", "true", "1"}

                defaults = dict(
                    name=name,  # Analise.name = TextField (longtext)
                    category=category,
                    material=material,
                    result_kind=normalize_result_kind(result_raw),
                    result_kind_raw=result_raw[:128],  # CharField(128)
                    turnaround_days=tat_days,
                    turnaround_note=tat_note[:32],     # CharField(32)
                    urgent_available=urgent,
                    price=to_decimal(price_raw),
                    description=description,
                    preparation=preparation,
                    clinical_info=clinical_info,
                    interpretation=interpretation,
                )

                if opts["dry_run"]:
                    exists = Analise.objects.filter(code=code).only("pk").exists()
                    created += int(not exists)
                    updated += int(exists)
                    continue

                obj, is_created = Analise.objects.update_or_create(code=code, defaults=defaults)
                created += int(is_created)
                updated += int(not is_created)

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY-RUN режим: изменения не записаны."))
        self.stdout.write(
            self.style.SUCCESS(f"Создано: {created}; Обновлено: {updated}; Пропущено: {skipped}")
        )

    # --- loaders ------------------------------------------------------------
    def _load_rows(self, path: Path, fmt: str, encoding: str, delimiter: str):
        if fmt == "csv":
            return self._load_csv(path, encoding, delimiter)
        return self._load_json(path, encoding)

    def _load_csv(self, path: Path, encoding: str, delimiter: str):
        with path.open("r", encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            return list(reader)

    def _load_json(self, path: Path, encoding: str):
        with path.open("r", encoding=encoding) as fh:
            data = json.load(fh)
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            if isinstance(data, list):
                return data
            raise CommandError("JSON должен быть списком объектов или иметь ключ 'data'")
