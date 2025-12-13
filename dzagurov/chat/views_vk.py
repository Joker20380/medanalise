import json
import logging
import re

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ChatThread, ChatMessage

logger = logging.getLogger(__name__)

THREAD_ID_RE = re.compile(r"#(\d+)")


def _vk_text(s: str) -> HttpResponse:
    """VK ожидает простой text/plain ответ."""
    return HttpResponse(s, content_type="text/plain; charset=utf-8")


def _find_thread_id_in_text(text: str) -> int | None:
    """
    Ищем номер потока в тексте вида:
    "#123 Привет" или "Ответ по #123 ..." и т.п.
    Берём первое вхождение #<число>.
    """
    if not text:
        return None
    m = THREAD_ID_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _strip_thread_tag(text: str) -> str:
    """
    Убираем служебный префикс '#123' в начале сообщения (если он там),
    чтобы в виджете отображался чистый текст.
    """
    if not text:
        return ""
    # Удаляем "#123" в начале + возможные пробелы/двоеточия/тире после
    return re.sub(r"^\s*#\d+\s*[:\-–—]?\s*", "", text).strip()


def resolve_thread_for_vk_message(text: str) -> tuple[ChatThread | None, int | None, str]:
    """
    Возвращает:
      (thread or None, thread_id or None, clean_text)

    Правила:
    1) Если в тексте есть #<id> — ищем ChatThread по этому id.
    2) Если не нашли — fallback на последний активный (closed_at IS NULL).
    3) clean_text: без #<id> (если он был префиксом в начале).
    """
    thread_id = _find_thread_id_in_text(text)
    clean_text = _strip_thread_tag(text) if thread_id else (text or "").strip()

    thread = None
    if thread_id:
        thread = ChatThread.objects.filter(id=thread_id).first()

    if not thread:
        thread = ChatThread.objects.filter(closed_at__isnull=True).order_by("-created_at").first()

    return thread, thread_id, clean_text


@csrf_exempt
@require_POST
def vk_callback(request):
    # 1) Парсим JSON — если что-то не так, VK всё равно надо ответить "ok"
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        logger.exception("VK callback: invalid JSON")
        return _vk_text("ok")

    event_type = data.get("type")

    # 2) confirmation: возвращаем код из settings/env
    if event_type == "confirmation":
        code = getattr(settings, "VK_CALLBACK_CONFIRMATION", "") or ""
        if not code:
            logger.error("VK callback: VK_CALLBACK_CONFIRMATION is empty in settings/env")
            return _vk_text("ok")
        return _vk_text(code)

    # 3) входящее сообщение
    if event_type == "message_new":
        try:
            msg = data["object"]["message"]
        except Exception:
            logger.exception("VK callback: malformed payload for message_new")
            return _vk_text("ok")

        vk_msg_id = msg.get("id")
        text = (msg.get("text") or "").strip()
        peer_id = msg.get("peer_id")
        from_id = msg.get("from_id")

        logger.info("VK message_new received: id=%s peer_id=%s from_id=%s text=%r",
                    vk_msg_id, peer_id, from_id, text)

        # Идемпотентность по vk_message_id
        if vk_msg_id is not None:
            if ChatMessage.objects.filter(vk_message_id=str(vk_msg_id)).exists():
                return _vk_text("ok")

        # Выбираем тред по #<id>, иначе fallback
        thread, thread_id, clean_text = resolve_thread_for_vk_message(text)

        if not thread:
            logger.warning("VK callback: no thread resolved, dropping message: %r", text)
            return _vk_text("ok")

        # Если после удаления '#id' текст пустой — можно не писать в БД
        if not clean_text:
            logger.info("VK callback: empty message after stripping thread tag, ignored. raw=%r", text)
            return _vk_text("ok")

        try:
            ChatMessage.objects.create(
                thread=thread,
                sender="operator",
                text=clean_text,
                vk_message_id=str(vk_msg_id) if vk_msg_id is not None else None,
            )
        except Exception:
            logger.exception("VK callback: failed to create ChatMessage")
            return _vk_text("ok")

        # (Опционально) если в ChatThread есть last_operator_activity — обновим
        if hasattr(thread, "last_operator_activity"):
            try:
                thread.last_operator_activity = timezone.now()
                thread.save(update_fields=["last_operator_activity"])
            except Exception:
                logger.exception("VK callback: failed to update last_operator_activity")

        return _vk_text("ok")

    # все остальные события
    return _vk_text("ok")
