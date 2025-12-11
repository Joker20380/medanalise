from __future__ import annotations
from decimal import Decimal
from django.core.management.base import BaseCommand
from lab.nacpp_client import NacppClient
from lab.models import Service, Panel


def _to_decimal(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


class Command(BaseCommand):
    help = "Обнаруживает прайс на сервере (API/HTML), парсит и синхронизирует Service."

    def handle(self, *args, **opts):
        c = NacppClient()
        try:
            # Сначала пробуем известные API-роуты с полноценным парсингом (XML/JSON) «как есть»
            found = c.discover_price_endpoints()

            # Если API молчит (пустое тело) — попытаемся выкачать типовые HTML-страницы прайса
            if not found:
                self.stdout.write(self.style.WARNING("API прайса молчит. Пробуем HTML-страницы…"))
                pages = ["/price", "/prices", "/services", "/catalog", "/panels", "/prajs", "/pricelist", "/lk/prices"]
                for p in pages:
                    r = c.s.get(c.base + p, timeout=c.timeout, allow_redirects=True)
                    if r.status_code == 200 and (r.text or "").strip():
                        found.append(({"page": p}, r.text))

            total = 0
            for params, text in found:
                items = c.parse_price_payload(text)
                if not items:
                    continue

                for it in items:
                    code = (it.get("code") or "").strip()
                    name = (it.get("name") or code).strip()
                    cost = _to_decimal(it.get("cost"))
                    currency = (it.get("currency") or "RUB")[:8]
                    duration = (it.get("duration") or "").strip()
                    comment = (it.get("comment") or "").strip()

                    panel = Panel.objects.filter(code=code).first() if code else None

                    Service.objects.update_or_create(
                        code=code,
                        defaults={
                            "name": name,
                            "cost": cost,
                            "currency": currency,
                            "duration": duration,
                            "comment": comment,
                            "panel": panel,
                        },
                    )
                    total += 1

            if total == 0:
                self.stdout.write(self.style.WARNING("❌ Прайс не удалось распознать. Укажи точный URL страницы с ценами — подстрою парсер."))
            else:
                self.stdout.write(self.style.SUCCESS(f"✅ Синхронизировано позиций прайса: {total}"))
        finally:
            c.logout()
