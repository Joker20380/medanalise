from django.core.management.base import BaseCommand
import os, re
import xml.etree.ElementTree as ET
from main.services.nacpp_client import NacppClient

OUTDIR = "nacpp_dumps"

def save(name, xml):
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"{name}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path

def sample_tags(xml, tag, limit=3):
    root = ET.fromstring(xml)
    items = root.findall(f".//{tag}")
    out = []
    for i, el in enumerate(items[:limit], 1):
        attrs = {k: v for k, v in el.attrib.items()}
        child_tags = [c.tag for c in list(el)]
        out.append((i, attrs, child_tags, ET.tostring(el, encoding="unicode")[:500]))
    return len(items), out

class Command(BaseCommand):
    help = "Проба: сохранить XML по ключевым каталогам и показать структуру первых элементов"

    def add_arguments(self, parser):
        parser.add_argument("--login", default="TESTTT")
        parser.add_argument("--password", default="1233")

    def handle(self, *args, **opts):
        c = NacppClient(opts["login"], opts["password"])
        c.login()
        try:
            catalogs = [
                ("panelscategories", []),
                ("tests", ["test", "item"]),
                ("panels", ["panel", "item"]),
                ("containertypes", ["containertype", "item"]),
                ("linkedpanels", ["link", "item"]),          # может не существовать
                ("testsrequirements", ["requirement", "item"]),  # может не существовать
                ("preanalytics", ["preanalytic", "item"]),       # может не существовать
            ]
            for cat, tags in catalogs:
                try:
                    xml = c.get_catalog(cat, categories=1 if cat == "panels" else None)
                    path = save(cat, xml)
                    self.stdout.write(self.style.SUCCESS(f"Saved {cat} -> {path}"))
                    for t in tags:
                        count, rows = sample_tags(xml, t)
                        self.stdout.write(f"  <{t}> count={count}")
                        for idx, attrs, childs, snippet in rows:
                            self.stdout.write(f"    [{idx}] attrs={attrs} childs={childs}")
                except Exception as e:
                    self.stdout.write(f"{cat}: skipped ({e})")
        finally:
            c.logout()
