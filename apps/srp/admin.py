from django.contrib import admin

from .models import (
    AdesaoARP,
    ARPExterna,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ItemARP,
)

admin.site.register(AtaRegistroPrecos)
admin.site.register(ItemARP)
admin.site.register(ContratacaoDecorrente)
admin.site.register(AdesaoARP)
admin.site.register(ARPExterna)
