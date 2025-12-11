import json
import hashlib

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

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


@require_GET
def chat_api_messages(request):
    """
    GET /chat/api/messages/ — отдать историю сообщений текущего посетителя.
    """
    thread = _get_or_create_thread(request)
    messages = thread.messages.order_by("created_at")

    data = {
        "thread_uuid": str(thread.uuid),
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "text": m.text,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
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
