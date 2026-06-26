from django.contrib import admin
from .models import SiafeLogConsulta


@admin.register(SiafeLogConsulta)
class SiafeLogConsultaAdmin(admin.ModelAdmin):
    list_display = (
        "endpoint", "sucesso", "status_http",
        "tempo_resposta_ms", "consultado_por", "criado_em",
    )
    list_filter = ("sucesso", "endpoint")
    readonly_fields = ("criado_em", "parametros")
    search_fields = ("erro_detalhe", "consultado_por__username")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("consultado_por")
