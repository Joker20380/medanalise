# lab/admin.py
from django.contrib import admin, messages
from django.utils.html import format_html
from django.db.models import Count, Prefetch  # <<< Prefetch
from decimal import Decimal, InvalidOperation
import re
import os
from pathlib import Path
from django.conf import settings

from .models import (
    Biomaterial, ContainerType, Test, Analyte, Panel, PanelCategory, PanelTest, PanelMaterial,
    PanelLinked, TestRequirement, Localization, Order, OrderPanel, ResultEntry, Service, PanelPreanalytic
)
from .nacpp_client import NacppClient


# ==========================
# Admin actions
# ==========================

@admin.action(description="Обновить результаты выбранных заявок")
def admin_refresh_results(modeladmin, request, queryset):
    client = NacppClient()
    updated = 0

    for order in queryset:
        try:
            res = client.get_results_for_order(order.number)
        except Exception as e:
            messages.warning(request, f"{order.number}: нет данных ({e})")
            continue

        changed = 0

        for p in res.findall(".//panel"):
            pcode = (p.get("code") or (p.findtext("code") or "")).strip()
            panel = Panel.objects.filter(code=pcode).first()
            op, _ = OrderPanel.objects.get_or_create(order=order, panel=panel)
            op.status = (p.findtext("status") or "").strip()
            op.released_doctor = (p.findtext("released_doctor") or "").strip()
            op.save()

            for t in p.findall(".//test"):
                tcode = (t.get("code") or (t.findtext("code") or "")).strip()
                test = Test.objects.filter(code=tcode).first()
                released = (t.findtext("released_doctor") or "").strip()

                for a in t.findall(".//analyte"):
                    an_code = (a.get("code") or (a.findtext("code") or "")).strip()
                    an_name = (a.get("name") or (a.findtext("name") or "")).strip()
                    val = (a.findtext("value") or "").strip()
                    unit = (a.findtext("unit") or "").strip()
                    low = (a.findtext("low") or "").strip()
                    high = (a.findtext("high") or "").strip()
                    comment = (a.findtext("comment") or "").strip()
                    raw = (a.findtext("rawresult") or "").strip()

                    analyt = None
                    if test:
                        if an_code:
                            analyt = Analyte.objects.filter(test=test, code=an_code).first()
                        if not analyt and an_name:
                            analyt = Analyte.objects.filter(test=test, name__iexact=an_name).first()

                    obj, created = ResultEntry.objects.get_or_create(
                        order_panel=op,
                        test=test,
                        value=val,
                        unit=unit,
                        norm_low=low,
                        norm_high=high,
                        comment=comment,
                        rawresult=raw,
                        analyte=analyt,
                        defaults={"released_doctor": released},
                    )
                    changed += int(created)

        updated += int(changed > 0)

    client.logout()
    messages.success(request, f"Обновлено заявок: {updated}")


@admin.action(description="Скачать печатки (PDF) для выбранных заявок")
def admin_fetch_reports(modeladmin, request, queryset):
    client = NacppClient()
    saved = 0
    base_dir = Path(settings.MEDIA_ROOT) / settings.NACPP_REPORTS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    for order in queryset:
        try:
            meta = client.get_report_pdf_bundle(order.number, with_logo=True)
        except Exception as e:
            messages.warning(request, f"{order.number}: ошибка запроса печаток ({e})")
            continue

        items = (meta.get("files") or meta.get("reports") or [])
        order_dir = base_dir / order.number
        order_dir.mkdir(parents=True, exist_ok=True)

        for f in items:
            url = f.get("url") or f.get("href")
            name = f.get("name") or os.path.basename(url or "report.pdf")
            if not url:
                continue
            try:
                r = client.s.get(url, timeout=getattr(settings, "NACPP_HTTP_TIMEOUT", 30))
                r.raise_for_status()
                (order_dir / name).write_bytes(r.content)
                saved += 1
            except Exception as e:
                messages.warning(request, f"{order.number}: не сохранил {name} ({e})")

    client.logout()
    messages.success(request, f"Сохранено PDF: {saved}")


# ==========================
# Inlines
# ==========================

class AnalyteInline(admin.TabularInline):
    model = Analyte
    extra = 0
    fields = ("code", "name", "unit", "norm_low", "norm_high")
    show_change_link = True


class PanelTestInline(admin.TabularInline):
    model = PanelTest
    extra = 0
    autocomplete_fields = ("test",)
    show_change_link = True


class PanelMaterialInline(admin.TabularInline):
    model = PanelMaterial
    extra = 0
    autocomplete_fields = ("biomaterial", "container_type")
    show_change_link = True


class OrderPanelInline(admin.TabularInline):
    model = OrderPanel
    extra = 0
    autocomplete_fields = ("panel",)
    show_change_link = True


