from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]
    METRIC_CHOICES = [
        ("cpu_percent", "CPU percent"),
        ("memory_percent", "Memory percent"),
        ("swap_percent", "Swap percent"),
        ("disk_percent", "Disk percent"),
        ("load_avg_1", "Load average 1m"),
        ("load_avg_5", "Load average 5m"),
        ("load_avg_15", "Load average 15m"),
        ("network_sent_rate_kbps", "Network sent kbps"),
        ("network_recv_rate_kbps", "Network received kbps"),
        ("process_count_total", "Total processes"),
        ("process_count_running", "Running processes"),
        ("process_count_zombie", "Zombie processes"),
    ]
    EVALUATION_CHOICES = [
        ("current", "Current value"),
        ("avg", "Average in window"),
        ("max", "Maximum in window"),
        ("min", "Minimum in window"),
    ]
    COMPARATOR_CHOICES = [
        ("gt", ">"),
        ("gte", ">="),
        ("lt", "<"),
        ("lte", "<="),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default="warning")
    metric = models.CharField(max_length=64, choices=METRIC_CHOICES)
    evaluation_mode = models.CharField(max_length=16, choices=EVALUATION_CHOICES, default="current")
    comparator = models.CharField(max_length=8, choices=COMPARATOR_CHOICES, default="gte")
    threshold = models.FloatField(default=80)
    window_minutes = models.PositiveIntegerField(default=5)
    min_occurrences = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
    )
    cooldown_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(10080)],
    )
    notifications_enabled = models.BooleanField(default=True)
    notification_channels = models.CharField(blank=True, default="", max_length=255)
    notification_tags = models.CharField(blank=True, default="", max_length=255)
    notification_user = models.CharField(blank=True, default="", max_length=255)
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

    def __str__(self):
        return self.name


class AlertEvent(models.Model):
    rule = models.ForeignKey(AlertRule, related_name="events", on_delete=models.CASCADE)
    snapshot = models.ForeignKey("monitor.SystemSnapshot", related_name="alert_events", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=16, choices=AlertRule.SEVERITY_CHOICES)
    metric = models.CharField(max_length=64)
    comparator = models.CharField(max_length=8)
    threshold = models.FloatField()
    evaluated_value = models.FloatField()
    matching_count = models.PositiveIntegerField(default=0)
    sample_count = models.PositiveIntegerField(default=1)
    window_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(blank=True, null=True)
    notification_sent = models.BooleanField(default=False)
    notification_status_code = models.IntegerField(blank=True, null=True)
    notification_response = models.JSONField(blank=True, null=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-triggered_at",)

    def __str__(self):
        return f"{self.rule.name} @ {self.triggered_at:%Y-%m-%d %H:%M:%S}"
