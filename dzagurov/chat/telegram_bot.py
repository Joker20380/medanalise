# chat/telegram_bot.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from .models import ChatThread, ChatMessage

log = logging.getLogger(__name__)

# UUID треда вытаскиваем из текста "карточки"
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)

@dataclass
class BotCfg:
    token: str
    operators_chat_id: int
    default_thread_id: Optional[int] = None  # message_thread_id для Topics

def get_cfg() -> BotCfg:
    # читаем из settings/env
    return BotCfg(
        token=getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "",
        operators_chat_id=int(getattr(settings, "TELEGRAM_OPERATORS_CHAT_ID", 0) or 0),
        default_thread_id=(getattr(settings, "TELEGRAM_DEFAULT_THREAD_ID", 0) or None),
    )

# ---------- Persistence helpers ----------

@sync_to_async
def _save_operator_reply(thread_uuid: str, text: str) -> tuple[ChatThread, ChatMessage]:
    t = ChatThread.objects.get(uuid=thread_uuid)
    m = ChatMessage.objects.create(thread=t, sender="operator", text=(text or "")[:2000])
    return t, m

@sync_to_async
def _admin_url_for_thread(t: ChatThread) -> str:
    return f"/admin/chat/chatthread/{t.id}/change/"

# ---------- Handlers ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text("Бот на линии. Отвечайте реплаем на карточку треда.")
    if update.effective_chat:
        await update.message.reply_text(f"[debug] chat_id = {update.effective_chat.id}")

async def log_any(update: Update, _):
    """Диагностический логгер — показывает любые входящие апдейты."""
    try:
        chat = update.effective_chat.id if update.effective_chat else None
        txt = (update.message and update.message.text) or ""
        ref = bool(update.message and update.message.reply_to_message)
        log.info("RAW chat=%s reply=%s text=%r", chat, ref, txt[:120])
    except Exception:
        pass

async def operator_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    # проверим, что реплай на СООБЩЕНИЕ БОТА
    ref = msg.reply_to_message
    ref_from_bot = bool(ref.from_user and ref.from_user.is_bot)
    if not ref_from_bot:
        log.warning("operator_reply: reply is not to bot message (skip)")
        return

    # берём текст/капшен карточки, логируем «что видим»
    ref_txt = (getattr(ref, "text", None) or getattr(ref, "caption", None) or "")[:4000]
    log.info("operator_reply: incoming chat=%s ref_from_bot=%s ref_head=%r",
             update.effective_chat.id if update.effective_chat else None,
             ref_from_bot, ref_txt[:120])

    # парсим UUID
    m = UUID_RE.search(ref_txt)
    if not m:
        log.warning("operator_reply: UUID not found in replied message")
        return
    thread_uuid = m.group(0)
    log.info("operator_reply: parsed uuid=%s", thread_uuid)

    text = (msg.text or "").strip()
    if not text:
        log.info("operator_reply: empty text, skip")
        return
    if len(text) > 2000:
        text = text[:2000]

    try:
        t, saved = await _save_operator_reply(thread_uuid, text)
    except ChatThread.DoesNotExist:
        log.warning("operator_reply: thread %s not found in DB", thread_uuid)
        return
    except Exception as e:
        log.exception("operator_reply: DB persist failed: %s", e)
        return

    # пуш в WS (если слой настроен)
    try:
        layer = get_channel_layer()
        if not layer:
            log.warning("operator_reply: no channel layer configured, skip WS push")
            return
        await layer.group_send(
            f"thread_{t.uuid}",
            {"type": "broadcast", "message": {
                "id": saved.id, "text": saved.text, "sender": saved.sender, "ts": saved.created_at.isoformat()
            }},
        )
        log.info("operator_reply: pushed to WS (thread=%s, msg_id=%s)", t.uuid, saved.id)
    except Exception as e:
        log.exception("operator_reply: WS push failed: %s", e)


async def send_to_operators(thread: ChatThread, text: str):
    """
    Одноразовая отправка 'карточки' в операторский чат:
    - Thread UUID (для reply-мэппинга)
    - текст клиента
    - ссылка на админку
    Если в группе включены Topics — шлём в default_thread_id (message_thread_id).
    """
    cfg = get_cfg()
    if not cfg.token or not cfg.operators_chat_id:
        log.warning("send_to_operators: token/chat_id not configured")
        return

    app = Application.builder().token(cfg.token).build()
    await app.initialize()
    await app.start()

    admin_url = await _admin_url_for_thread(thread)
    body = (
        "Новое сообщение от посетителя\n"
        f"Thread UUID: {thread.uuid}\n"
        f"{text}\n\n"
        "Ответьте реплаем на это сообщение.\n"
        f"Админка: {admin_url}"
    )

    try:
        if cfg.default_thread_id is not None:
            await app.bot.send_message(
                chat_id=cfg.operators_chat_id,
                message_thread_id=cfg.default_thread_id,
                text=body,
            )
        else:
            await app.bot.send_message(
                chat_id=cfg.operators_chat_id,
                text=body,
            )
        log.info("send_to_operators: sent to chat=%s thread=%s", cfg.operators_chat_id, cfg.default_thread_id)
    except Exception as e:
        log.exception("send_to_operators failed: %s", e)
    finally:
        await app.stop()
        await app.shutdown()

def build_app() -> Application:
    """
    Основной Application для длительного запуска (polling/webhook).
    На время диагностики ловим ЛЮБЫЕ реплаи без доп. фильтров.
    """
    cfg = get_cfg()
    app = Application.builder().token(cfg.token).build()

    app.add_handler(CommandHandler("start", cmd_start))

    # Диагностический лог всех апдейтов — первым
    app.add_handler(MessageHandler(filters.ALL, log_any))

    # ВАЖНО: временно без filters.Chat(...) и без ~filters.COMMAND, чтобы ничего не отсечь
    app.add_handler(MessageHandler(filters.REPLY, operator_reply))

    # Когда всё заработает стабильно, можешь ужесточить обратно:
    # app.add_handler(MessageHandler(filters.Chat(cfg.operators_chat_id) & filters.REPLY & ~filters.COMMAND, operator_reply))

    return app

def run_bot():
    """Запуск polling. Вызывается management-командой `run_telebot`."""
    cfg = get_cfg()
    if not cfg.token or not cfg.operators_chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_OPERATORS_CHAT_ID не заданы")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    log.info("Starting Telegram bot (polling) for chat_id=%s", cfg.operators_chat_id)

    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)
