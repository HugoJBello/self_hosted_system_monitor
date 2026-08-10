from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0022_backupjob_remote_direction"),
    ]

    operations = [
        migrations.CreateModel(
            name="VolumeMountPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("volume_key", models.CharField(db_index=True, max_length=255, unique=True)),
                ("device", models.CharField(blank=True, default="", max_length=255)),
                ("uuid", models.CharField(blank=True, default="", max_length=255)),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("model", models.CharField(blank=True, default="", max_length=255)),
                ("serial", models.CharField(blank=True, default="", max_length=255)),
                ("mountpoint", models.CharField(max_length=500)),
                ("last_mounted_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("volume_key",),
            },
        ),
    ]
