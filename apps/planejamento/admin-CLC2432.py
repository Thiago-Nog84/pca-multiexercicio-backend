from django.contrib import admin

from .models import ETP, EquipePlanejamentoTI, MatrizRisco, RiscoItem, TermoReferencia

admin.site.register(ETP)
admin.site.register(EquipePlanejamentoTI)
admin.site.register(MatrizRisco)
admin.site.register(RiscoItem)
admin.site.register(TermoReferencia)