class ResultEntryInline(admin.TabularInline):
    model = ResultEntry
    extra = 0
    autocomplete_fields = ("test", "analyte")
    fields = ("test", "analyte", "value", "unit", "norm_low", "norm_high")
    show_change_link = True


# ==========================
# List filters (UX)
# ==========================

class PanelByBiomaterialFilter(admin.SimpleListFilter):
    title = "Биоматериал"
    parameter_name = "biomaterial"

    def lookups(self, request, model_admin):
        qs = Biomaterial.objects.order_by("name").values_list("id", "name")[:200]
        return [(str(i), (n or "")[:60]) for i, n in qs]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(panel_materials__biomaterial_id=val).distinct()
        return queryset


class PanelHasLinkedFilter(admin.SimpleListFilter):
    title = "Связанные панели"
    parameter_name = "has_linked"

    def lookups(self, request, model_admin):
        return (("yes", "Есть"), ("no", "Нет"))

    def queryset(self, request, queryset):
        v = self.value()
        if v == "yes":
            return queryset.filter(linked_children__isnull=False).distinct()
        if v == "no":
            return queryset.filter(linked_children__isnull=True)
        return queryset


# ==========================
# Model admins
# ==========================

@admin.register(Biomaterial)
class BiomaterialAdmin(admin.ModelAdmin):
    list_display = ("code", "short_name", "barcodeinfo_short")
    search_fields = ("code", "name", "barcodeinfo")
    ordering = ("code",)
    list_per_page = 50
    save_on_top = True

    def short_name(self, obj):
        return (obj.name or "")[:80]
    short_name.short_description = "Название"

    def barcodeinfo_short(self, obj):
        return (obj.barcodeinfo or "")[:60]
    barcodeinfo_short.short_description = "Barcode info"


@admin.register(ContainerType)
class ContainerTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "short_name", "color_swatch")
    search_fields = ("code", "name", "color")
    ordering = ("code",)
    list_per_page = 50
    save_on_top = True

    def short_name(self, obj):
        return (obj.name or "")[:80]
    short_name.short_description = "Название"

    def color_swatch(self, obj):
        color = (obj.color or "").strip() or "#cccccc"
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;border:1px solid #999;background:{}"></span> {}',
            color, color
        )
    color_swatch.short_description = "Цвет"


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("code", "name_short", "unit", "method_short")
    search_fields = ("code", "name", "unit", "method", "description", "analytes__name")
    ordering = ("code",)
    inlines = (AnalyteInline,)
    list_filter = ("unit",)
    list_per_page = 50
    save_on_top = True

    def name_short(self, obj):
        return (obj.name or "")[:100]
    name_short.short_description = "Название"

    def method_short(self, obj):
        return (obj.method or "")[:60]
    method_short.short_description = "Метод"


@admin.register(PanelCategory)
class PanelCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "sorter")
    list_filter = ("parent",)
    search_fields = ("code", "name")


@admin.register(PanelTest)
class PanelTestAdmin(admin.ModelAdmin):
    list_display = ("panel", "test")
    autocomplete_fields = ("panel", "test")
    search_fields = ("panel__code", "panel__name", "test__code", "test__name")
    ordering = ("panel__code", "test__code")
    list_select_related = ("panel", "test")
    list_per_page = 100
    save_on_top = True


@admin.register(PanelMaterial)
class PanelMaterialAdmin(admin.ModelAdmin):
    list_display = ("panel", "biomaterial", "container_type")
    autocomplete_fields = ("panel", "biomaterial", "container_type")
    search_fields = ("panel__code", "panel__name", "biomaterial__code", "biomaterial__name", "container_type__code", "container_type__name")
    list_select_related = ("panel", "biomaterial", "container_type")
    ordering = ("panel__code",)
    list_per_page = 100
    save_on_top = True


@admin.register(PanelLinked)
class PanelLinkedAdmin(admin.ModelAdmin):
    list_display = ("main_panel", "extra_panel")
    autocomplete_fields = ("main_panel", "extra_panel")
    search_fields = ("main_panel__code", "main_panel__name", "extra_panel__code", "extra_panel__name")
    list_select_related = ("main_panel", "extra_panel")
    ordering = ("main_panel__code",)
    list_per_page = 100
    save_on_top = True


@admin.register(TestRequirement)
class TestRequirementAdmin(admin.ModelAdmin):
    list_display = ("field_code", "name_short")
    search_fields = ("field_code", "name", "description", "dependent_tests__code", "dependent_tests__name")
    filter_horizontal = ("dependent_tests",)
    ordering = ("field_code",)
    list_per_page = 50
    save_on_top = True

    def name_short(self, obj):
        return (obj.name or "")[:100]
    name_short.short_description = "Название"


