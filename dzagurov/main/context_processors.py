from .forms import SubscriberForm
from typing import Dict, Any, Optional
from django.http import HttpRequest
from django.apps import apps
import logging
from django.conf import settings
from .forms import CustomLoginForm


def vk_settings(request):
    return {
        "VK_GROUP_ID": getattr(settings, "VK_GROUP_ID", 0),
    }


def auth_popups(request):
    login_form = None
    if not request.user.is_authenticated:
        login_form = CustomLoginForm(request=request)
    return {
        "login_form": login_form,
    }

def subscriber_form(request):
    return {'subscriber_form': SubscriberForm()}
    



logger = logging.getLogger(__name__)

def current_office(request: HttpRequest) -> Dict[str, Any]:
    """
    Глобальный контекст для top-bar:
    - читает cookie 'office_id'
    - тянет список офисов
    - выбирает текущий: cookie -> is_main -> первый из списка
    Пишет диагностику в логи, чтобы исключить «тихий» провал.
    """
    Empty = type("Empty", (), {
        "id": None,
        "name": "Основной офис",
        "phone": "+7(918)000-00-00",
        "email": "youremail@email.ru",
        "is_main": True,
    })

    def empty(reason: str):
        logger.warning("current_office: fallback empty payload (%s)", reason)
        return {"current_office": Empty(), "offices_for_switcher": []}

    try:
        Contact = apps.get_model("main", "Contact")
        if Contact is None:
            return empty("apps.get_model returned None (check app_label/model name)")

        office_id_raw: Optional[str] = request.COOKIES.get("office_id")

        qs = (Contact.objects
              .select_related("location")
              )

        total = qs.count()
        if total == 0:
            return empty("no Contact rows in DB")

        default_office = qs.filter(is_main=True).first()
        chosen = None
        if office_id_raw and str(office_id_raw).isdigit():
            chosen = qs.filter(id=int(office_id_raw)).first()
            if chosen is None:
                logger.info("current_office: cookie id=%s not found, fallback", office_id_raw)

        current = chosen or default_office or qs.order_by("-is_main", "name").first()
        if current is None:
            return empty("no current resolved (unexpected)")

        offices = list(qs.order_by("-is_main", "name"))

        logger.debug(
            "current_office: resolved id=%s, total=%s, default_id=%s, cookie=%s",
            getattr(current, "id", None), total, getattr(default_office, "id", None), office_id_raw
        )

        return {"current_office": current, "offices_for_switcher": offices}

    except Exception as ex:
        logger.exception("current_office: exception")
        return empty(f"exception: {ex!r}")



