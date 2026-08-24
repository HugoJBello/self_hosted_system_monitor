from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0031_fileoperation_rsync_delete"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fileoperation",
            name="action",
            field=models.CharField(
                choices=[
                    ("copy", "Copy"),
                    ("move", "Move"),
                    ("delete", "Delete"),
                    ("upload", "Upload"),
                    ("download", "Download"),
                    ("search", "Search"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="FileSearch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("root_path", models.CharField(max_length=500)),
                ("query", models.CharField(max_length=500)),
                ("recursive", models.BooleanField(default=True)),
                ("timeout_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("result_paths", models.JSONField(blank=True, default=list)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("truncated", models.BooleanField(default=False)),
                ("timed_out", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("operation", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="search", to="monitor.fileoperation")),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
