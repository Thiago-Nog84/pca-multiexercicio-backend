from django.contrib import admin

from .models import Aditivo, Apostilamento, Contrato, OrdemFornecimento

admin.site.register(Contrato)
admin.site.register(Aditivo)
admin.site.register(Apostilamento)
admin.site.register(OrdemFornecimento)
