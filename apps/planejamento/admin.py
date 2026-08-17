from django.contrib import admin

from .models import ETP, DocumentoOficializacaoDemanda, EquipePlanejamentoTI

admin.site.register(ETP)


class EquipePlanejamentoTIInline(admin.StackedInline):
    model = EquipePlanejamentoTI
    extra = 0
    max_num = 1
    fields = [
        "integrante_requisitante", "integrante_tecnico", "integrante_administrativo",
        "lider", "ato_designacao_sei",
    ]

    def get_fields(self, request, obj=None):
        # "Integrante Administrativo" só é relevante em contratação de TI
        # (Res. CNMP 283/2024) — some do formulário nas demais naturezas
        # pra não sugerir que é sempre exigido. A regra de fato (bloquear
        # save incompleto) mora em EquipePlanejamentoTI.clean().
        fields = list(super().get_fields(request, obj))
        if obj is not None and obj.natureza_objeto != DocumentoOficializacaoDemanda.NATUREZA_TI:
            fields = [f for f in fields if f != "integrante_administrativo"]
        return fields


@admin.register(DocumentoOficializacaoDemanda)
class DocumentoOficializacaoDemandaAdmin(admin.ModelAdmin):
    list_display = [
        "identificador", "pca", "status", "grau_prioridade",
        "qtd_itens", "valor_total_estimado", "criado_em",
    ]
    list_filter = ["pca", "status", "grau_prioridade", "unidade_orcamentaria"]
    search_fields = ["identificador", "numero_sei", "objeto"]
    filter_horizontal = ["itens"]
    inlines = [EquipePlanejamentoTIInline]

    fieldsets = [
        ("Identificação", {
            "fields": ["pca", "identificador", "numero_sei", "objeto", "itens", "status"],
        }),
        ("Informações gerais da contratação", {
            "fields": [
                "unidade_orcamentaria", "natureza_objeto",
                "contratacao_correlata", "contratacao_correlata_qual",
                "grau_prioridade", "previsao_inicio_execucao", "previsao_termino_execucao",
            ],
        }),
        ("Alinhamento estratégico", {
            "fields": ["objetivos_estrategicos", "alinhamento_pdtic"],
            "classes": ["collapse"],
        }),
        ("Fundamentação e resultados esperados", {
            "fields": [
                "necessidade_contratacao", "motivacao_justificativa",
                "objetivo_contratacao", "meta_contratacao", "indicador_resultado",
            ],
            "classes": ["collapse"],
        }),
        ("Responsável", {
            "fields": ["responsavel_preenchimento"],
        }),
    ]

    @admin.display(description="Itens")
    def qtd_itens(self, obj):
        return obj.itens.count()

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "itens":
            from django.db.models import Q

            from apps.pca.models import ItemPCA

            obj_id = request.resolver_match.kwargs.get("object_id")
            qs = ItemPCA.objects.filter(status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
            bloqueados = Q(documentos_oficializacao__status="aberto")
            if obj_id:
                # Não bloqueia os itens que já são deste próprio DOD sendo editado.
                bloqueados &= ~Q(documentos_oficializacao__pk=obj_id)
            kwargs["queryset"] = qs.exclude(bloqueados).distinct()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


# Registrar apos implementacao completa de planejamento/models.py:
# from .models import EquipePlanejamentoTI, MatrizRisco, RiscoItem, TermoReferencia
