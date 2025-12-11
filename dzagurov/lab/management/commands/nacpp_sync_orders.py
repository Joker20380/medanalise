from django.core.management.base import BaseCommand
from django.db import transaction
from lab.models import Order, OrderPanel, Panel, Test, ResultEntry, Analyte
from lab.nacpp_client import NacppClient


class Command(BaseCommand):
    help = "Загрузка заявок и результатов с сервера kdldzagurov.ru"

    def add_arguments(self, parser):
        parser.add_argument("--only-pending", action="store_true", help="Только pending")
        parser.add_argument("--date-start", help="YYYY/MM/DD")
        parser.add_argument("--date-end", help="YYYY/MM/DD")

    def handle(self, *args, **opts):
        client = NacppClient()
        try:
            order_numbers = set()

            if opts.get("only_pending"):
                pend = client.get_pending()
                for o in pend.findall(".//orderno"):
                    order_numbers.add((o.text or "").strip())

            ds = opts.get("date_start")
            de = opts.get("date_end")
            if ds and de:
                root = client.get_orders_by_period(ds, de, extended=True)
                for o in root.findall(".//order"):
                    order_numbers.add((o.findtext("orderno") or "").strip())

            count = 0
            for orderno in sorted(on for on in order_numbers if on):
                order, _ = Order.objects.get_or_create(number=orderno)
                try:
                    res = client.get_results_for_order(orderno)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"{orderno}: нет результатов ({e})"))
                    continue

                with transaction.atomic():
                    for p in res.findall(".//panel"):
                        pcode = (p.get("code") or p.findtext("code") or "").strip()
                        panel = Panel.objects.filter(code=pcode).first()
                        op, _ = OrderPanel.objects.get_or_create(order=order, panel=panel)
                        op.status = (p.findtext("status") or "").strip()
                        op.released_doctor = (p.findtext("released_doctor") or "").strip()
                        op.save()

                        for t in p.findall(".//test"):
                            tcode = (t.get("code") or t.findtext("code") or "").strip()
                            test = Test.objects.filter(code=tcode).first()
                            released = (t.findtext("released_doctor") or "").strip()

                            for a in t.findall(".//analyte"):
                                val = (a.findtext("value") or "").strip()
                                unit = (a.findtext("unit") or "").strip()
                                low = (a.findtext("low") or "").strip()
                                high = (a.findtext("high") or "").strip()
                                comment = (a.findtext("comment") or "").strip()
                                raw = (a.findtext("rawresult") or "").strip()
                                an_code = (a.get("code") or a.findtext("code") or "").strip()
                                an_name = (a.get("name") or a.findtext("name") or "").strip()

                                analyt_obj = None
                                if test:
                                    if an_code:
                                        analyt_obj = Analyte.objects.filter(test=test, code=an_code).first()
                                    if not analyt_obj and an_name:
                                        analyt_obj = Analyte.objects.filter(test=test, name__iexact=an_name).first()

                                ResultEntry.objects.get_or_create(
                                    order_panel=op,
                                    test=test,
                                    value=val,
                                    unit=unit,
                                    norm_low=low,
                                    norm_high=high,
                                    comment=comment,
                                    rawresult=raw,
                                    analyte=analyt_obj,
                                    defaults={"released_doctor": released},
                                )

                count += 1

            self.stdout.write(self.style.SUCCESS(f"Обработано заявок: {count}"))
        finally:
            client.logout()
