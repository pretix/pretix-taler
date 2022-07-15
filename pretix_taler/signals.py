import logging
from django.dispatch import receiver
from pretix.base.signals import register_payment_providers

logger = logging.getLogger(__name__)


@receiver(register_payment_providers, dispatch_uid="payment_taler")
def register_payment_provider(sender, **kwargs):
    from .payment import Taler

    return Taler
