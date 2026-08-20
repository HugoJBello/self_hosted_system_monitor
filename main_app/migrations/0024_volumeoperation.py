from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0023_volumemountpreference"),
    ]

    operations = [
        migrations.CreateModel(
            name="VolumeOperation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("label", "Update label"), ("format", "Format")], max_length=16)),
                ("device", models.CharField(db_index=True, max_length=255)),
                ("fstype", models.CharField(blank=True, default="", max_length=32)),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("running", "Running"), ("success", "Success"), ("failed", "Failed")], db_index=True, default="running", max_length=16)),
                ("summary", models.CharField(blank=True, default="", max_length=255)),
                ("log_output", models.TextField(blank=True, default="")),
                ("command_line", models.TextField(blank=True, default="")),
                ("process_pid", models.PositiveIntegerField(blank=True, null=True)),
                ("runner_label", models.CharField(blank=True, default="", max_length=255)),
                ("started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-started_at",),
            },
        ),
    ]
