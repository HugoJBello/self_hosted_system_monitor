from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0008_backupjob_cloudflare_auth_home"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backuprun",
            name="status",
            field=models.CharField(
                choices=[("running", "Running"), ("success", "Success"), ("failed", "Failed")],
                default="success",
                max_length=16,
            ),
        ),
    ]
