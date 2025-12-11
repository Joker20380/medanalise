from django.core.management.base import BaseCommand
from django.db import transaction
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from main.services.nacpp_client import NacppClient
from main.models import (
    SyncStamp, LabCategory, Biomaterial, ContainerType,
    LabTest, LabPanel, PanelItem, PanelCategory,
    TestCategory, TestRequirement, Preanalytic
)


# ----------------- helpers -----------------

PRICE_KEYS = ("price", "cost", "tariff", "amount", "sum", "value", "price_rub")

# ключи для поиска кода биоматериала в тесте/аналитах
BIOMATERIAL_KEYS = (
    "biomaterial", "biomaterial_code", "material", "material_code",
    "mat", "bio", "biomat", "biomaterialid", "biomaterial_id", "materialid", "material_id"
)
# ключи для поиска кода типа контейнера в тесте
CONTAINERTYPE_KEYS = (
    "containertype", "container_type", "container", "container_code",
    "containercode", "ctype", "tube", "vacutainer", "containertypeid", "containertype_id"
)


def _val_any(el, keys, default=""):
    """ Вернуть значение по первому совпавшему ключу из атрибута или дочернего тега. """
    for k in keys:
        if k in el.attrib and (el.attrib[k] or "").strip():
            return el.attrib[k].strip()
        node = el.find(k)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return default


def _to_decimal(v):
    if not v:
        return None
    v = str(v).replace(",", ".").strip()
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError):
        return None


def _find_price(el):
    """ Универсально пытаемся достать цену из текущего узла и его потомков. """
    for k, v in el.attrib.items():
        if any(p in k.lower() for p in PRICE_KEYS):
            dec = _to_decimal(v)
            if dec is not None:
                return dec
    for child in list(el):
        tag = child.tag.lower()
        if any(p == tag or p in tag for p in PRICE_KEYS):
            if (child.text or "").strip():
                dec = _to_decimal(child.text)
                if dec is not None:
                    return dec
        for k, v in child.attrib.items():
            if any(p in k.lower() for p in PRICE_KEYS):
                dec = _to_decimal(v)
                if dec is not None:
                    return dec
    for node in el.iter():
        if node is el:
            continue
        tag = node.tag.lower()
        if any(p in tag for p in PRICE_KEYS):
            if (node.text or "").strip():
                dec = _to_decimal(node.text)
                if dec is not None:
                    return dec
            for k, v in node.attrib.items():
                if any(p in k.lower() for p in PRICE_KEYS):
                    dec = _to_decimal(v)
                    if dec is not None:
                        return dec
    return None


def _find_code(el, keys):
    """ Ищем значение кода (строку) в атрибутах/тексте дочерних узлов/глубоко по дереву. """
    for k in keys:
        for ak, av in el.attrib.items():
            if ak.lower() == k.lower() and (av or "").strip():
                return av.strip()
    for k in keys:
        node = el.find(k)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    for node in el.iter():
        tag = node.tag.lower()
        for k in keys:
            if tag == k.lower() or k.lower() in tag:
                val = (node.text or "").strip()
                if val:
                    return val
                for ak, av in node.attrib.items():
                    if ak.lower() == k.lower() or k.lower() in ak.lower():
                        if (av or "").strip():
                            return av.strip()
    return ""


def _resolve_biomaterial(code_or_name: str):
    if not code_or_name:
        return None
    val = code_or_name.strip()
    bm = Biomaterial.objects.filter(external_id=val).first()
    if bm:
        return bm
    return Biomaterial.objects.filter(name=val).first()


def _resolve_containertype(code_or_name: str):
    if not code_or_name:
        return None
    val = code_or_name.strip()
    ct = ContainerType.objects.filter(external_id=val).first()
    if ct:
        return ct
    return ContainerType.objects.filter(name=val).first()


