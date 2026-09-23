from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


FEATURES = ["monitor", "history", "alerts", "reports", "docker", "files", "volumes", "jobs", "backups"]


def preserve_existing_access(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Access = apps.get_model("monitor", "UserFeatureAccess")
    Access.objects.bulk_create([
        Access(user_id=user_id, feature=feature)
        for user_id in User.objects.filter(is_staff=False).values_list("pk", flat=True)
        for feature in FEATURES
    ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("monitor", "0038_fileshareaccessevent"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="UserFeatureAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("feature", models.CharField(db_index=True, max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feature_accesses", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ("feature",)},
        ),
        migrations.AddConstraint(model_name="userfeatureaccess", constraint=models.UniqueConstraint(fields=("user", "feature"), name="unique_user_feature_access")),
        migrations.RunPython(preserve_existing_access, migrations.RunPython.noop),
    ]
