import json
import hashlib

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache

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
    GET /chat/api/messages/?after_id=123
    - Если after_id задан: вернуть только сообщения с id > after_id
    - Если after_id не задан: вернуть последние N (для первого открытия/фоллбэка)
    """
    thread = _get_or_create_thread(request)

    after_id_raw = request.GET.get("after_id")
    try:
        after_id = int(after_id_raw) if after_id_raw is not None else None
    except (TypeError, ValueError):
        after_id = None

    LIMIT = 50  # под UX и экономию CPU/DB

    qs = thread.messages.all()

    # Важно: id — лучше ключ для инкрементальной выборки
    if after_id is not None:
        qs = qs.filter(id__gt=after_id).order_by("id")[:LIMIT]
    else:
        # Если фронт открылся и lastMessageId неизвестен — не отдаём всю историю
        # отдаём последние LIMIT, но в правильном порядке
        qs = qs.order_by("-id")[:LIMIT]
        qs = reversed(list(qs))  # чтобы вернуть по возрастанию id

        data = {
            "thread_uuid": str(thread.uuid),
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "text": m.text,
                    "created_at": m.created_at.isoformat(),
                }
                for m in qs
            ],
        }
        return JsonResponse(data)

    # Оптимизация сериализации: values() (меньше накладных расходов ORM)
    rows = list(qs.values("id", "sender", "text", "created_at"))

    data = {
        "thread_uuid": str(thread.uuid),
        "messages": [
            {
                "id": r["id"],
                "sender": r["sender"],
                "text": r["text"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
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
