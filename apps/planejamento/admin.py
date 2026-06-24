from django.contrib import admin

from .models import ETP, EquipePlanejamentoTI, MatrizRisco, RiscoItem, TermoReferencia

admin.site.register(ETP)
admin.site.register(TermoReferencia)
admin.site.register(MatrizRisco)
