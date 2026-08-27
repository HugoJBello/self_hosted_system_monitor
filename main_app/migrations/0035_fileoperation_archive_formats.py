from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0034_fileoperation_compress"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fileoperation",
            name="compression_method",
            field=models.CharField(
                choices=[
                    ("deflated", "ZIP deflated"),
                    ("stored", "Store only"),
                    ("bzip2", "ZIP BZIP2"),
                    ("lzma", "ZIP LZMA"),
                    ("tar", "TAR"),
                    ("tar_gz", "TAR gzip"),
                    ("tar_bz2", "TAR BZIP2"),
                    ("tar_xz", "TAR XZ"),
                ],
                default="deflated",
                max_length=16,
            ),
        ),
    ]
