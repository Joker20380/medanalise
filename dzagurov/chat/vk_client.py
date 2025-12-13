import logging
import random
import requests

from django.conf import settings

logger = logging.getLogger(__name__)


VK_API_URL = "https://api.vk.com/method/messages.send"


def send_vk_message(text: str, thread_id: int, visitor_name: str | None = None):
    """
    Отправляет сообщение в VK от имени сообщества
    в указанный peer_id (оператор/беседа).

    Никаких исключений наружу не бросаем, только логируем.
    """

    token = getattr(settings, "VK_GROUP_TOKEN", "")
    peer_id = getattr(settings, "VK_OPERATOR_PEER_ID", 0)
    api_version = getattr(settings, "VK_API_VERSION", "5.236")

    if not token or not peer_id:
        logger.warning("VK: token or peer_id not configured, skip sending")
        return

    # Собираем удобный текст для оператора
    header = f"[Чат с сайта #{thread_id}]"
    if visitor_name:
        header += f" {visitor_name}"

    full_text = f"{header}\n\n{text}"

    params = {
        "access_token": token,
        "v": api_version,
        "peer_id": peer_id,
        "random_id": random.randint(1, 2**31 - 1),
        "message": full_text,
    }

    try:
        resp = requests.post(VK_API_URL, data=params, timeout=5)
        data = resp.json()
        if "error" in data:
            logger.error("VK messages.send error: %s", data["error"])
        else:
            logger.debug("VK messages.send ok: %s", data)
    except Exception as ex:
        logger.exception("VK messages.send exception: %s", ex)
