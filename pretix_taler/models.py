from django.db import models


class TalerOrder(models.Model):
    payment = models.ForeignKey("pretixbase.OrderPayment", on_delete=models.CASCADE)
    poll_until = models.DateTimeField()
