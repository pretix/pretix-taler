# Generated by Django 3.2.12 on 2022-07-18 15:52

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('pretixbase', '0218_checkinlist_addon_match'),
    ]

    operations = [
        migrations.CreateModel(
            name='TalerOrder',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('poll_until', models.DateTimeField()),
                ('payment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pretixbase.orderpayment')),
            ],
        ),
    ]
