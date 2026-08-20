from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0012_monitoringsettings_display_timezone"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="http_backup_token",
            field=models.CharField(blank=True, default="change_this_token", max_length=255),
        ),
        migrations.AlterField(
            model_name="backupjob",
            name="backup_type",
            field=models.CharField(
                choices=[
                    ("local", "Local memory backup"),
                    ("remote", "SSH + rsync backup"),
                    ("http", "HTTP server to server backup"),
                ],
                default="remote",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="http_remote_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="http_remote_token",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="http_remote_path",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="http_direction",
            field=models.CharField(
                choices=[
                    ("push", "Copy from this server to remote server"),
                    ("pull", "Copy from remote server to this server"),
                ],
                default="push",
                max_length=16,
            ),
        ),
    ]
