"""Keep the denormalized ``Product.stock`` in sync with ``ProductVariant`` stock."""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Product, ProductVariant


def _sync_product_stock(product_id):
    """Recalculate stock for a single product id (no-op for non variant products)."""
    if not product_id:
        return
    product = Product.objects.filter(pk=product_id).only('id', 'has_variants').first()
    if product and product.has_variants:
        product.sync_variant_stock()


@receiver(pre_save, sender=ProductVariant)
def stash_previous_product(sender, instance, **kwargs):
    """Remember the owning product so a re-assignment can resync both products."""
    instance._previous_product_id = None
    if instance.pk:
        instance._previous_product_id = (
            ProductVariant.objects.filter(pk=instance.pk)
            .values_list('product_id', flat=True)
            .first()
        )


@receiver(post_save, sender=ProductVariant)
def sync_product_stock_on_variant_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    _sync_product_stock(instance.product_id)

    previous_product_id = getattr(instance, '_previous_product_id', None)
    if previous_product_id and previous_product_id != instance.product_id:
        _sync_product_stock(previous_product_id)


@receiver(post_delete, sender=ProductVariant)
def sync_product_stock_on_variant_delete(sender, instance, **kwargs):
    _sync_product_stock(instance.product_id)
