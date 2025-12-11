from django.contrib import admin
from .models import ChatThread, ChatMessage

@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    # что видно в списке
    list_display = ("id", "uuid", "created_at", "closed_at")
    # по чему фильтруем/ищем
    list_filter = ("created_at",)
    search_fields = ("uuid",)

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "short_text", "created_at")
    list_filter = ("sender", "created_at")
    search_fields = ("text", "thread__uuid")

    def short_text(self, obj):
        t = obj.text or ""
        return (t[:80] + "…") if len(t) > 80 else t
    short_text.short_description = "text"
