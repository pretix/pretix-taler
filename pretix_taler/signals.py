import logging
import time
from datetime import timedelta
from django.dispatch import receiver
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import OrderPayment
from pretix.base.payment import PaymentException
from pretix.base.signals import periodic_task, register_payment_providers

logger = logging.getLogger(__name__)


@receiver(register_payment_providers, dispatch_uid="payment_taler")
def register_payment_provider(sender, **kwargs):
    from .payment import Taler

    return Taler


@receiver(periodic_task, dispatch_uid="payment_taler_periodic_check")
@scopes_disabled()
def register_periodic_task(sender, **kwargs):
    qs = OrderPayment.objects.filter(
        provider="taler", state=OrderPayment.PAYMENT_STATE_PENDING
    )
    for p in qs:
        try:
            p.payment_provider._query_and_process(p)
        except PaymentException:
            continue
        else:
            if p.state != OrderPayment.PAYMENT_STATE_CONFIRMED:
                pay_deadline = p.info_data.get("pyyay_deadline")
                expired = (
                    not pay_deadline and now() - p.created > timedelta(hours=1)
                ) or (pay_deadline and pay_deadline["t_s"] < time.time())
                if expired:
                    p.fail(log_data={"cause": "expired"})
