from django.db import models
from django.contrib.auth.models import User
from phonenumber_field.modelfields import PhoneNumberField
from django_admin_geomap import GeoItem
from main.fields import WEBPField
import uuid


def image_folder(instance, filename):
    return "photos/{}.webp".format(uuid.uuid4().hex)


class Location(models.Model, GeoItem):
    name = models.CharField(max_length=255)
    lon = models.FloatField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def geomap_longitude(self):
        return '' if self.lon is None else str(self.lon)

    @property
    def geomap_latitude(self):
        return '' if self.lat is None else str(self.lat)

    @property
    def geomap_popup_view(self):
        return self._build_popup_html()

    @property
    def geomap_popup_edit(self):
        return self.geomap_popup_view

    @property
    def geomap_popup_common(self):
        return self.geomap_popup_view

    @property
    def geomap_icon(self):
        # Верни путь к кастомной иконке, если нужно
        return "https://maps.google.com/mapfiles/ms/micons/red.png"
        
    def _build_popup_html(self) -> str:
        """
        Собираем HTML: заголовок локации + связанные контакты.
        related_name у модели Contact — 'Contact' (с заглавной буквы).
        """
        contacts = getattr(self, 'Contact', None)
        rows = [f"<strong>{self.name}</strong>"]
        if contacts is not None:
            items = []
            for c in contacts.all():
                line = [f"<strong>{c.name}</strong>"]
                if c.address:
                    line.append(c.address)
                phone_bits = []
                if c.phone:
                    phone_bits.append(f"📞 {c.phone}")
                if c.email:
                    phone_bits.append(f"✉️ {c.email}")
                if phone_bits:
                    line.append(" | ".join(phone_bits))
                items.append("<br>".join(line))
            if items:
                rows.append("<hr style='margin:6px 0'>")
                rows.append("<br>".join(items))
        return "<br>".join(rows)

    @property
    def geojson_coordinates(self):
        """Возвращает координаты в формате GeoJSON или None."""
        if self.lon is not None and self.lat is not None:
            return {
                "type": "Point",
                "coordinates": [self.lon, self.lat]
            }
        return None


class UserProfile(models.Model):
    class Genders(models.TextChoices):
        UNDEFINED = 'U', 'не выбран'
        MALE = 'M', 'мужской'
        FEMALE = 'F', 'женский'

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    gender = models.CharField(
        max_length=1,
        choices=Genders.choices,
        default=Genders.UNDEFINED,
        verbose_name='Пол'
    )
    image = WEBPField(
        upload_to=image_folder,
        verbose_name="Фото",
        null=True,
        blank=True
    )
    address = models.CharField(max_length=255, null=True, blank=True)
    phone_number = PhoneNumberField(null=True, blank=True)
    patronymic = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Отчество"
    )
    birth = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    merit = models.TextField(blank=True, verbose_name="Заслуги", null=True)

    def __str__(self):
        try:
            if getattr(self, "user", None):
                full = (self.user.get_full_name() or "").strip()
                if full:
                    return full
                if self.user.username:
                    return self.user.username
        except Exception:
            pass
        return f"Профиль #{self.pk}"

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'
