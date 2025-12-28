from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from assistant.models import SearchIndex

# ===== Imports of your models =====
from lab.models import Test, Panel, Service as LabService, PanelMaterial
from main.models import Contact, News


# ---------------------------
# Utils
# ---------------------------

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    if not text:
        return ""
    # remove tags
    text = TAG_RE.sub(" ", str(text))
    text = text.replace("&nbsp;", " ")
    text = text.replace("\xa0", " ")
    text = WS_RE.sub(" ", text).strip()
    return text


def cut(text: str, n: int) -> str:
    if not text:
        return ""
    t = str(text).strip()
    return t if len(t) <= n else (t[:n].rstrip() + "…")


def safe_url(obj) -> str:
    try:
        if hasattr(obj, "get_absolute_url"):
            return obj.get_absolute_url() or ""
    except Exception:
        return ""
    return ""


def category_path(cat) -> str:
    """
    Full path for PanelCategory (parent -> child).
    """
    if not cat:
        return ""
    parts = [cat.name]
    p = getattr(cat, "parent", None)
    while p:
        parts.append(p.name)
        p = getattr(p, "parent", None)
    return " / ".join(reversed([x for x in parts if x]))


def dec_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        # avoid exponent formats
        return format(v, "f").rstrip("0").rstrip(".") if "." in format(v, "f") else format(v, "f")
    return str(v)


def ref_range(low: str, high: str) -> str:
    low = (low or "").strip()
    high = (high or "").strip()
    if low and high:
        return f"{low}–{high}"
    if low and not high:
        return f"от {low}"
    if high and not low:
        return f"до {high}"
    return ""


# ---------------------------
# Builders
# ---------------------------

def build_test_row(t: Test) -> dict:
    meta = {
        "code": t.code,
        "unit": (t.unit or "").strip(),
        "method": cut(strip_html(t.method), 80),
        "ref": ref_range(t.low, t.high),
    }

    # короткий "hint" (не простыня) — из description, но сильно режем
    # если description пустой — пусто, фронт сам скроет строку
    hint = cut(strip_html(t.description), 80)
    if hint:
        meta["hint"] = hint

    title = f"{t.name}".strip() or t.code

    search_text = " ".join([
        t.code or "",
        title,
        meta.get("unit", ""),
        meta.get("method", ""),
        meta.get("ref", ""),
        strip_html(t.description or ""),
    ]).strip()

    return {
        "kind": "test",
        "object_id": t.id,
        "title": title,
        "url": safe_url(t),
        "search_text": search_text,
        "meta": meta,
    }


def build_panel_row(p: Panel, materials_map: dict[int, list[str]], cat_map: dict[int, str]) -> dict:
    cat_path = cat_map.get(p.category_id or 0, "")
    meta = {
        "code": p.code,
        "duration": (p.duration or "").strip(),
        "category": cat_path,
    }

    mats = materials_map.get(p.id, [])
    if mats:
        meta["biomaterials"] = mats[:6]

    title = cut((p.name or "").strip() or p.code, 180)


    search_text = " ".join([
        p.code or "",
        title,
        (p.duration or ""),
        cat_path,
        " ".join(mats),
    ]).strip()

    return {
        "kind": "panel",
        "object_id": p.id,
        "title": title,
        "url": safe_url(p),
        "search_text": search_text,
        "meta": meta,
    }


def build_lab_service_row(s: LabService) -> dict:
    meta = {
        "code": s.code,
        "price": dec_to_str(s.cost),
        "currency": (s.currency or "").strip(),
        "duration": (s.duration or "").strip(),
        "panel_code": s.panel.code if s.panel_id else "",
        "panel_name": s.panel.name if s.panel_id else "",
    }

    title = cut((s.name or "").strip() or s.code, 180)

    search_text = " ".join([
        s.code or "",
        title,
        dec_to_str(s.cost),
        (s.currency or ""),
        (s.duration or ""),
        (s.comment or ""),
        meta.get("panel_code", ""),
        meta.get("panel_name", ""),
    ]).strip()

    return {
        "kind": "lab_service",
        "object_id": s.id,
        "title": title,
        "url": safe_url(s),
        "search_text": search_text,
        "meta": meta,
    }


def build_contact_row(c: Contact) -> dict:
    meta = {
        "group": getattr(c.group, "name", "") if c.group_id else "",
        "phone": (c.phone or "").strip(),
        "email": (c.email or "").strip(),
        "address": (c.address or "").strip(),
        "is_main": bool(c.is_main),
    }

    title = cut((c.name or "").strip() or "Контакт", 180)

    search_text = " ".join([
        title,
        meta["group"],
        meta["phone"],
        meta["email"],
        meta["address"],
        strip_html(c.description or ""),
    ]).strip()

    return {
        "kind": "contact",
        "object_id": c.id,
        "title": title,
        "url": safe_url(c),
        "search_text": search_text,
        "meta": meta,
    }