@admin.register(Localization)
class LocalizationAdmin(admin.ModelAdmin):
    list_display = ("panel", "external_id")
    autocomplete_fields = ("panel",)
    search_fields = ("panel__code", "panel__name", "external_id")
    ordering = ("panel__code",)
    list_select_related = ("panel",)
    list_per_page = 100
    save_on_top = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "created_at", "status_badge", "patient_short", "panels_qty", "results_qty")
    search_fields = ("number", "status", "patient_fio", "panels__panel__code", "panels__panel__name")
    list_filter = ("status",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = (OrderPanelInline,)
    list_per_page = 50
    actions = (admin_refresh_results, admin_fetch_reports)
    save_on_top = True

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _panels_count=Count("panels", distinct=True),
            _results_count=Count("panels__results", distinct=True),
        ).only("id", "number", "created_at", "status", "patient_fio")

    def patient_short(self, obj):
        return (obj.patient_fio or "")[:80]
    patient_short.short_description = "Пациент"

    def panels_qty(self, obj):
        return getattr(obj, "_panels_count", 0)
    panels_qty.short_description = "Панелей"

    def results_qty(self, obj):
        return getattr(obj, "_results_count", 0)
    results_qty.short_description = "Результатов"

    def status_badge(self, obj):
        s = (obj.status or "").upper()
        color = {
            "OK": "#0a7d0a",
            "DONE": "#0a7d0a",
            "READY": "#0a7d0a",
            "ERR": "#b00020",
            "CANCEL": "#b00020",
        }.get(s, "#444")
        return format_html(
            '<span style="padding:2px 6px;border-radius:10px;background:{};color:#fff">{}</span>',
            color, s or "—"
        )
    status_badge.short_description = "Статус"


def _parse_decimal(s: str):
    s = (s or "").strip().replace(",", ".")
    s = re.sub(r"[^\d\.\-eE]+", "", s)
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


@admin.register(OrderPanel)
class OrderPanelAdmin(admin.ModelAdmin):
    list_display = ("order", "panel", "status", "released_doctor")
    autocomplete_fields = ("order", "panel")
    search_fields = ("order__number", "panel__code", "panel__name", "status", "released_doctor")
    list_filter = ("status",)
    ordering = ("-order__created_at", "panel__code")
    list_select_related = ("order", "panel")
    list_per_page = 100
    save_on_top = True



@admin.register(ResultEntry)
class ResultEntryAdmin(admin.ModelAdmin):
    list_display = ("order_link", "panel_code", "test_code", "analyte_code", "value_colored", "unit", "ref_range")
    autocomplete_fields = ("order_panel", "test", "analyte")
    search_fields = (
        "order_panel__order__number", "order_panel__panel__code",
        "test__code", "test__name", "analyte__code", "analyte__name",
        "value", "comment",
    )
    ordering = ("-order_panel__order__created_at", "order_panel__panel__code", "test__code")
    list_select_related = ("order_panel__order", "order_panel__panel", "test", "analyte")
    list_per_page = 100
    save_on_top = True

    def order_link(self, obj):
        return obj.order_panel.order.number if obj.order_panel_id else ""
    order_link.short_description = "Заявка"

    def panel_code(self, obj):
        return obj.order_panel.panel.code if obj.order_panel_id else ""
    panel_code.short_description = "Панель"

    def test_code(self, obj):
        return obj.test.code if obj.test_id else ""
    test_code.short_description = "Тест"

    def analyte_code(self, obj):
        return obj.analyte.code if obj.analyte_id else ""
    analyte_code.short_description = "Аналит"

    def ref_range(self, obj):
        low = obj.norm_low or ""
        high = obj.norm_high or ""
        if not (low or high):
            return "—"
        return f"{low} … {high}"
    ref_range.short_description = "Реф. интервал"

    def value_colored(self, obj):
        v = _parse_decimal(obj.value)
        lo = _parse_decimal(obj.norm_low)
        hi = _parse_decimal(obj.norm_high)
        if v is None or (lo is None and hi is None):
            return (obj.value or "")[:60]
        bad = (lo is not None and v < lo) or (hi is not None and v > hi)
        if bad:
            return format_html('<b style="color:#b00020">{}</b>', (obj.value or "")[:60])
        return (obj.value or "")[:60]
    value_colored.short_description = "Значение"


