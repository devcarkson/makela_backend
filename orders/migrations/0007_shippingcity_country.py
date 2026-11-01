# ShippingCity: add country field, scope uniqueness by (name, country)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0006_shippingcity'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippingcity',
            name='country',
            field=models.CharField(default='GB', help_text='ISO 3166-1 alpha-2 country code', max_length=2, verbose_name='Country Code'),
        ),
        migrations.AlterField(
            model_name='shippingcity',
            name='name',
            field=models.CharField(max_length=100, verbose_name='City Name'),
        ),
        migrations.AlterModelOptions(
            name='shippingcity',
            options={'ordering': ['country', 'name'], 'verbose_name': 'Shipping City', 'verbose_name_plural': 'Shipping Cities'},
        ),
        migrations.AlterUniqueTogether(
            name='shippingcity',
            unique_together={('name', 'country')},
        ),
    ]
