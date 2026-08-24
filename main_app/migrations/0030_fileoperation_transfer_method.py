from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0029_fileoperation_folder_conflict_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileoperation",
            name="transfer_method",
            field=models.CharField(
                choices=[("standard", "Standard"), ("rsync", "Rsync differential")],
                default="standard",
                max_length=16,
            ),
        ),
    ]
