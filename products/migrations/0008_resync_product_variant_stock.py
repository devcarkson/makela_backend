from django.db import migrations
from django.db.models import Sum


def resync_product_stock(apps, schema_editor):
    """Repair Product.stock for variant products that drifted from their variants."""
    Product = apps.get_model('products', 'Product')
    db_alias = schema_editor.connection.alias

    for product in Product.objects.using(db_alias).filter(has_variants=True):
        total = (
            product.variants.using(db_alias)
            .filter(is_active=True)
            .aggregate(total=Sum('stock'))['total'] or 0
        )
        if product.stock != total:
            Product.objects.using(db_alias).filter(pk=product.pk).update(stock=total)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0007_color_size_product_has_variants_alter_product_price_and_more'),
    ]

    operations = [
        migrations.RunPython(resync_product_stock, noop),
    ]
