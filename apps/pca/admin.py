from django.contrib import admin

from .models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual

admin.site.register(PlanoContratacaoAnual)
admin.site.register(DocumentoFormalizacaoDemanda)
admin.site.register(ItemPCA)
