from django.utils.translation import gettext_lazy
from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_taler"
    verbose_name = "Taler"

    class PretixPluginMeta:
        name = gettext_lazy("Taler")
        author = "pretix team"
        description = gettext_lazy(
            "Accept payments through GNU Taler, a payment system that makes privacy-friendly online transactions fast and easy."
        )
        visible = True
        version = __version__
        picture = "pretix_taler/logo.svg"
        category = "PAYMENT"
        compatibility = "pretix>=4.10.0"

    def ready(self):
        from . import signals  # NOQA


