import uuid
from django.db.models import Count, Q, Prefetch
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.views.generic import ListView, TemplateView
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse, Http404
from .forms import SubscriberForm, UnsubscriberForm
from .models import (
    News,
    Documents,
    Subscriber,
    ContactGroup,
    Contact,
    ContactRequest,
)

from lab.models import (
    Panel,
    PanelCategory,
    PanelPreanalytic,
)

from django_admin_geomap import geomap_context
from users.models import Location


PREANALYTIC_QS = PanelPreanalytic.objects.select_related('panel').order_by('id')
PREANALYTIC_REL = 'preanalytics'


def _try_reverse(name, *args, **kwargs):
    try:
        return reverse(name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        return None


class Index(TemplateView):
    template_name = "dzagurov/index.html"
    PANEL_LIMIT = 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        p_cat = (self.request.GET.get("p_cat") or "").strip() or None
        p_q = (self.request.GET.get("p_q") or "").strip() or None

        categories_qs = (
            PanelCategory.objects
            .annotate(total=Count("panels"))
            .order_by("sorter", "name")
        )

        selected_category = None
        p_cat_name = None
        if p_cat:
            selected_category = categories_qs.filter(code=p_cat).first()
            p_cat_name = selected_category.name if selected_category else None

        panel_categories = [
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "total": c.total,
                "active": bool(selected_category and selected_category.id == c.id),
            }
            for c in categories_qs
        ]

        panels_qs = (
            Panel.objects
            .select_related("category", "preanalytic")
            .prefetch_related(
                "panel_materials__biomaterial",
                "panel_materials__container_type",
                "panel_tests__test",
                "services",
            )
            .order_by("code")
        )

        if p_cat:
            panels_qs = panels_qs.filter(category__code=p_cat)

        if p_q:
            q = p_q
            panels_qs = panels_qs.filter(
                Q(code__icontains=q) |
                Q(name__icontains=q) |
                Q(category_code__icontains=q) |
                Q(panel_tests__test__name__icontains=q)
            ).distinct()

        panel_found_total = panels_qs.count()
        panel_list = list(panels_qs[: self.PANEL_LIMIT])

        hero_contacts = Contact.objects.all().order_by("order", "name")[:200]

        panel_catalog_url = None

        ctx.update({
            "p_cat": p_cat,
            "p_q": p_q,
            "p_cat_name": p_cat_name,
            "selected_category": selected_category,

            "panel_categories": panel_categories,

            "panel_list": panel_list,
            "panel_found_total": panel_found_total,
            "panel_limit": self.PANEL_LIMIT,
            "panel_catalog_url": panel_catalog_url,

            "hero_contacts": hero_contacts,
        })
        return ctx


class Doctors(ListView):
    queryset = News.objects.order_by('-time_update')
    model = News
    template_name = 'dzagurov/doctors.html'
    context_object_name = 'news'
    paginate_by = 6


class Analysis(ListView):
    queryset = News.objects.order_by('-time_update')
    model = News
    template_name = 'dzagurov/analysis.html'
    context_object_name = 'news'
    paginate_by = 6
    PANEL_LIMIT = 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        p_cat_code = (self.request.GET.get("p_cat") or "").strip() or None
        p_q = (self.request.GET.get("p_q") or "").strip() or None

        all_cats = list(
            PanelCategory.objects.only("id", "code", "name", "parent_id", "sorter").order_by("sorter", "name")
        )
        by_id = {c.id: c for c in all_cats}
        children = {}
        roots = []
        for c in all_cats:
            if c.parent_id:
                children.setdefault(c.parent_id, []).append(c.id)
            else:
                roots.append(c.id)

        def subtree_ids(root_id: int) -> list[int]:
            out = [root_id]
            stack = [root_id]
            while stack:
                nid = stack.pop()
                for ch in children.get(nid, ()):
                    out.append(ch)
                    stack.append(ch)
            return out

        subtree_map = {rid: subtree_ids(rid) for rid in roots}
        if p_cat_code:
            sel_for_map = next((c for c in all_cats if c.code == p_cat_code), None)
            if sel_for_map and sel_for_map.id not in subtree_map:
                subtree_map[sel_for_map.id] = subtree_ids(sel_for_map.id)

        per_cat_counts = Panel.objects.values("category_id").annotate(cnt=Count("id"))
        count_by_cat_id = {row["category_id"]: row["cnt"] for row in per_cat_counts}

        def total_for_cat(root_id: int) -> int:
            return sum(count_by_cat_id.get(cid, 0) for cid in subtree_map.get(root_id, [root_id]))

        panel_categories = []
        selected_category = None
        for rid in roots:
            c = by_id[rid]
            total = total_for_cat(rid)
            active = (p_cat_code == c.code)
            if active:
                selected_category = c
            panel_categories.append({
                "code": c.code,
                "name": c.name,
                "total": total,
                "active": active,
            })

        panels_qs = (
            Panel.objects
            .select_related("category", "preanalytic")
            .prefetch_related(
                "panel_materials__biomaterial",
                "panel_materials__container_type",
                "panel_tests__test",
                "services",
            )
        )

        if p_q:
            panels_qs = panels_qs.filter(
                Q(code__icontains=p_q) |
                Q(name__icontains=p_q) |
                Q(category_code__icontains=p_q) |
                Q(panel_tests__test__name__icontains=p_q)
            ).distinct()

        if p_cat_code:
            sel = selected_category or next((c for c in all_cats if c.code == p_cat_code), None)
            if sel:
                cat_ids = subtree_map.get(sel.id, [sel.id])
                panels_qs = panels_qs.filter(category_id__in=cat_ids)

        panels_qs = panels_qs.order_by("code")
        panel_found_total = panels_qs.count()
        panel_list = list(panels_qs[: self.PANEL_LIMIT])

        ctx.update({
            "panel_categories": panel_categories,
            "panel_list": panel_list,
            "panel_found_total": panel_found_total,
            "p_cat": p_cat_code,
            "p_q": p_q,
            "selected_category": selected_category,
            "p_cat_name": selected_category.name if selected_category else "",
            "panel_limit": self.PANEL_LIMIT,
            "panel_catalog_url": None,
        })
        return ctx



