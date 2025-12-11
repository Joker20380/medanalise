from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property



class Biomaterial(models.Model):
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.TextField()
    barcodeinfo = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Биоматериал"
        verbose_name_plural = "Биоматериалы"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.name[:60]}"


class ContainerType(models.Model):
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.TextField()
    color = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        verbose_name = "Тип контейнера"
        verbose_name_plural = "Типы контейнеров"
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Test(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.TextField()
    unit = models.CharField(max_length=128, blank=True, default="")
    method = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    low = models.CharField(max_length=64, blank=True, default="")
    high = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "Тест"
        verbose_name_plural = "Тесты"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.name[:80]}"


class Analyte(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="analytes")
    code = models.CharField(max_length=64, db_index=True)
    name = models.TextField()
    unit = models.CharField(max_length=64, blank=True, default="")
    norm_low = models.CharField(max_length=64, blank=True, default="")
    norm_high = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "Аналит"
        verbose_name_plural = "Аналиты"
        ordering = ["test_id", "code"]
        unique_together = [("test", "code")]
        indexes = [
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.name[:60]}"


class PanelCategory(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.TextField()
    sorter = models.IntegerField(null=True, blank=True)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )

    class Meta:
        verbose_name = "Категория панели"
        verbose_name_plural = "Категории панелей"
        ordering = ["sorter", "code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["parent", "sorter"]),
        ]

    def __str__(self):
        path = [self.name]
        p = self.parent
        while p:
            path.append(p.name)
            p = p.parent
        return " / ".join(reversed(path))


class Panel(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.TextField()
    duration = models.CharField(max_length=64, blank=True, default="")
    category_code = models.CharField(max_length=64, blank=True, default="", help_text="Легаси. Не использовать напрямую.")
    category = models.ForeignKey(
        "PanelCategory", on_delete=models.SET_NULL, null=True, blank=True, related_name="panels"
    )

    class Meta:
        verbose_name = "Панель"
        verbose_name_plural = "Панели"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name[:80]}"

	
    @cached_property
    def preanalytics_list(self):
        # используем реальный related_name="preanalytics"
        return self.preanalytics.order_by('order', 'id')
        

class Service(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.TextField()
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="RUB")
    duration = models.CharField(max_length=64, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    panel = models.ForeignKey("Panel", on_delete=models.SET_NULL, null=True, blank=True, related_name="services")

    class Meta:
        ordering = ["code"]
        verbose_name = "Услуга (прайс)"
        verbose_name_plural = "Прайс-лист"

    def __str__(self):
        return f"{self.code} — {self.name[:60]}"



class PanelTest(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="panel_tests")
    test = models.ForeignKey(Test, on_delete=models.PROTECT)

    class Meta:
        verbose_name = "Тест панели"
        verbose_name_plural = "Тесты панелей"
        unique_together = [("panel", "test")]
        indexes = [
            models.Index(fields=["panel", "test"]),
        ]

    def __str__(self):
        return f"{self.panel.code} → {self.test.code}"


class PanelMaterial(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="panel_materials")
    biomaterial = models.ForeignKey(Biomaterial, on_delete=models.PROTECT)
    container_type = models.ForeignKey(ContainerType, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        verbose_name = "Материал панели"
        verbose_name_plural = "Материалы панелей"
        unique_together = [("panel", "biomaterial", "container_type")]

    def __str__(self):
        return f"{self.panel.code} — {self.biomaterial.name}"


class PanelLinked(models.Model):
    main_panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="linked_children")
    extra_panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="linked_parents")

    class Meta:
        verbose_name = "Связанная панель"
        verbose_name_plural = "Связанные панели"
        unique_together = [("main_panel", "extra_panel")]

    def __str__(self):
        return f"{self.main_panel.code} ↔ {self.extra_panel.code}"


class TestRequirement(models.Model):
    field_code = models.CharField(max_length=64, db_index=True)
    name = models.TextField()
    description = models.TextField(blank=True, default="")
    dependent_tests = models.ManyToManyField(Test, related_name="required_fields", blank=True)

    class Meta:
        verbose_name = "Требование к тесту"
        verbose_name_plural = "Требования к тестам"
        ordering = ["field_code"]

    def __str__(self):
        return f"{self.field_code} — {self.name[:60]}"


class Localization(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="localizations")
    external_id = models.CharField(max_length=128, db_index=True)

    class Meta:
        verbose_name = "Локализация панели"
        verbose_name_plural = "Локализации панелей"
        unique_together = [("panel", "external_id")]

    def __str__(self):
        return f"{self.panel.code} → {self.external_id}"


class Order(models.Model):
    number = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, blank=True, default="")
    patient_fio = models.TextField(blank=True, default="")
    patient_birthdate = models.DateField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Заявка (направление)"
        verbose_name_plural = "Заявки (направления)"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["number"]),
        ]

    def __str__(self):
        return f"{self.number} — {self.patient_fio[:60]}"


class OrderPanel(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="panels")
    panel = models.ForeignKey(Panel, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, blank=True, default="")
    released_doctor = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Панель в заявке"
        verbose_name_plural = "Панели в заявках"
        unique_together = [("order", "panel")]

    def __str__(self):
        return f"{self.order.number} — {self.panel.code}"


class ResultEntry(models.Model):
    order_panel = models.ForeignKey(OrderPanel, on_delete=models.CASCADE, related_name="results")
    test = models.ForeignKey(Test, on_delete=models.PROTECT)
    analyte = models.ForeignKey(Analyte, on_delete=models.SET_NULL, null=True, blank=True)
    value = models.TextField(blank=True, default="")
    unit = models.CharField(max_length=64, blank=True, default="")
    norm_low = models.CharField(max_length=64, blank=True, default="")
    norm_high = models.CharField(max_length=64, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    rawresult = models.TextField(blank=True, default="")
    released_doctor = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Результат"
        verbose_name_plural = "Результаты"
        ordering = ["order_panel_id", "test_id"]
        indexes = [
            models.Index(fields=["order_panel", "test"]),
        ]

    def __str__(self):
        return f"{self.test.code}: {self.value}"


# app/models.py

class PanelPreanalytic(models.Model):
    panel = models.OneToOneField(
        Panel,
        on_delete=models.CASCADE,
        related_name="preanalytic"
    )

    # поля из спецификации НАКФФ
    training = models.TextField(blank=True, default="", help_text="Подготовка к исследованию")
    centrifugation = models.TextField(blank=True, default="", help_text="Центрифугирование")
    storage_transportation = models.TextField(blank=True, default="", help_text="Хранение и транспортировка")
    note = models.TextField(blank=True, default="", help_text="Примечание")
    min_count = models.TextField(blank=True, default="", help_text="Минимальный объем образца")

    # служебка
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Преаналитика панели"
        verbose_name_plural = "Преаналитика панелей"
        indexes = [
            models.Index(fields=["panel"]),
        ]

    def __str__(self):
        return f"Преаналитика {self.panel.code} — {self.panel.name[:60]}"
