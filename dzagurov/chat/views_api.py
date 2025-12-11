import json
import os

from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import ChatThread, ChatMessage

from openai import OpenAI


# ===========================
#  OpenAI client factory
# ===========================
def get_openai_client():
    return None    # принудительно отключаем AI на серваке



# ===========================
#  BOOTSTRAP
# ===========================
@login_required
@require_http_methods(["POST"])
def chat_bootstrap(request):
    """
    Создаёт (при необходимости) поток пользователя
    и возвращает всю накопленную историю.
    Сделано максимально «толстокожим», чтобы не падать 500.
    """
    try:
        # Берём первый поток пользователя, если есть
        thread = (
            ChatThread.objects
            .filter(user=request.user)
            .order_by("id")
            .first()
        )

        # Если потока ещё нет — создаём
        if thread is None:
            thread = ChatThread.objects.create(
                user=request.user,
                title="Диалог с ассистентом",
            )

        messages_qs = (
            ChatMessage.objects
            .filter(thread=thread)
            .order_by("created_at")
        )

        messages = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages_qs
        ]

        return JsonResponse({
            "thread_id": thread.id,
            "messages": messages,
        })

    except Exception as ex:
        # Временно отдаём текст исключения наружу для диагностики
        return JsonResponse(
            {"error": f"chat_bootstrap error: {ex!s}"},
            status=500,
        )


# ===========================
#  GET NEW MESSAGES
# ===========================
@login_required
@require_http_methods(["GET"])
def chat_messages(request):
    """
    Возвращает сообщения потока.
    Если передан after_id — только более новые.
    """
    thread_id = request.GET.get("thread_id")
    if not thread_id:
        return HttpResponseBadRequest("thread_id is required")

    try:
        thread = ChatThread.objects.get(id=thread_id, user=request.user)
    except ChatThread.DoesNotExist:
        return HttpResponseBadRequest("Invalid thread_id")

    qs = ChatMessage.objects.filter(thread=thread)

    after_id = request.GET.get("after_id")
    if after_id:
        try:
            after_id_int = int(after_id)
            qs = qs.filter(id__gt=after_id_int)
        except ValueError:
            return HttpResponseBadRequest("after_id must be integer")

    qs = qs.order_by("created_at")

    messages = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in qs
    ]

    return JsonResponse({"messages": messages})


# ===========================
#  SEND MESSAGE
# ===========================
@login_required
@require_http_methods(["POST"])
def chat_send(request):
    """
    Принимает текст пользователя, сохраняет сообщение,
    синхронно получает ответ ассистента, сохраняет его
    и возвращает оба сообщения.
    """

    # Поддержка формы и JSON тела
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")
        text = payload.get("content")
        thread_id = payload.get("thread_id")
    else:
        text = request.POST.get("content")
        thread_id = request.POST.get("thread_id")

    if not text or not thread_id:
        return HttpResponseBadRequest("content and thread_id are required")

    try:
        thread = ChatThread.objects.get(id=thread_id, user=request.user)
    except ChatThread.DoesNotExist:
        return HttpResponseBadRequest("Invalid thread_id")

    # === Создаём сообщение пользователя ===
    user_message = ChatMessage.objects.create(
        thread=thread,
        role="user",
        content=text,
        created_at=timezone.now(),
    )

    # === Готовим историю для модели ===
    history = ChatMessage.objects.filter(thread=thread).order_by("created_at")
    openai_messages = [
        {"role": m.role, "content": m.content}
        for m in history
    ]

    # === Запрос к модели ===
    client = get_openai_client()
    if not client:
        assistant_text = "⚠️ AI временно недоступен: не задан OPENAI_API_KEY."
    else:
        try:
            completion = client.chat.completions.create(
                model="gpt-5.1-mini",
                messages=openai_messages,
            )
            assistant_text = completion.choices[0].message.content
        except Exception as ex:
            assistant_text = f"Ошибка обращения к AI: {ex}"

    # === Создаём ответ ассистента ===
    assistant_message = ChatMessage.objects.create(
        thread=thread,
        role="assistant",
        content=assistant_text,
        created_at=timezone.now(),
    )

    return JsonResponse({
        "user_message": {
            "id": user_message.id,
            "role": user_message.role,
            "content": user_message.content,
            "created_at": user_message.created_at.isoformat(),
        },
        "assistant_message": {
            "id": assistant_message.id,
            "role": assistant_message.role,
            "content": assistant_message.content,
            "created_at": assistant_message.created_at.isoformat(),
        },
    })
