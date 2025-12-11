import uuid

from django.db import models


class ChatThread(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # для анонимов — завязка на сессию браузера
    visitor_session = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        default="",
    )
    visitor_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )

    def __str__(self):
        status = "closed" if self.closed_at else "open"
        return f"{self.uuid} ({status})"

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Чат-сессия"
        verbose_name_plural = "Чат-сессии"


class ChatMessage(models.Model):
    SENDER_CHOICES = [
        ("visitor", "Visitor"),
        ("operator", "Operator"),
        ("system", "System"),
    ]

    thread = models.ForeignKey(
        ChatThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.CharField(
        max_length=16,
        choices=SENDER_CHOICES,
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.sender}] {self.text[:40]}"

    class Meta:
        ordering = ("created_at",)
        verbose_name = "Сообщение чата"
        verbose_name_plural = "Сообщения чата"
