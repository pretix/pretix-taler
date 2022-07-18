import hashlib
import json
import logging
from datetime import timedelta

import requests
import time
from collections import OrderedDict
from decimal import Decimal
from django import forms
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SecretKeySettingsField
from pretix.base.models import Event, OrderPayment, OrderRefund
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import SettingsSandbox
from pretix.multidomain.urlreverse import build_absolute_uri, eventreverse
from urllib.parse import urljoin

from pretix_taler.models import TalerOrder

logger = logging.getLogger(__name__)


class Taler(BasePaymentProvider):
    identifier = "taler"
    verbose_name = _("Taler")
    public_name = _("Taler")
    abort_pending_allowed = True

    @property
    def settings_form_fields(self):
        fields = [
            (
                "merchant_api_url",
                forms.URLField(
                    label=_("Merchant backend URL"),
                ),
            ),
            (
                "merchant_api_instance",
                forms.CharField(
                    label=_("Merchant instance"),
                    initial="default",
                ),
            ),
            (
                "merchant_api_key",
                SecretKeySettingsField(
                    label=_("Merchant API key"),
                ),
            ),
            (
                "max_pay_deadline",
                forms.IntegerField(
                    label=_("Maximum payment deadline in minutes"),
                    help_text=_(
                        "The payment will be kept in escrow for this time frame. Refunds are not possible "
                        "afterwards."
                    ),
                    initial=60,
                    min_value=2,
                    max_value=10080,
                ),
            ),
            (
                "refund_delay",
                forms.IntegerField(
                    label=_("Refund time frame in minutes"),
                    help_text=_(
                        "The payment will be kept in escrow for this time frame. Refunds are not possible "
                        "afterwards."
                    ),
                    min_value=2,
                    initial=60 * 24 * 7,
                ),
            ),
            (
                "testmode_kudos",
                forms.BooleanField(
                    label=_("Convert all currencies to KUDOS in test mode"),
                    required=False,
                ),
            ),
        ]
        d = OrderedDict(fields + list(super().settings_form_fields.items()))
        del d["_invoice_text"]
        d.move_to_end("_enabled", last=False)
        return d

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox("payment", "paytabs", event)

    def checkout_prepare(self, request: HttpRequest, cart):
        return self.payment_prepare(request, None)

    def payment_prepare(self, request, payment):
        return True

    def payment_can_retry(self, payment):
        return self._is_still_available(order=payment.order)

    def test_mode_message(self) -> str:
        if self.settings.testmode_kudos:
            return _(
                "Taler is operating in test mode and will charge you in KUDOS instead of the correct currency."
            )

    def payment_control_render(self, request, payment) -> str:
        if payment.info:
            payment_info = payment.info_data
        else:
            payment_info = None
        template = get_template("pretix_taler/control.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "payment_info": payment_info,
            "payment": payment,
            "provider": self,
        }
        return template.render(ctx)

    def payment_is_valid_session(self, request: HttpRequest) -> bool:
        return True

    def checkout_confirm_render(self, request) -> str:
        template = get_template("pretix_taler/checkout_confirm_render.html")
        ctx = {
            "request": request,
        }
        return template.render(ctx)

    def payment_form_render(self, request: HttpRequest, total: Decimal) -> str:
        template = get_template("pretix_taler/checkout_payment_form.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
        }
        return template.render(ctx)

    def payment_pending_render(
        self, request: HttpRequest, payment: OrderPayment
    ) -> str:
        template = get_template("pretix_taler/pending.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "payment": payment,
            "taler_url": payment.info_data["taler_pay_uri"],
        }
        return template.render(ctx)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment) -> str:
        currency = (
            "KUDOS"
            if self.settings.testmode_kudos and payment.order.testmode
            else self.event.currency
        )
        refund_deadline_unixtime = (
            time.time()
            + self.settings.get("refund_delay", default=60 * 24 * 7, as_type=int) * 60
        )
        pay_deadline_unixtime = max(
            # At least 2 minutes from now, usually like configured in payment settings, but at most the payment
            # deadline of the order
            time.time() + 120,
            min(
                time.time() + self.settings.get("max_pay_deadline", default=60, as_type=int) * 60,
                payment.order.expires.timestamp(),
            )
        )
        payload = {
            "order": {
                "summary": str(_("Order {code} for {event}")).format(
                    code=payment.order.code, event=self.event
                ),
                "order_id": payment.full_id,
                "amount": f"{currency}:{payment.amount}",
                "public_reorder_url": build_absolute_uri(
                    self.event, "presale:event.index"
                ),
                "fulfillment_url": build_absolute_uri(
                    self.event,
                    "plugins:pretix_taler:return",
                    kwargs={
                        "order": payment.order.code,
                        "payment": payment.pk,
                        "hash": hashlib.sha1(
                            payment.order.secret.lower().encode()
                        ).hexdigest(),
                    },
                ),
                "refund_deadline": {"t_s": int(refund_deadline_unixtime)},
                "pay_deadline": {"t_s": int(pay_deadline_unixtime)},
                "auto_refund": {"d_us": int(refund_deadline_unixtime - time.time()) * 1_000_000},
            },
            "create_token": True,
        }
        try:
            r = requests.post(
                urljoin(
                    self.settings.merchant_api_url,
                    f"/instances/{self.settings.merchant_api_instance}/private/orders",
                ),
                json=payload,
                headers={
                    "Authorization": f"Bearer secret-token:{self.settings.merchant_api_key}"
                },
            )

            if r.status_code not in (200, 201):
                payment.info_data = {
                    "error": True,
                    "message": r.text,
                }
                payment.state = OrderPayment.PAYMENT_STATE_FAILED
                payment.save()
                payment.order.log_action(
                    "pretix.event.order.payment.failed",
                    {
                        "local_id": payment.local_id,
                        "provider": payment.provider,
                        "message": r.text,
                    },
                )
                raise PaymentException(
                    _(
                        "We were unable to contact the payment system. Please try again later."
                    )
                )

            resp = r.json()
            payment.info_data = resp

            r = requests.get(
                urljoin(
                    self.settings.merchant_api_url,
                    f"/instances/{self.settings.merchant_api_instance}/private/orders/{payment.info_data['order_id']}",
                ),
                headers={
                    "Authorization": f"Bearer secret-token:{self.settings.merchant_api_key}"
                },
            )
            r.raise_for_status()
            order_resp = r.json()

            payment.info_data = {
                **payload["order"],
                **payment.info_data,
                **order_resp,
            }
            payment.state = OrderPayment.PAYMENT_STATE_PENDING
            payment.save(update_fields=["info", "state"])
            TalerOrder.objects.create(payment=payment, poll_until=now() + timedelta(seconds=max(pay_deadline_unixtime, refund_deadline_unixtime) + 3600))
            return eventreverse(
                self.event,
                "plugins:pretix_taler:return",
                kwargs={
                    "order": payment.order.code,
                    "payment": payment.pk,
                    "hash": hashlib.sha1(
                        payment.order.secret.lower().encode()
                    ).hexdigest(),
                },
            )
        except requests.RequestException as e:
            logger.exception("Failed to contact Taler merchant backend")
            payment.info_data = {
                "error": True,
                "message": str(e),
            }
            payment.state = OrderPayment.PAYMENT_STATE_FAILED
            payment.save()
            payment.order.log_action(
                "pretix.event.order.payment.failed",
                {
                    "local_id": payment.local_id,
                    "provider": payment.provider,
                    "message": str(e),
                },
            )

            raise PaymentException(
                _(
                    "We were unable to contact the payment system. Please try again later."
                )
            )

    def _query_and_process(self, payment):
        if "order_id" not in payment.info_data:
            payment.fail(log_data={"reason": "No order_id"})
            raise PaymentException("Invalid state")
        try:
            r = requests.get(
                urljoin(
                    self.settings.merchant_api_url,
                    f"/instances/{self.settings.merchant_api_instance}/private/orders/{payment.info_data['order_id']}",
                ),
                headers={
                    "Authorization": f"Bearer secret-token:{self.settings.merchant_api_key}"
                },
            )
            r.raise_for_status()
            resp = r.json()

            if resp["order_status"] == "paid" and not resp.get("refunded") and payment.state not in (OrderPayment.PAYMENT_STATE_REFUNDED, OrderPayment.PAYMENT_STATE_CONFIRMED):
                payment.info_data = {**payment.info_data, **resp}
                payment.confirm()

            if resp.get("refund_details"):
                pending_refunds = list(payment.refunds.filter(state=OrderRefund.REFUND_STATE_TRANSIT))
                external_refunds = list(payment.refunds.filter(source=OrderRefund.REFUND_SOURCE_EXTERNAL))
                for api_refund in resp["refund_details"]:
                    for r in pending_refunds:
                        # Check for refunds that we started and that are now done
                        if api_refund["reason"].startswith(f"{r.full_id} ") and not api_refund["pending"]:
                            r.done()
                            break
                    else:
                        # Check for refunds that we did not started and that we should know about
                        if not api_refund["pending"] and not any(r.info_data["timestamp"] == api_refund["timestamp"] for r in external_refunds):
                            payment.create_external_refund(
                                amount=Decimal(api_refund["amount"].split(":")[1]),
                                info=json.dumps(api_refund)
                            )

        except requests.RequestException as e:
            logger.exception("Failed to contact Taler merchant backend")
            payment.order.log_action(
                "pretix_taler.poll_failed",
                {
                    "local_id": payment.local_id,
                    "provider": payment.provider,
                    "message": str(e),
                },
            )
            raise PaymentException(
                _(
                    "We were unable to contact the payment system. Please try again later."
                )
            )

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return (
            "refund_deadline" in payment.info_data
            and payment.info_data["refund_deadline"]["t_s"] > time.time() + 180
        )

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return self.payment_refund_supported(payment)

    def execute_refund(self, refund: OrderRefund):
        currency = (
            "KUDOS"
            if self.settings.testmode_kudos and refund.order.testmode
            else self.event.currency
        )
        try:
            r = requests.post(
                urljoin(
                    self.settings.merchant_api_url,
                    f"/instances/{self.settings.merchant_api_instance}/private/orders/{refund.payment.info_data['order_id']}/refund",
                ),
                json={
                    "refund": f"{currency}:{refund.amount}",
                    "reason": f"{refund.full_id} {refund.comment or str(_('Refund'))}",
                },
                headers={
                    "Authorization": f"Bearer secret-token:{self.settings.merchant_api_key}"
                },
            )

            if r.status_code not in (200, 201):
                raise PaymentException(
                    _(
                        "We received a negative response from the payment backend. Response: {error}"
                    ).format(error=r.text)
                )

            resp = r.json()

            refund.info_data = resp
            refund.state = OrderRefund.REFUND_STATE_TRANSIT
            refund.save(update_fields=['info', 'state'])
        except requests.RequestException:
            logger.exception("Failed to contact Taler merchant backend")
            raise PaymentException(
                _(
                    "We were unable to contact the payment system. Please try again later."
                )
            )
