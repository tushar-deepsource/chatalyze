from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.utils import RandomFileName
from core import settings
from core.celery import app


class ChatAnalysis(models.Model):
    class AnalysisStatus(models.TextChoices):
        """Enumerated string choices."""

        READY = "READY", "Ready"
        PROCESSING = "PROCESSING", "Processing"
        ERROR = "ERROR", "Error"

    author = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
    )
    chat_file = models.FileField(upload_to="chats", storage=settings.private_storage)
    chat_name = models.CharField(
        max_length=255,
        default="-",
    )
    telegram_id = models.CharField(
        blank=True,
        max_length=40,
    )
    chat_platform = models.CharField(
        max_length=255,
        default="-",
    )
    messages_count = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PROCESSING,
    )
    error_text = models.TextField(blank=True)
    word_cloud_pic = models.ImageField(
        blank=True,
        null=True,
        upload_to=RandomFileName("wordclouds"),
    )
    task_id = models.UUIDField(
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"{self.author} - {self.chat_name}"

    class Meta:
        ordering = ["-updated"]
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_status_valid",
                check=models.Q(status__in=["READY", "PROCESSING", "ERROR"]),
            ),
        )


@receiver(pre_delete, sender=ChatAnalysis)
def my_handler(instance, **__):
    app.control.revoke(instance.task_id, terminate=True)