@admin.register(Analyte)
class AnalyteAdmin(admin.ModelAdmin):
    list_display = ("code", "name_short", "test_code", "unit", "ref_range")
    search_fields = ("code", "name", "test__code", "test__name")
    autocomplete_fields = ("test",)
    list_select_related = ("test",)
    ordering = ("test__code", "code")
    list_per_page = 50
    save_on_top = True

    def name_short(self, obj):
        return (obj.name or "")[:80]
    name_short.short_description = "Название"

    def test_code(self, obj):
        return obj.test.code if obj.test_id else ""
    test_code.short_description = "Тест"

    def ref_range(self, obj):
        if obj.norm_low or obj.norm_high:
            return f"{obj.norm_low or ''} … {obj.norm_high or ''}"
        return "—"
    ref_range.short_description = "Реф. интервал"


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("code", "name_short", "cost", "currency", "duration", "panel")
    search_fields = ("code", "name", "panel__name", "panel__code")
    autocomplete_fields = ("panel",)
    ordering = ("code",)
    list_per_page = 50
    save_on_top = True

    def name_short(self, obj):
        return (obj.name or "")[:100]
    name_short.short_description = "Название"



# --- Фильтр "есть/нет преаналитики"
class HasPreanalyticFilter(admin.SimpleListFilter):
    title = "Преаналитика"
    parameter_name = "has_preanalytic"

    def lookups(self, request, model_admin):
        return (("yes", "Только с преаналитикой"),
                ("no", "Без преаналитики"),)

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(preanalytic__isnull=False).distinct()  # <<< plural + distinct
        if val == "no":
            return queryset.filter(preanalytic__isnull=True).distinct()   # <<<
        return queryset


# --- Inline для преаналитики (reverse FK)
class PanelPreanalyticInline(admin.StackedInline):
    model = PanelPreanalytic
    extra = 0
    classes = ("collapse",)
    fieldsets = (
        (None, {"fields": (
            "min_count",
            "training",
            "centrifugation",
            "storage_transportation",
            "note",
        )}),
    )


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name_short",
        "category_code",
        "duration",
        "materials_badge",
        "tests_count",
        "preanalytic_badge",
    )
    search_fields = (
        "code",
        "name",
        "category_code",
        "duration",
        "panel_tests__test__name",
        # поиск по текстам преаналитики (reverse FK)
        "preanalytic__training",                 # <<<
        "preanalytic__centrifugation",           # <<<
        "preanalytic__storage_transportation",   # <<<
        "preanalytic__note",                     # <<<
        "preanalytic__min_count",                # <<<
    )
    list_filter = ("category_code", HasPreanalyticFilter, PanelByBiomaterialFilter, PanelHasLinkedFilter)
    ordering = ("code",)
    inlines = (PanelPreanalyticInline, PanelTestInline, PanelMaterialInline)
    list_per_page = 50
    save_on_top = True

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("category")
        # reverse-связи — через prefetch
        return qs.prefetch_related(
            "panel_tests__test",
            "panel_materials__biomaterial",
            "panel_materials__container_type",
            Prefetch(
                "preanalytic",
                queryset=PanelPreanalytic.objects.only(
                    "id", "panel_id", "min_count", "training",
                    "centrifugation", "storage_transportation", "note"
                ).order_by("id"),
            ),
        )

    def name_short(self, obj):
        return (obj.name or "")[:100]
    name_short.short_description = "Название"

    def materials_badge(self, obj):
        mats = obj.panel_materials.select_related("biomaterial", "container_type")
        if not mats.exists():
            return "—"
        items = []
        MAX_SHOW = 3
        for m in list(mats[:MAX_SHOW]):
            bi = (m.biomaterial.name or m.biomaterial.code)
            ct = m.container_type.name if m.container_type_id else ""
            items.append(f"{bi}{(' → ' + ct) if ct else ''}")
        tail = "…" if mats.count() > MAX_SHOW else ""
        return ", ".join(items) + tail
    materials_badge.short_description = "Материалы"

    def tests_count(self, obj):
        return obj.panel_tests.count()
    tests_count.short_description = "Тестов"

    def preanalytic_badge(self, obj):
        # работаем с множеством preanalytics; показываем краткий тизер по первой записи
        pa = getattr(obj, "preanalytic", None)
        if not pa:
            return "—"
        pa_first = pa.first() if hasattr(pa, "first") else None
        if not pa_first:
            return "—"
        teaser = pa_first.min_count or pa_first.training or pa_first.centrifugation or pa_first.storage_transportation or pa_first.note or ""
        teaser = teaser.strip()
        if len(teaser) > 40:
            teaser = teaser[:40] + "…"
        return format_html(
            '<span style="display:inline-block;padding:.1rem .35rem;border-radius:.5rem;'
            'background:#e6ffed;border:1px solid #b7eb8f;">есть</span> {}',
            teaser or ""
        )
    preanalytic_badge.short_description = "Преаналитика"


# ==========================
# Admin site look & feel
# ==========================
admin.site.site_header = "КДЛ / Витрина — администрирование"
admin.site.site_title = "КДЛ Админка"
admin.site.index_title = "Навигация по справочникам и заявкам"
admin.site.empty_value_display = "—"
