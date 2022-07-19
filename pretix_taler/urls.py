from django.conf.urls import url

from . import views

event_patterns = [
    url(
        r"^_taler/pay/(?P<order>[^/]+)/(?P<hash>[^/]+)/(?P<payment>[0-9]+)/$",
        views.ReturnView.as_view(),
        name="return",
    ),
]
