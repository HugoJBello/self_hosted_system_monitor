from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0030_fileoperation_transfer_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileoperation",
            name="rsync_delete",
            field=models.BooleanField(default=False),
        ),
    ]
