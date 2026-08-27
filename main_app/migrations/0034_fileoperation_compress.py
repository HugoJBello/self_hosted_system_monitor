from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0033_filesearch_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileoperation",
            name="compression_method",
            field=models.CharField(
                choices=[
                    ("deflated", "ZIP deflated"),
                    ("stored", "Store only"),
                    ("bzip2", "ZIP BZIP2"),
                    ("lzma", "ZIP LZMA"),
                ],
                default="deflated",
                max_length=16,
            ),
        ),
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
                    ("search", "Search"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
