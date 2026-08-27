from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0035_fileoperation_archive_formats"),
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
                    ("compress", "Compress"),
                    ("uncompress", "Uncompress"),
                    ("search", "Search"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
