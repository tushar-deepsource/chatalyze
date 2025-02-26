from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from model_utils.fields import UrlsafeTokenField

from apps.utils import RandomFileName
from core import settings
from core.celery import app


class ChatAnalysis(models.Model):
    """Stores analysis results and chat information

    Attributes:
        author: Related User model
        chat_file: File containing chat messages
        chat_name: Chat title
        telegram_id: Chat id for Telegram chats
        chat_platform: Chat platform name
        language: Chat language
        messages_count: Number of the messages in the chat
        created: Date and time the first analysis started
        updated: Date and time the last analysis finished
        status: Analysis status
        error_text: Text of error to display
        word_cloud_pic: WordCloud picture file
        task_id: Last Celery task id for the analysis
        results: Analysis data

    """

    class AnalysisStatus(models.TextChoices):
        """Enumerated string choices."""

        READY = "READY"
        PROCESSING = "PROCESSING"
        ERROR = "ERROR"

    class AnalysisLanguage(models.TextChoices):
        """Enumerated string choices."""

        ENGLISH = "ENG"
        RUSSIAN = "RUS"

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
    language = models.CharField(
        max_length=3,
        choices=AnalysisLanguage.choices,
        default=AnalysisLanguage.RUSSIAN,
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
    results = models.JSONField(
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
                check=models.Q(
                    status__in=(
                        "READY",
                        "PROCESSING",
                        "ERROR",
                    )
                ),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_language_valid",
                check=models.Q(
                    language__in=(
                        "ENG",
                        "RUS",
                    )
                ),
            ),
        )


@receiver(pre_delete, sender=ChatAnalysis)
def my_handler(instance, **__):
    """Stops a task associated with the deleted analysis"""
    app.control.revoke(instance.task_id, terminate=True)


class ShareLink(models.Model):
    """Stores public id for a shared analysis

    Attributes:
        id: id for the shared analysis link
        analysis: Related ChatAnalysis model
    """

    id = UrlsafeTokenField(
        editable=False,
        max_length=128,
        primary_key=True,
    )
    analysis = models.OneToOneField(
        to=ChatAnalysis,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return "link - " + str(self.analysis)
