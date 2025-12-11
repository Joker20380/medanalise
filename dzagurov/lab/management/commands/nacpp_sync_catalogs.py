# lab/management/commands/<твоя_команда>.py
from django.core.management.base import BaseCommand
from django.db import transaction
from lab.models import (
    Biomaterial, ContainerType, Test, Analyte, Panel, PanelTest, PanelMaterial,
    TestRequirement, PanelLinked, PanelCategory, PanelPreanalytic  # ← добавили
)
from lab.nacpp_client import NacppClient


class Command(BaseCommand):
    help = "Синхронизация справочников (контейнеры, тесты, аналиты, категории панелей, панели, материалы, преаналитика, требования, связи)."

    def handle(self, *args, **opts):
        client = NacppClient()
        try:
            with transaction.atomic():
                self.stdout.write("→ Синхронизация контейнеров…")
                self.sync_containers(client)

                self.stdout.write("→ Синхронизация тестов и аналитов…")
                self.sync_tests(client)

                # ВАЖНО: сначала категории, затем панели (чтобы FK нашёлся)
                self.stdout.write("→ Синхронизация категорий панелей…")
                self.sync_panel_categories(client)

                self.stdout.write("→ Синхронизация панелей и материалов…")
                self.sync_panels(client)

                # Новое: тянем преаналитику, когда панели уже заведены
                self.stdout.write("→ Синхронизация преаналитики…")
                self.sync_preanalytics(client)

                self.stdout.write("→ Синхронизация требований…")
                self.sync_requirements(client)

                self.stdout.write("→ Синхронизация связанных панелей…")
                self.sync_linked(client)

            self.stdout.write(self.style.SUCCESS("✅ Справочники синхронизированы"))
        finally:
            client.logout()

    # ------------------------------------------------------------------------
    # helpers

    @staticmethod
    def _tx(el, name, default=""):
        n = el.find(name)
        return (n.text or "").strip() if n is not None and n.text else default

    @staticmethod
    def _attr(el, name, default=""):
        v = el.get(name)
        return (v or "").strip() if v is not None else default

    # ------------------------------------------------------------------------
    # containers

    def sync_containers(self, client: NacppClient):
        root = client.get_container_types()
        for ct in root.findall(".//containertype"):
            code = self._attr(ct, "code")
            name = (ct.text or "").strip()
            color = self._attr(ct, "color")
            ContainerType.objects.update_or_create(
                code=code, defaults={"name": name, "color": color}
            )

    # ------------------------------------------------------------------------
    # tests + analytes

    def sync_tests(self, client: NacppClient):
        tests_root = client.get_catalog("tests")

        def iter_analytes(test_el):
            return test_el.findall("./analytes/analyte")

        for t in tests_root.findall(".//test"):
            tcode = self._attr(t, "code") or self._tx(t, "code")
            if not tcode:
                continue
            tname = self._tx(t, "name", tcode)
            unit = self._tx(t, "unit", "")
            method = self._tx(t, "method", "")
            desc = self._tx(t, "description", "")
            low = self._tx(t, "low", "")
            high = self._tx(t, "high", "")

            test, _ = Test.objects.update_or_create(
                code=tcode,
                defaults={
                    "name": tname,
                    "unit": unit,
                    "method": method,
                    "description": desc,
                    "low": low,
                    "high": high,
                },
            )

            idx = 0
            for a in iter_analytes(t):
                idx += 1
                acode = self._attr(a, "code") or self._tx(a, "code", "")
                aname = self._attr(a, "name") or self._tx(a, "name", "")
                unit_a = self._attr(a, "unit") or self._tx(a, "unit", unit)
                nlow = self._attr(a, "low") or self._tx(a, "low", "")
                nhigh = self._attr(a, "high") or self._tx(a, "high", "")

                if not acode:
                    key = aname or f"#{idx}"
                    acode = f"{tcode}::{key}"

                Analyte.objects.update_or_create(
                    test=test,
                    code=acode,
                    defaults={
                        "name": aname or acode,
                        "unit": unit_a,
                        "norm_low": nlow,
                        "norm_high": nhigh,
                    },
                )

    # ------------------------------------------------------------------------
    # panel categories (дерево)

    def sync_panel_categories(self, client: NacppClient):
        root = client.get_panel_categories()

        def to_int(s):
            try:
                return int(s)
            except Exception:
                return None

        created = 0
        updated = 0

        def walk(cat_el, parent_obj=None):
            nonlocal created, updated
            if cat_el.tag != "category":
                return
            code = self._attr(cat_el, "code")
            sorter = to_int(self._attr(cat_el, "sorter"))
            name = self._tx(cat_el, "name", code)

            obj, is_created = PanelCategory.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "sorter": sorter,
                    "parent": parent_obj,
                },
            )
            created += int(is_created)
            updated += int(not is_created)

            ch_root = cat_el.find("./categories")
            if ch_root is not None:
                for ch in ch_root.findall("./category"):
                    walk(ch, parent_obj=obj)

        for top in root.findall("./category"):
            walk(top, parent_obj=None)

        self.stdout.write(self.style.SUCCESS(
            f"Категории панелей: created={created}, updated={updated}"
        ))

    # ------------------------------------------------------------------------
    # panels + materials + tests + FK category

    def sync_panels(self, client: NacppClient):
        panels_root = client.get_panels(include_categories=True)

        for p in panels_root.findall(".//panel"):
            pcode = self._attr(p, "code") or self._tx(p, "code")
            if not pcode:
                continue

            pname = self._tx(p, "name", pcode)
            duration = self._tx(p, "duration", "")

            category_code = self._attr(p, "category")

            panel, _ = Panel.objects.update_or_create(
                code=pcode,
                defaults={
                    "name": pname,
                    "duration": duration,
                    "category_code": category_code,
                },
            )

            if category_code:
                cat = PanelCategory.objects.filter(code=category_code).first()
                if cat and panel.category_id != cat.id:
                    panel.category = cat
                    panel.save(update_fields=["category"])

            for ctn in p.findall(".//containers/container"):
                bio_code = self._attr(ctn, "biomaterial")
                cont_code = self._attr(ctn, "containertype")
                mat_name = self._attr(ctn, "matdakks")

                bio = None
                if bio_code:
                    bio, _ = Biomaterial.objects.update_or_create(
                        code=bio_code, defaults={"name": mat_name or bio_code}
                    )

                cont = (
                    ContainerType.objects.filter(code=cont_code).first()
                    if cont_code else None
                )
                if bio:
                    PanelMaterial.objects.get_or_create(
                        panel=panel, biomaterial=bio, container_type=cont
                    )

                for tnode in ctn.findall("./test"):
                    tcode = self._attr(tnode, "code") or self._tx(tnode, "code")
                    if not tcode:
                        continue
                    test = Test.objects.filter(code=tcode).first()
                    if test:
                        PanelTest.objects.get_or_create(panel=panel, test=test)

    # ------------------------------------------------------------------------
    # preanalytics  ← НОВЫЙ РАЗДЕЛ

    def sync_preanalytics(self, client: NacppClient):
        """
        Тянем catalog=preanalytics и апсертим OneToOne PanelPreanalytic.
        Формат (по их доке):
          <preanalytics>
            <preanalytic>
              <panel_code>10.000</panel_code>
              <training>...</training>
              <centrifugation>...</centrifugation>
              <storage_transportation>...</storage_transportation>
              <note>...</note>
              <min_count>2 мл.</min_count>
            </preanalytic>
          </preanalytics>
        """
        # поддержим оба варианта клиента: явный метод и общий catalog
        try:
            root = client.get_preanalytics()
        except AttributeError:
            root = client.get_catalog("preanalytics")

        created = 0
        updated = 0
        skipped = 0

        for node in root.findall(".//preanalytic"):
            pcode = self._tx(node, "panel_code", "")
            if not pcode:
                continue

            panel = Panel.objects.filter(code=pcode).first()
            if not panel:
                skipped += 1
                continue

            defaults = {
                "training": self._tx(node, "training", ""),
                "centrifugation": self._tx(node, "centrifugation", ""),
                "storage_transportation": self._tx(node, "storage_transportation", ""),
                "note": self._tx(node, "note", ""),
                "min_count": self._tx(node, "min_count", ""),
            }

            obj, is_created = PanelPreanalytic.objects.update_or_create(
                panel=panel, defaults=defaults
            )
            created += int(is_created)
            updated += int(not is_created)

        self.stdout.write(self.style.SUCCESS(
            f"Преаналитика: created={created}, updated={updated}, skipped(no panel)={skipped}"
        ))

    # ------------------------------------------------------------------------
    # requirements

    def sync_requirements(self, client: NacppClient):
        req_root = client.get_tests_requirements()
        for f in req_root.findall(".//field"):
            fcode = self._attr(f, "code") or self._tx(f, "code")
            name = self._tx(f, "name", fcode)
            desc = self._tx(f, "description", "")
            req, _ = TestRequirement.objects.update_or_create(
                field_code=fcode, defaults={"name": name, "description": desc}
            )
            req.dependent_tests.clear()
            for t in f.findall(".//dependent_tests/test"):
                tcode = (t.text or "").strip()
                test = Test.objects.filter(code=tcode).first()
                if test:
                    req.dependent_tests.add(test)

    # ------------------------------------------------------------------------
    # linked panels

    def sync_linked(self, client: NacppClient):
        try:
            lp = client.get_linked_panels()
            for rel in lp.findall(".//relation"):
                main = (rel.findtext("main") or "").strip()
                if not main:
                    continue
                main_panel = Panel.objects.filter(code=main).first()
                if not main_panel:
                    continue
                for ex in rel.findall(".//extra"):
                    ex_code = (ex.text or "").strip()
                    extra_panel = Panel.objects.filter(code=ex_code).first()
                    if extra_panel:
                        PanelLinked.objects.get_or_create(
                            main_panel=main_panel, extra_panel=extra_panel
                        )
        except Exception:
            # на некоторых стендах нет справочника связей — ок, молча пропускаем
            pass
