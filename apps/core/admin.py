from django.contrib import admin

from .models import Orgao, Perfil, UnidadeRequisitante

admin.site.register(Orgao)
admin.site.register(UnidadeRequisitante)
admin.site.register(Perfil)
