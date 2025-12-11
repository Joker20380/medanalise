# lab/api_booking.py
import datetime as dt

from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from main.models import Contact, Appointment


def _iter_slots(start: dt.time, end: dt.time, step_min: int, date: dt.date):
    """Итерируем слоты, поддерживаем ночные смены (start > end)."""
    step = dt.timedelta(minutes=step_min or 20)

    def _walk(d, t_from, t_to):
        cur = dt.datetime.combine(d, t_from)
        end_dt = dt.datetime.combine(d, t_to)
        while cur <= end_dt:
            yield cur.date(), cur.time()
            cur += step

    if start <= end:
        yield from _walk(date, start, end)
    else:
        # пример: 22:00–02:00 (часть сегодня, часть — завтра)
        yield from _walk(date, start, dt.time(23, 59))
        next_day = date + dt.timedelta(days=1)
        yield from _walk(next_day, dt.time(0, 0), end)


@require_GET
def api_contact_slots(request):
    """
    GET /lab/api/slots/?contact_id=...&date=YYYY-MM-DD
    Возвращает доступные слоты на указанную дату.
    """
    contact_id = request.GET.get("contact_id")
    date_s = request.GET.get("date")
    if not contact_id or not date_s:
        return HttpResponseBadRequest("contact_id and date are required")

    day = parse_date(date_s)
    if not day:
        return HttpResponseBadRequest("invalid date")

    try:
        contact = Contact.objects.get(pk=contact_id)
    except Contact.DoesNotExist:
        return HttpResponseBadRequest("contact not found")

    # Настройка длины слота из Contact (если нет поля — 20 минут)
    slot_min = getattr(contact, "booking_slot_minutes", None) or 20
    if hasattr(contact, "booking_enabled") and not contact.booking_enabled:
        return JsonResponse({"contact_name": str(contact), "date": date_s, "slots": []})

    open_t, close_t, is_closed, _ = contact.get_today_hours(day)
    if is_closed or not (open_t and close_t):
        return JsonResponse({"contact_name": str(contact), "date": date_s, "slots": []})

    # Итерируем все слоты и фильтруем по выбранной дате (без части «после полуночи»)
    all_slots = list(_iter_slots(open_t, close_t, slot_min, day))
    day_slots = [t.strftime("%H:%M") for d, t in all_slots if d == day]

    # Уберём занятые
    busy = set(
        Appointment.objects.filter(
            contact=contact,
            date=day,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        ).values_list("time", flat=True)
    )
    free = [s for s in day_slots if dt.time.fromisoformat(s) not in busy]

    return JsonResponse({"contact_name": str(contact), "date": date_s, "slots": free})


@require_POST
@transaction.atomic
def api_book_appointment(request):
    """
    POST /lab/api/book/
    form-data: contact_id, date(YYYY-MM-DD), time(HH:MM), note?
    """
    contact_id = request.POST.get("contact_id")
    date_s = request.POST.get("date")
    time_s = request.POST.get("time")
    note = request.POST.get("note") or ""

    if not (contact_id and date_s and time_s):
        return HttpResponseBadRequest("contact_id, date, time are required")

    try:
        contact = Contact.objects.select_for_update().get(pk=contact_id)
    except Contact.DoesNotExist:
        return HttpResponseBadRequest("contact not found")

    day = parse_date(date_s)
    try:
        t = dt.time.fromisoformat(time_s)
    except Exception:
        return HttpResponseBadRequest("invalid time")

    # Повторная проверка занятости
    exists = Appointment.objects.filter(
        contact=contact,
        date=day,
        time=t,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
    ).exists()
    if exists:
        return JsonResponse({"ok": False, "error": "slot_taken"}, status=409)

    appt = Appointment.objects.create(
        contact=contact,
        user=request.user if request.user.is_authenticated else None,
        user_profile=getattr(
            getattr(request.user, "userprofile", None),
            "pk",
            None,
        )
        and request.user.userprofile
        or None,
        date=day,
        time=t,
        status=Appointment.Status.PENDING,
        note=note,
    )
    return JsonResponse({"ok": True, "id": appt.id, "status": appt.status})
