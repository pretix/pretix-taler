import logging
import time
from datetime import timedelta
from django.dispatch import receiver
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import OrderPayment
from pretix.base.payment import PaymentException
from pretix.base.signals import periodic_task, register_payment_providers

from pretix_taler.models import TalerOrder

logger = logging.getLogger(__name__)


@receiver(register_payment_providers, dispatch_uid="payment_taler")
def register_payment_provider(sender, **kwargs):
    from .payment import Taler

    return Taler


@receiver(periodic_task, dispatch_uid="payment_taler_periodic_check")
@scopes_disabled()
def register_periodic_task(sender, **kwargs):
    for t in TalerOrder.objects.filter(poll_until__gte=now()).select_related(
        "payment", "payment__order", "payment__order__event"
    ):
        try:
            t.payment.payment_provider._query_and_process(t.payment)
        except PaymentException:
            continue
        else:
            if t.payment.state in (
                OrderPayment.PAYMENT_STATE_CREATED,
                OrderPayment.PAYMENT_STATE_PENDING,
            ):
                pay_deadline = t.payment.info_data.get("pay_deadline")
                expired = (
                    not pay_deadline and now() - t.payment.created > timedelta(hours=1)
                ) or (pay_deadline and pay_deadline["t_s"] < time.time())
                if expired:
                    t.payment.fail(log_data={"cause": "expired"})
