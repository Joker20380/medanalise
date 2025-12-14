import json
import time

from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import ChatThread, ChatMessage
from .vk_client import send_vk_message

from django.contrib import messages as dj_messages
from .utils import pop_django_messages
from .utils import push_chat_system_message

# ✅ Шаблонные ответы (0 ₽)
from .quick_replies import match_quick_reply


CHAT_QUEUE_KEY = "chat_system_queue"


def _get_or_create_thread_for_session(request):
    """
    Вытаскиваем (или создаём) чат-поток, привязанный к session_key.
    Работает с текущей моделью ChatThread:
    поля visitor_session, visitor_name, created_at, closed_at.
    """
    # Убеждаемся, что у запроса вообще есть session_key
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key

    # Берём незакрытый поток для этой сессии
    thread = (
        ChatThread.objects
        .filter(visitor_session=session_key, closed_at__isnull=True)
        .order_by("created_at")
        .first()
    )

    if thread is None:
        thread = ChatThread.objects.create(
            visitor_session=session_key,
            visitor_name="",  # можно потом заполнить, если понадобится
        )

    return thread


@login_required
@require_http_methods(["GET", "POST"])
def chat_bootstrap(request):
    """
    Создаёт (при необходимости) поток для текущей сессии
    и возвращает всю историю сообщений + system (django-messages).

    Привязка — по visitor_session, а не по user.
    """
    try:
        thread = _get_or_create_thread_for_session(request)

        messages_qs = (
            ChatMessage.objects
            .filter(thread=thread)
            .order_by("created_at", "id")
        )

        def map_author(m):
            if m.sender == "visitor":
                return request.user.username
            if m.sender == "operator":
                # Можно оставить "Оператор" — это и для автоответов, и для VK-оператора.
                # Если хочешь различать, придётся добавлять доп. поле (kind/auto).
                return "Оператор"
            if m.sender == "system":
                return "Система"
            return "Система"

        def map_role(sender: str) -> str:
            if sender == "visitor":
                return "user"
            if sender == "operator":
                return "assistant"
            if sender == "system":
                return "system"
            return "system"

        messages = [
            {
                "id": m.id,
                "role": map_role(m.sender),
                "author": map_author(m),
                "content": m.text,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages_qs
        ]

        # ✅ системные сообщения берём из утилиты (django-messages + session queue)
        system_messages = pop_django_messages(request)

        return JsonResponse({
            "thread_id": thread.id,
            "messages": messages,
            "system_messages": system_messages,
        })

    except Exception as ex:
        import traceback
        traceback.print_exc()
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

    Привязка также по session_key (visitor_session),
    чтобы нельзя было дернуть чужой thread_id.
    """
    try:
        thread = _get_or_create_thread_for_session(request)
    except Exception as ex:
        return JsonResponse(
            {"error": f"chat_messages error: {ex!s}"},
            status=500,
        )

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
            "role": "user" if m.sender == "visitor" else ("system" if m.sender == "system" else "assistant"),
            "content": m.text,
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
    Принимает текст пользователя, сохраняет сообщение
    (sender='visitor').

    ✅ Далее:
      - пробуем шаблоны (0 ₽). Если матч — создаём автоответ (sender='operator') и НЕ шлём в VK.
      - если шаблона нет — отправляем копию в VK операторам как раньше.

    Ответы операторов прилетают из VK через callback и
    подхватываются фронтом через polling (chat_messages).
    """

    # Поддержка JSON и обычной формы
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")
        text = payload.get("content")
    else:
        text = request.POST.get("content")

    if not text:
        return HttpResponseBadRequest("content is required")

    try:
        thread = _get_or_create_thread_for_session(request)
    except Exception as ex:
        return JsonResponse(
            {"error": f"chat_send error: {ex!s}"},
            status=500,
        )

    now = timezone.now()

    # === Сообщение пользователя ===
    user_message = ChatMessage.objects.create(
        thread=thread,
        sender="visitor",
        text=text,
        created_at=now,
    )

    # ✅ 1) Шаблонные ответы (быстро, бесплатно)
    reply = match_quick_reply(text)
    if reply:
        auto_message = ChatMessage.objects.create(
            thread=thread,
            sender="operator",      # чтобы на фронте было как assistant
            text=reply.text,
            created_at=timezone.now(),
        )

        return JsonResponse({
            "user_message": {
                "id": user_message.id,
                "role": "user",
                "content": user_message.text,
                "created_at": user_message.created_at.isoformat(),
            },
            "auto_reply": {
                "id": auto_message.id,
                "role": "assistant",
                "content": auto_message.text,
                "created_at": auto_message.created_at.isoformat(),
            },
            "auto": True,
            "handoff": bool(getattr(reply, "handoff", False)),
        })

    # ✅ 2) Шаблон не найден → как раньше отправляем в VK
    try:
        send_vk_message(
            text=text,
            thread_id=thread.id,
            visitor_name=thread.visitor_name or "",
        )
    except Exception:
        # Внутри send_vk_message уже логируем; здесь не валим ответ пользователю
        pass

    return JsonResponse({
        "user_message": {
            "id": user_message.id,
            "role": "user",
            "content": user_message.text,
            "created_at": user_message.created_at.isoformat(),
        },
        "auto": False,
    })


@login_required
@require_http_methods(["GET"])
def chat_system_poll(request):
    try:
        timeout = int(request.GET.get("timeout") or 20)
    except ValueError:
        timeout = 20

    deadline = time.monotonic() + max(1, min(timeout, 60))

    while True:
        queue = request.session.get(CHAT_QUEUE_KEY, [])
        if queue:
            return JsonResponse({"count": len(queue)})

        if time.monotonic() >= deadline:
            return JsonResponse({"count": 0})

        time.sleep(0.5)
