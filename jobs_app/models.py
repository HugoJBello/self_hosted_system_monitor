from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class ScriptJob(models.Model):
    SCHEDULE_MODE_CHOICES = [
        ("manual", "Run only when clicking Run now"),
        ("interval", "Recurring schedule"),
        ("one_off", "Run once at a specific date and time"),
    ]
    SCHEDULE_UNIT_CHOICES = [
        ("minutes", "Minutes"),
        ("days", "Days"),
        ("weeks", "Weeks"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    schedule_mode = models.CharField(max_length=16, choices=SCHEDULE_MODE_CHOICES, default="interval")
    schedule_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(60 * 24 * 30)],
    )
    schedule_unit = models.CharField(max_length=16, choices=SCHEDULE_UNIT_CHOICES, default="minutes")
    scheduled_for = models.DateTimeField(blank=True, null=True)
    working_directory = models.CharField(max_length=500, blank=True, default="")
    script_body = models.TextField(default="")
    script_arguments = models.JSONField(default=dict, blank=True)
    run_as_sudo = models.BooleanField(default=False)
    sudo_password = models.CharField(max_length=255, blank=True, default="")
    run_timeout_seconds = models.PositiveIntegerField(
        default=7200,
        validators=[MinValueValidator(30), MaxValueValidator(60 * 60 * 24 * 7)],
    )
    idle_timeout_seconds = models.PositiveIntegerField(
        default=900,
        validators=[MinValueValidator(30), MaxValueValidator(60 * 60 * 24)],
    )
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "monitor"
        ordering = ("position", "id")

    @property
    def is_one_off(self):
        return self.schedule_mode == "one_off"

    @property
    def is_manual(self):
        return self.schedule_mode == "manual"

    @property
    def cadence_delta(self):
        value = max(int(self.schedule_minutes or 0), 1)
        if self.schedule_unit == "weeks":
            return timezone.timedelta(weeks=value)
        if self.schedule_unit == "days":
            return timezone.timedelta(days=value)
        return timezone.timedelta(minutes=max(value, 5))

    @property
    def schedule_label(self):
        if self.is_manual:
            return "Run only on demand"
        if self.is_one_off:
            return (
                timezone.localtime(self.scheduled_for).strftime("%Y-%m-%d %H:%M")
                if self.scheduled_for
                else "Date pending"
            )
        unit_map = {
            "minutes": "minute",
            "days": "day",
            "weeks": "week",
        }
        unit_label = unit_map.get(self.schedule_unit, "minute")
        plural = "" if int(self.schedule_minutes or 0) == 1 else "s"
        return f"Every {self.schedule_minutes} {unit_label}{plural}"

    @property
    def script_preview(self):
        for line in (self.script_body or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:120]
        return "(empty script)"

    @property
    def normalized_script_arguments(self):
        payload = self.script_arguments if isinstance(self.script_arguments, dict) else {}
        positionals = []
        flags = []
        for item in payload.get("positionals", []):
            if not isinstance(item, dict):
                continue
            value = str(item.get("value", ""))
            if value:
                positionals.append({"value": value})
        for item in payload.get("flags", []):
            if not isinstance(item, dict):
                continue
            flag = str(item.get("flag", ""))
            value = str(item.get("value", ""))
            if flag:
                flags.append({"flag": flag, "value": value})
        return {"positionals": positionals, "flags": flags}

    @property
    def script_argument_parts(self):
        payload = self.normalized_script_arguments
        parts = [item["value"] for item in payload["positionals"]]
        for item in payload["flags"]:
            parts.append(item["flag"])
            if item["value"]:
                parts.append(item["value"])
        return parts

    @property
    def script_arguments_count(self):
        payload = self.normalized_script_arguments
        return len(payload["positionals"]) + len(payload["flags"])

    def save(self, *args, **kwargs):
        if not self.enabled:
            self.next_run_at = None
        elif self.is_manual:
            self.next_run_at = None
        elif self.is_one_off:
            self.next_run_at = self.scheduled_for
        elif self.next_run_at is None:
            self.next_run_at = timezone.now() + self.cadence_delta
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ScriptJobRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("timed_out", "Timed out"),
    ]
    LAUNCH_CHOICES = [
        ("manual", "Manual"),
        ("scheduler", "Scheduler"),
    ]

    job = models.ForeignKey("monitor.ScriptJob", related_name="runs", on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="success")
    exit_code = models.IntegerField(default=0)
    summary = models.CharField(max_length=255, blank=True, default="")
    log_output = models.TextField(blank=True, default="")
    launched_by = models.CharField(max_length=16, choices=LAUNCH_CHOICES, default="manual")
    process_pid = models.PositiveIntegerField(blank=True, null=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)
    last_output_at = models.DateTimeField(blank=True, null=True)
    stop_requested_at = models.DateTimeField(blank=True, null=True)
    command_line = models.TextField(blank=True, default="")
    runner_label = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        app_label = "monitor"
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.job.name} @ {self.started_at:%Y-%m-%d %H:%M:%S}"
