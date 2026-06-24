from django.contrib import admin

from .models import (
    AdesaoARP,
    ARPExterna,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ItemAdesaoARP,
    ItemARP,
    ItemContratacaoDecorrente,
)

admin.site.register(AtaRegistroPrecos)
admin.site.register(ItemARP)
admin.site.register(ContratacaoDecorrente)
admin.site.register(ItemContratacaoDecorrente)
admin.site.register(AdesaoARP)
admin.site.register(ItemAdesaoARP)
admin.site.register(ARPExterna)
