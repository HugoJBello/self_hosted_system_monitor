from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0010_backup_runtime_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="backup_type",
            field=models.CharField(
                choices=[("remote", "Remote SSH/Cloudflare"), ("local", "Local folder clone")],
                default="remote",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="last_mount_was_available",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="local_dest_path",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="trigger_on_mount",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="backupjob",
            name="remote_dir",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AlterField(
            model_name="backupjob",
            name="remote_host",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="backupjob",
            name="remote_user",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
