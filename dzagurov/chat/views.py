import json
import hashlib

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache

import time



from .models import ChatMessage
from .views import _get_or_create_thread

from .models import ChatThread, ChatMessage


def _visitor_session(request):
    """
    Грубый, но стабильный идентификатор посетителя на базе сессии+UA+IP.
    """
    key = (request.session.session_key or "anon") + \
          (request.META.get("HTTP_USER_AGENT", "")) + \
          (request.META.get("REMOTE_ADDR", ""))
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _get_or_create_thread(request):
    """
    Находит открытый тред для посетителя или создаёт новый.
    """
    # гарантируем, что у сессии есть ключ
    if not request.session.session_key:
        request.session.save()

    vsess = _visitor_session(request)

    thread = (
        ChatThread.objects
        .filter(visitor_session=vsess, closed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if not thread:
        thread = ChatThread.objects.create(visitor_session=vsess)

    return thread


@csrf_exempt
@require_POST
def bootstrap(request):
    """
    Старая точка входа, если вдруг где-то используется.
    Возвращает UUID треда и (на будущее) ws_url.
    """
    thread = _get_or_create_thread(request)
    return JsonResponse({
        "thread_uuid": str(thread.uuid),
        "ws_url": f"/ws/chat/{thread.uuid}/",
    })


@never_cache
def chat_api_messages(request):
    """
    GET /chat/api/messages/?after_id=123&timeout=20

    Long-poll:
    - если есть новые сообщения -> отдаём сразу
    - если нет -> ждём до timeout секунд, проверяя раз в ~0.8s
    """
    thread = _get_or_create_thread(request)

    try:
        after_id = int(request.GET.get("after_id") or 0)
    except ValueError:
        after_id = 0

    try:
        timeout = int(request.GET.get("timeout") or 20)
    except ValueError:
        timeout = 20

    timeout = max(1, min(timeout, 25))  # держим коротко, чтобы не убивать воркеры
    deadline = time.monotonic() + timeout

    def fetch_new():
        qs = (
            thread.messages
            .filter(id__gt=after_id)
            .order_by("id")[:50]  # страховка
        )
        return list(qs)

    messages = fetch_new()

    # long-poll ожидание
    while not messages and time.monotonic() < deadline:
        time.sleep(0.8)
        messages = fetch_new()

    data = {
        "thread_id": thread.id,  # или uuid, как у тебя
        "messages": [
            {
                "id": m.id,
                "role": "user" if m.sender == "visitor" else "assistant",
                "content": m.text,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "server_time": time.time(),
    }
    return JsonResponse(data)




@csrf_exempt  # для простоты, чтобы не возиться с CSRF в JS
@require_POST
def chat_api_send(request):
    """
    POST /chat/api/send/ — принять сообщение от посетителя.
    Тело: {"text": "..."}.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    text = (payload.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "empty"}, status=400)

    thread = _get_or_create_thread(request)

    msg = ChatMessage.objects.create(
        thread=thread,
        sender="visitor",
        text=text,
    )

    return JsonResponse({
        "message": {
            "id": msg.id,
            "sender": msg.sender,
            "text": msg.text,
            "created_at": msg.created_at.isoformat(),
        }
    })
