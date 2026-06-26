from django.contrib import admin

from .models import Orgao, Perfil, UnidadeRequisitante


@admin.register(UnidadeRequisitante)
class UnidadeRequisitanteAdmin(admin.ModelAdmin):
    search_fields = ("sigla", "nome")
    list_display = ("sigla", "nome")
    ordering = ("sigla",)


admin.site.register(Orgao)
admin.site.register(Perfil)
