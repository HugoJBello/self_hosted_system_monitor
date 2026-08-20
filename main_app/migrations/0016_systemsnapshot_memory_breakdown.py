from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0015_script_job_schedule_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsnapshot",
            name="memory_buffers_mb",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="systemsnapshot",
            name="memory_cached_mb",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="systemsnapshot",
            name="memory_slab_mb",
            field=models.FloatField(default=0),
        ),
    ]