def _extract_biomaterial_from_test(test_node):
    """
    Частый кейс: <test><analytes><analyte ... material='SOMECODE' /></analytes></test>
    Берём первый валидный материал из аналитов, если есть.
    """
    # прямой поиск по тесту
    code = _find_code(test_node, BIOMATERIAL_KEYS)
    if code:
        return code

    # поиск внутри analytes/analyte
    analytes = test_node.find("analytes")
    if analytes is not None:
        for an in analytes.findall(".//analyte"):
            # сначала атрибуты
            for k, v in an.attrib.items():
                if any(k.lower() == key or key in k.lower() for key in BIOMATERIAL_KEYS):
                    if (v or "").strip():
                        return v.strip()
            # затем вложенные теги
            val = _find_code(an, BIOMATERIAL_KEYS)
            if val:
                return val
    return ""


def _extract_containertype_from_test(test_node):
    """
    Встречается редко, но поддержим:
    <test>...<containers><containertype code="..."/></containers></test>
    Или просто атрибуты/теги с ключами CONTAINERTYPE_KEYS.
    """
    # прямой поиск по тесту
    code = _find_code(test_node, CONTAINERTYPE_KEYS)
    if code:
        return code

    # containers внутри теста
    containers = test_node.find("containers")
    if containers is not None:
        # самый явный кейс
        ct = containers.find(".//containertype")
        if ct is not None:
            c = ct.attrib.get("code") or ct.attrib.get("id") or (ct.text or "").strip()
            if c:
                return c.strip()
        # запасной путь — любой тег/атрибут, где встречается ключ
        for node in containers.iter():
            for k, v in node.attrib.items():
                if any(key in k.lower() for key in CONTAINERTYPE_KEYS) and (v or "").strip():
                    return v.strip()
            if any(key in node.tag.lower() for key in CONTAINERTYPE_KEYS):
                if (node.text or "").strip():
                    return node.text.strip()
    return ""


# ----------------- command -----------------

