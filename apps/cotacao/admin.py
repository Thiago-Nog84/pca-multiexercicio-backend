from django.contrib import admin

from .models import FontePreco, ItemCotacao, PesquisaPrecos

admin.site.register(PesquisaPrecos)
admin.site.register(FontePreco)
admin.site.register(ItemCotacao)
