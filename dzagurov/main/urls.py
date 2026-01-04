from django.urls import path, re_path
from django.views.decorators.csrf import csrf_exempt
from .views import *

from django.urls import path
from django.shortcuts import render
from django_admin_geomap import geomap_context
from users.models import Location

from lab import api_booking



urlpatterns = [
                path('', Index.as_view(), name='index'),
                path('analysis/', Analysis.as_view(), name='analysis'),
                path('contacts/', ContactsView.as_view(), name='contacts'),
                path('subscribe/', Subscribe, name='subscribe'),
                path('unsubscribe/', Unsubscribe, name='unsubscribe_request'),
    			path('unsubscribe/confirm/<str:token>/', Unsubscribe_confirm, name='unsubscribe_confirm'),
    			path("vk-test/", TemplateView.as_view(template_name="vk_test.html")),
    			path('doctors/', Doctors.as_view(), name='doctors'),
    			path('documents/', Documents.as_view(), name='documents'),
				path('blog/', Blog.as_view(), name='blog'),
				path('conf/', Confidential_information.as_view(), name='conf'),
                path("api/contacts/<int:pk>/summary/", contact_summary, name="contact_summary"),
                path("api/slots/", api_booking.api_contact_slots, name="api_slots"),
    			path("api/book/", api_booking.api_book_appointment, name="api_book"),
              ]