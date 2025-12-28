from django.db import models
from django.utils import timezone
from django.conf import settings


class SearchIndex(models.Model):
    """
    Unified searchable index (RAG-ready)
    """
    class Kind(models.TextChoices):
        PANEL = "panel", "Panel"
        TEST = "test", "Test"
        LAB_SERVICE = "lab_service", "Lab Service"
        DOC = "doc", "Document"
        NEWS = "news", "News"
        CONTACT = "contact", "Contact"
        SITE_SERVICE = "site_service", "Site Service"

    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    object_id = models.PositiveBigIntegerField(db_index=True)

    title = models.CharField(max_length=512)
    url = models.CharField(max_length=1024)
    search_text = models.TextField()

    boost = models.FloatField(default=1.0)
    extra = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        unique_together = [("kind", "object_id")]
        indexes = [
            models.Index(fields=["kind", "object_id"]),
        ]

    def __str__(self):
        return f"{self.kind}:{self.object_id} {self.title[:80]}"


class AssistantEvent(models.Model):
    """
    Interaction log (analytics / future learning)
    """
    session_key = models.CharField(max_length=64, db_index=True, blank=True, default="")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    query = models.CharField(max_length=512)
    normalized = models.CharField(max_length=512, blank=True, default="")
    intents = models.JSONField(default=list, blank=True)

    results = models.JSONField(default=list, blank=True)  # ["panel:12", ...]
    clicked = models.CharField(max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