class Command(BaseCommand):
    help = "Импорт каталогов NACPP: категории, биоматериалы, тесты (линки на биоматериал/контейнер), панели, контейнеры, преаналитика."

    def add_arguments(self, parser):
        parser.add_argument("--login", default="TESTTT")
        parser.add_argument("--password", default="1233")
        parser.add_argument("--base", default=None)

    def handle(self, *args, **opts):
        client = NacppClient(opts["login"], opts["password"], base=opts["base"])
        client.login()
        self.stdout.write(self.style.SUCCESS("Logged in."))

        # ---------- CATEGORIES ----------
        self.stdout.write("Импорт категорий...")
        xml = client.get_catalog("panelscategories")
        root = ET.fromstring(xml)
        with transaction.atomic():
            for c in root.findall(".//category"):
                ext_id = _val_any(c, ["id", "code"]) or _val_any(c, ["name"])
                if not ext_id:
                    continue
                name = _val_any(c, ["name"]) or ext_id
                parent_id = _val_any(c, ["parent"])
                LabCategory.objects.update_or_create(
                    external_id=ext_id[:128],
                    defaults={
                        "name": name,
                        "parent_external_id": parent_id,
                        "raw_xml": ET.tostring(c, encoding="unicode"),
                    },
                )
            SyncStamp.objects.update_or_create(catalog="panelscategories")

        # ---------- BIOMATERIALS ----------
        self.stdout.write("Импорт биоматериалов...")
        biomaterials_loaded = False
        for dict_name in ("bio", "biomaterials"):
            try:
                xml = client.get_catalog(dict_name)
                root = ET.fromstring(xml)
                with transaction.atomic():
                    nodes = root.findall(".//biomaterial") or root.findall(".//item")
                    for m in nodes:
                        ext_id = _val_any(m, ["id", "code"]) or _val_any(m, ["name"])
                        if not ext_id:
                            continue
                        name = _val_any(m, ["name"]) or ext_id
                        Biomaterial.objects.update_or_create(
                            external_id=ext_id[:128],
                            defaults={
                                "name": name,
                                "raw_xml": ET.tostring(m, encoding="unicode"),
                            },
                        )
                    SyncStamp.objects.update_or_create(catalog="biomaterials")
                biomaterials_loaded = True
                break
            except Exception:
                self.stdout.write(f"{dict_name}: skipped (нет каталога/ошибка).")
        if not biomaterials_loaded:
            self.stdout.write("biomaterials: не удалось загрузить (каталог отсутствует).")

        # ---------- TESTS ----------
        self.stdout.write("Импорт тестов...")
        xml = client.get_catalog("tests")
        root = ET.fromstring(xml)
        linked_bm = 0
        linked_ct = 0
        with transaction.atomic():
            for t in root.findall(".//test"):
                code = _val_any(t, ["code"])
                if not code:
                    continue
                name = _val_any(t, ["name"]) or code
                price = _find_price(t)

                # biomaterial: из analytes/analyte или прямо из test
                bm_code = _extract_biomaterial_from_test(t)
                bm = _resolve_biomaterial(bm_code) if bm_code else None
                if bm:
                    linked_bm += 1

                # container type: если вдруг есть внутри test
                ct_code = _extract_containertype_from_test(t)
                ct = _resolve_containertype(ct_code) if ct_code else None
                if ct:
                    linked_ct += 1

                LabTest.objects.update_or_create(
                    external_id=code[:128],
                    defaults={
                        "code": code[:128],
                        "name": name,
                        "short_name": "",
                        "price": price,
                        "biomaterial": bm,
                        "container_type": ct,
                        "raw_xml": ET.tostring(t, encoding="unicode"),
                    },
                )
            SyncStamp.objects.update_or_create(catalog="tests")

        # ---------- PANELS ----------
        self.stdout.write("Импорт панелей...")
        xml = client.get_catalog("panels")
        root = ET.fromstring(xml)
        with transaction.atomic():
            for p in root.findall(".//panel"):
                code = _val_any(p, ["code"])
                if not code:
                    continue
                name = _val_any(p, ["name"]) or code
                cat_id = _val_any(p, ["category"])
                price = _find_price(p)

                panel, _ = LabPanel.objects.update_or_create(
                    external_id=code[:128],
                    defaults={
                        "code": code[:128],
                        "name": name,
                        "price": price,
                        "raw_xml": ET.tostring(p, encoding="unicode"),
                    },
                )
                if cat_id:
                    cat = LabCategory.objects.filter(external_id=cat_id).first()
                    if cat:
                        PanelCategory.objects.get_or_create(panel=panel, category=cat)
            SyncStamp.objects.update_or_create(catalog="panels")

        # ---------- CONTAINER TYPES ----------
        self.stdout.write("Импорт типов контейнеров...")
        xml = client.get_catalog("containertypes")
        root = ET.fromstring(xml)
        with transaction.atomic():
            for ct in root.findall(".//containertype"):
                code = _val_any(ct, ["code"])
                if not code:
                    continue
                name = code
                ContainerType.objects.update_or_create(
                    external_id=code[:128],
                    defaults={
                        "name": name,
                        "raw_xml": ET.tostring(ct, encoding="unicode"),
                    },
                )
            SyncStamp.objects.update_or_create(catalog="containertypes")

        # ---------- PREANALYTICS ----------
        self.stdout.write("Импорт преаналитики...")
        xml = client.get_catalog("preanalytics")
        root = ET.fromstring(xml)
        with transaction.atomic():
            for node in root.findall(".//preanalytic"):
                panel_code = _val_any(node, ["panel_code"])
                if not panel_code:
                    continue
                Preanalytic.objects.update_or_create(
                    target_type="panel",
                    target_external_id=panel_code[:128],
                    defaults={
                        "raw_xml": ET.tostring(node, encoding="unicode"),
                    },
                )
            SyncStamp.objects.update_or_create(catalog="preanalytics")

        # ---------- финальная статистика ----------
        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write(
            "Stats: "
            f"categories={LabCategory.objects.count()}, "
            f"biomaterials={Biomaterial.objects.count()}, "
            f"tests={LabTest.objects.count()}, "
            f"panels={LabPanel.objects.count()}, "
            f"containertypes={ContainerType.objects.count()}, "
            f"preanalytics={Preanalytic.objects.count()}, "
            f"panel_cats={PanelCategory.objects.count()}, "
            f"tests_linked_biomaterial={linked_bm}, "
            f"tests_linked_containertype={linked_ct}"
        )

        client.logout()
