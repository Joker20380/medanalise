from django.db import migrations
import hashlib

def norm(s: str) -> str:
    return (s or "").strip().lower()

def backfill_materials(apps, schema_editor):
    Material = apps.get_model("main", "Material")
    for m in Material.objects.all():
        base = (m.full_name or m.name or "").strip()
        if not m.full_name:
            m.full_name = base
        if not m.name:
            m.name = base[:255]
        if not m.normalized_name:
            m.normalized_name = norm(base)[:255]
        m.name_hash = hashlib.sha256(norm(base).encode("utf-8")).hexdigest()
        m.save(update_fields=["full_name", "name", "normalized_name", "name_hash"])

def backfill_categories(apps, schema_editor):
    Category = apps.get_model("main", "Category")
    for c in Category.objects.all():
        base = (c.full_name or c.name or "").strip()
        if not c.full_name:
            c.full_name = base
        if not c.name:
            c.name = base[:255]
        c.name_hash = hashlib.sha256(norm(base).encode("utf-8")).hexdigest()
        c.save(update_fields=["full_name", "name", "name_hash"])

class Migration(migrations.Migration):
    dependencies = [
        ("main", "0005_add_full_name_and_hashes"),  # ← ПОДСТАВЬ СВОЙ НОМЕР из шага 2
    ]
    operations = [
        migrations.RunPython(backfill_materials, migrations.RunPython.noop),
        migrations.RunPython(backfill_categories, migrations.RunPython.noop),
    ]
