from django.utils.translation import gettext_lazy

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")

__version__ = "1.1.0"


class PluginApp(PluginConfig):
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


default_app_config = "pretix_taler.PluginApp"
