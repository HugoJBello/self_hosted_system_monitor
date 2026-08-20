from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class ReportRule(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    period_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 30)],
    )
    cadence_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 30)],
    )
    send_notifications = models.BooleanField(default=True)
    notification_channels = models.CharField(blank=True, default="", max_length=255)
    notification_tags = models.CharField(blank=True, default="", max_length=255)
    notification_user = models.CharField(blank=True, default="", max_length=255)
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "monitor"
        ordering = ("position", "id")

    @property
    def notification_channels_list(self):
        return [item.strip() for item in self.notification_channels.replace(",", ";").split(";") if item.strip()]

    @property
    def notification_tags_list(self):
        return [item.strip() for item in self.notification_tags.replace(",", ";").split(";") if item.strip()]

    def save(self, *args, **kwargs):
        if self.enabled and self.next_run_at is None:
            self.next_run_at = timezone.now() + timezone.timedelta(hours=max(self.cadence_hours, 1))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ReportRun(models.Model):
    rule = models.ForeignKey("monitor.ReportRule", related_name="runs", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    sample_count = models.PositiveIntegerField(default=0)
    report_data = models.JSONField(default=dict)
    notification_sent = models.BooleanField(default=False)
    notification_status_code = models.IntegerField(blank=True, null=True)
    notification_response = models.JSONField(blank=True, null=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-generated_at",)

    def __str__(self):
        return f"{self.rule.name} report @ {self.generated_at:%Y-%m-%d %H:%M:%S}"
