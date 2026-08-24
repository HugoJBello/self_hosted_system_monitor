from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0028_fileoperation_conflict_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileoperation",
            name="folder_conflict_policy",
            field=models.CharField(
                choices=[("merge", "Merge"), ("skip", "Skip"), ("rename", "Rename")],
                default="merge",
                max_length=16,
            ),
        ),
    ]
