import hashlib
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from pretix.base.models import Order, OrderPayment
from pretix.base.payment import PaymentException
from pretix.multidomain.urlreverse import eventreverse
from pretix.presale.views import EventViewMixin


class TalerOrderView:
    def dispatch(self, request, *args, **kwargs):
        try:
            self.order = request.event.orders.get(code=kwargs["order"])
            if (
                hashlib.sha1(self.order.secret.lower().encode()).hexdigest()
                != kwargs["hash"].lower()
            ):
                raise Http404("")
        except Order.DoesNotExist:
            # Do a hash comparison as well to harden timing attacks
            if (
                "abcdefghijklmnopq".lower()
                == hashlib.sha1("abcdefghijklmnopq".encode()).hexdigest()
            ):
                raise Http404("")
            else:
                raise Http404("")
        return super().dispatch(request, *args, **kwargs)

    def _redirect_to_order(self):
        return redirect(
            eventreverse(
                self.request.event,
                "presale:event.order",
                kwargs={"order": self.order.code, "secret": self.order.secret},
            )
            + ("?paid=yes" if self.order.status == Order.STATUS_PAID else "")
        )


@method_decorator(xframe_options_exempt, "dispatch")
@method_decorator(csrf_exempt, "dispatch")
class ReturnView(TalerOrderView, EventViewMixin, TemplateView):
    template_name = "pretix_taler/pay.html"

    def get(self, request, *args, **kwargs):
        self.payment = get_object_or_404(
            self.order.payments,
            pk=self.kwargs["payment"],
            provider__startswith="taler",
        )
        pp = self.payment.payment_provider

        if self.payment.state != OrderPayment.PAYMENT_STATE_PENDING:
            if "ajax" in request.GET:
                return JsonResponse({"refresh": True})
            return self._redirect_to_order()
        else:
            try:
                pp._query_and_process(self.payment)
            except PaymentException as e:
                messages.error(self.request, str(e))
                if "ajax" in request.GET:
                    return JsonResponse({"refresh": True})
                self._redirect_to_order()
        if "ajax" in request.GET:
            return JsonResponse({"refresh": False})
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "payment": self.payment,
            "order": self.payment.order,
            "taler_url": self.payment.info_data["taler_pay_uri"],
        }
