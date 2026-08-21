from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0025_alter_backupjob_max_size"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="file_manager_start_path",
            field=models.CharField(default="/", max_length=500),
        ),
    ]
