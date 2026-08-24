from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0027_fileoperation"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileoperation",
            name="conflict_policy",
            field=models.CharField(
                choices=[("overwrite", "Overwrite"), ("skip", "Skip"), ("rename", "Rename")],
                default="overwrite",
                max_length=16,
            ),
        ),
    ]
