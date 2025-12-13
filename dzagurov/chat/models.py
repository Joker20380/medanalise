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
    vk_peer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    vk_from_id = models.BigIntegerField(null=True, blank=True, db_index=True)


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

    vk_message_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        db_index=True,  # ускорит exists/filter по vk_message_id
    )

    thread = models.ForeignKey(
        "ChatThread",
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
    )

    sender = models.CharField(
        max_length=16,
        choices=SENDER_CHOICES,
        db_index=True,  # опционально, но полезно для админки/фильтров
    )

    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"[{self.sender}] {self.text[:40]}"

    class Meta:
        # Важно: для инкрементального polling дешевле и стабильнее order_by("id")
        # Это не ломает created_at, он всё равно есть и отображается.
        ordering = ("id",)
        verbose_name = "Сообщение чата"
        verbose_name_plural = "Сообщения чата"
        indexes = [
            # Ключевой индекс под запрос:
            # WHERE thread_id = ? AND id > ? ORDER BY id LIMIT N
            models.Index(fields=["thread", "id"], name="chatmsg_thread_id_idx"),
        ]

