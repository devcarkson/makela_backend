# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_alter_category_image_alter_productimage_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='weight',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Weight in kg', max_digits=6),
        ),
    ]