class Blog(ListView):
    queryset = News.objects.order_by('-time_update')
    model = News
    template_name = 'dzagurov/blog.html'
    context_object_name = 'news'
    paginate_by = 6

    @staticmethod
    def news_all():
        return News.objects.order_by('-time_update')


class Confidential_information(ListView):
    model = Documents
    template_name = 'dzagurov/confidential_information.html'
    context_object_name = 'news'

    @staticmethod
    def post_last3():
        return News.objects.reverse()[:3]

    @staticmethod
    def news_all_conf():
        return News.objects.filter(title='Политика конфиденциальности')


def Subscribe(request):
    if request.method == 'POST':
        form = SubscriberForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Вы успешно подписались на рассылку!')
            return redirect('index')
    else:
        form = SubscriberForm()
    return render(request, 'diagnost/index.html', {'form': form})


def Unsubscribe(request):
    if request.method == 'POST':
        form = UnsubscriberForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                subscriber = Subscriber.objects.get(email=email, is_active=True)
                subscriber.unsubscribe_token = uuid.uuid4().hex
                subscriber.save()
                unsubscribe_url = request.build_absolute_uri(
                    f"/unsubscribe/confirm/{subscriber.unsubscribe_token}/"
                )
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    'Подтверждение отписки',
                    f'Для подтверждения отписки перейдите по ссылке: {unsubscribe_url}',
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
                messages.success(request, 'На ваш email отправлено письмо с подтверждением отписки.')
            except Subscriber.DoesNotExist:
                messages.error(request, 'Подписка с таким email не найдена.')
            return redirect('unsubscribe_request')
    else:
        form = UnsubscriberForm()
    return render(request, 'dzagurov/unsubscribe_form.html', {'form': form})


def Unsubscribe_confirm(request, token):
    subscriber = get_object_or_404(Subscriber, unsubscribe_token=token, is_active=True)
    subscriber.is_active = False
    subscriber.unsubscribe_token = None
    subscriber.save()
    messages.success(request, 'Вы успешно отписались от рассылки.')
    return render(request, 'dzagurov/unsubscribe_success.html')


class ContactsView(TemplateView):
    template_name = 'dzagurov/contacts.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        main_contact = (
            Contact.objects
            .filter(is_main=True)
            .select_related('location')
            .first()
        )

        contacts_qs = (
            Contact.objects
            .select_related('location')
            .prefetch_related('business_hours', 'business_hour_overrides')
            .order_by('order', 'name')
        )

        contact_groups = (
            ContactGroup.objects
            .prefetch_related(Prefetch('contacts', queryset=contacts_qs))
            .all()
        )

        geomap_qs = (
            Location.objects
            .exclude(lat__isnull=True).exclude(lon__isnull=True)
            .prefetch_related('Contact')  # обратная связь: related_name='Contact'
            .distinct()
        )

        geo_ctx = geomap_context(
            geomap_qs,
            auto_zoom="12",
            map_height="800px",
        )

        offices = (
            geomap_qs
            .annotate(contacts_count=Count('Contact'))
            .order_by('name')
        )

        today = timezone.localdate()
        for g in contact_groups:
            for c in g.contacts.all():
                ot, ct, is_closed, note = c.get_today_hours(today)
                c.today_open_time = ot
                c.today_close_time = ct
                c.today_is_closed = bool(is_closed)
                c.today_note = note or ""
                c.is_open_flag = c.is_open_now()

                week_map = {bh.weekday: bh for bh in c.business_hours.all()}
                c.hours_week = []
                for wd in range(7):
                    bh = week_map.get(wd)
                    c.hours_week.append({
                        "weekday": wd,
                        "open_time": getattr(bh, "open_time", None),
                        "close_time": getattr(bh, "close_time", None),
                        "is_closed": getattr(bh, "is_closed", True) if bh else True,
                        "note": getattr(bh, "note", "") if bh else "",
                    })

        context.update({
            'main_contact': main_contact,
            'contact_groups': contact_groups,
            'offices': offices,
            'today_weekday': today.weekday(),
            **geo_ctx,
        })
        return context

    def post(self, request, *args, **kwargs):
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        message = request.POST.get('message')
        contact_id = request.POST.get('contact')

        if not all([name, email, message]):
            messages.error(request, 'Пожалуйста, заполните все обязательные поля')
            return self.get(request, *args, **kwargs)

        contact = None
        if contact_id:
            try:
                contact = Contact.objects.get(id=contact_id)
            except Contact.DoesNotExist:
                contact = None

        ContactRequest.objects.create(
            name=name,
            email=email,
            phone=phone,
            message=message,
            contact=contact
        )

        messages.success(request, 'Ваше сообщение успешно отправлено!')
        return redirect('contacts')


def contact_summary(request, pk: int):
    try:
        c = Contact.objects.only("id", "name", "phone", "email").get(pk=pk)
    except Contact.DoesNotExist:
        raise Http404
    return JsonResponse({
        "id": c.id,
        "name": c.name,
        "phone": c.phone or "",
        "email": c.email or "",
    })
