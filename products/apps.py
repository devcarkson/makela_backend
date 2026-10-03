from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'products'

    def ready(self):
        from django.contrib import admin

        from . import signals  # noqa: F401

        admin.site.site_header = 'Makela'
        admin.site.site_title = 'Makela admin'
        admin.site.index_title = 'Store administration'
