from django.contrib import admin

from .models import ETP

admin.site.register(ETP)

# Registrar apos implementacao completa de planejamento/models.py:
# from .models import EquipePlanejamentoTI, MatrizRisco, RiscoItem, TermoReferencia
