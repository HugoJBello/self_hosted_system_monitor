from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0032_filesearch"),
    ]

    operations = [
        migrations.AddField(
            model_name="filesearch",
            name="case_sensitive",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="filesearch",
            name="use_regex",
            field=models.BooleanField(default=False),
        ),
    ]