def build_news_row(n: News) -> dict:
    meta = {
        "category": getattr(n.cat, "name", "") if n.cat_id else "",
        "date": n.time_create.isoformat() if isinstance(n.time_create, date) else str(n.time_create) if n.time_create else "",
    }

    title = cut((n.title or "").strip() or "Новость", 180)

    # берём кусок контента без HTML
    text = strip_html(n.content or "")
    text2 = strip_html(n.content2 or "")
    text3 = strip_html(n.content3 or "")
    text4 = strip_html(n.content4 or "")
    body = " ".join([text, text2, text3, text4]).strip()

    search_text = " ".join([
        title,
        meta["category"],
        body,
    ]).strip()

    return {
        "kind": "news",
        "object_id": n.id,
        "title": title,
        "url": safe_url(n),
        "search_text": search_text,
        "meta": meta,
    }


# ---------------------------
# Command
# ---------------------------

class Command(BaseCommand):
    help = "Rebuild assistant search index (bulk, production-safe)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=1000, help="Bulk insert batch size (default: 1000).")
        parser.add_argument("--keep", action="store_true", help="Do not wipe existing index (append).")

    @transaction.atomic
    def handle(self, *args, **opts):
        batch = int(opts["batch"] or 1000)
        keep = bool(opts["keep"])

        self.stdout.write(self.style.WARNING("assistant: reindex_search started"))

        if not keep:
            SearchIndex.objects.all().delete()
            self.stdout.write("assistant: cleared SearchIndex")

        created = 0
        buf = []

        def flush():
            nonlocal created, buf
            if not buf:
                return
            SearchIndex.objects.bulk_create(buf, batch_size=batch)
            created += len(buf)
            buf = []
            self.stdout.write(f"assistant: inserted {created}")

        # -------- Tests --------
        self.stdout.write("assistant: indexing tests...")
        for t in Test.objects.all().only("id", "code", "name", "unit", "method", "description", "low", "high").iterator(chunk_size=2000):
            row = build_test_row(t)
            buf.append(SearchIndex(**row))
            if len(buf) >= batch:
                flush()
        flush()

        # -------- Panels (need category path + biomaterials) --------
        self.stdout.write("assistant: indexing panels...")
        panels = Panel.objects.select_related("category").all().only("id", "code", "name", "duration", "category_id", "category__name", "category__parent_id")

        # category path cache
        cat_ids = set(p.category_id for p in panels if p.category_id)
        cat_map = {}
        if cat_ids:
            # we already have category via select_related for direct, but for full path we need parents chain;
            # easiest: compute lazily via object category_path() using loaded relations where possible.
            # We'll do a second fetch of categories with parents preloaded is tricky; instead compute per panel.
            pass

        # material map: panel_id -> list of biomaterial names
        materials_map = {}
        for pm in PanelMaterial.objects.select_related("biomaterial").all().only("panel_id", "biomaterial__name").iterator(chunk_size=4000):
            materials_map.setdefault(pm.panel_id, []).append((pm.biomaterial.name or "").strip())

        # build category paths per panel (works because category.parent is accessible if loaded; if not, path will be partial but ok)
        for p in panels.iterator(chunk_size=2000):
            cat_map[p.category_id or 0] = category_path(p.category) if p.category_id else ""

            row = build_panel_row(p, materials_map=materials_map, cat_map=cat_map)
            buf.append(SearchIndex(**row))
            if len(buf) >= batch:
                flush()
        flush()

        # -------- Lab services --------
        self.stdout.write("assistant: indexing lab services...")
        qs = LabService.objects.select_related("panel").all().only("id", "code", "name", "cost", "currency", "duration", "comment", "panel_id", "panel__code", "panel__name")
        for s in qs.iterator(chunk_size=2000):
            row = build_lab_service_row(s)
            buf.append(SearchIndex(**row))
            if len(buf) >= batch:
                flush()
        flush()

        # -------- Contacts --------
        self.stdout.write("assistant: indexing contacts...")
        qs = Contact.objects.select_related("group").all().only("id", "name", "phone", "email", "address", "description", "group_id", "group__name", "is_main")
        for c in qs.iterator(chunk_size=2000):
            row = build_contact_row(c)
            buf.append(SearchIndex(**row))
            if len(buf) >= batch:
                flush()
        flush()

        # -------- News --------
        self.stdout.write("assistant: indexing news...")
        qs = News.objects.select_related("cat").all().only(
            "id", "title", "slug", "time_create", "cat_id", "cat__name",
            "content", "content2", "content3", "content4",
        )
        for n in qs.iterator(chunk_size=500):
            row = build_news_row(n)
            buf.append(SearchIndex(**row))
            if len(buf) >= batch:
                flush()
        flush()

        self.stdout.write(self.style.SUCCESS(f"assistant: reindex_search done. total={created}"))
