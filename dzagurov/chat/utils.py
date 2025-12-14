from django.contrib import messages as dj_messages

CHAT_QUEUE_KEY = "chat_system_queue"

def push_chat_system_message(request, text: str, level=dj_messages.INFO):
    """
    1) обычное django-message (для баннеров на странице)
    2) дубль в session-очередь (для чата)
    """
    dj_messages.add_message(request, level, text)

    queue = request.session.get(CHAT_QUEUE_KEY, [])
    queue.append({
        "level": dj_messages.DEFAULT_TAGS.get(level, "info"),
        "content": str(text),
    })
    request.session[CHAT_QUEUE_KEY] = queue
    request.session.modified = True


def pop_django_messages(request):
    """
    Для чата: берём session-очередь + django-messages (fallback),
    и убираем дубли (которые появляются из-за двойной записи push_chat_system_message).
    """
    combined = []

    # 1) очередь чата (устойчива до открытия чата)
    queued = request.session.pop(CHAT_QUEUE_KEY, [])
    if queued:
        request.session.modified = True
        combined.extend(queued)

    # 2) одноразовые django-messages (если ещё не съедены шаблоном)
    storage = dj_messages.get_messages(request)
    for m in storage:
        combined.append({
            "level": m.level_tag,
            "content": str(m.message),
        })

    # 3) дедуп: (level, content)
    seen = set()
    result = []
    for item in combined:
        key = (item.get("level"), item.get("content"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result

