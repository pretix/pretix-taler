from django.urls import path

from . import views

event_patterns = [
    path(
        "_taler/pay/<str:order>/<str:hash>/<int:payment>/",
        views.ReturnView.as_view(),
        name="return",
    ),
]
