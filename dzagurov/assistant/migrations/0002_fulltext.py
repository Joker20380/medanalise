from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [("assistant", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE assistant_searchindex ADD FULLTEXT INDEX ft_search (search_text);",
            reverse_sql="ALTER TABLE assistant_searchindex DROP INDEX ft_search;",
        )
    ]
