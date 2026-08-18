from django.contrib import admin

from .models import (
    ETP,
    DocumentoOficializacaoDemanda,
    EquipePlanejamentoTI,
    MatrizRisco,
    RiscoItem,
    TermoReferencia,
)


@admin.register(ETP)
class ETPAdmin(admin.ModelAdmin):
    """
    Fieldsets adicionados em 2026-08-18, junto com a tela de detalhe do ETP
    (etp_detalhe.html): antes o ETP só tinha `admin.site.register(ETP)` nu,
    sem organização nenhuma dos ~20 campos. Mantido registrado (mesmo com a
    tela nova) porque o link "Editar" do etp_detalhe.html aponta pra cá — a
    tela nova só cria e mostra, não edita.
    """

    list_display = ["numero_etp", "dod", "status", "is_ti", "estimativa_custo", "atualizado_em"]
    list_filter = ["status", "is_ti", "etp_dispensado"]
    search_fields = ["numero_etp", "numero_sei", "dod__identificador"]

    fieldsets = [
        ("Identificação", {
            "fields": ["dod", "numero_etp", "numero_sei", "is_ti", "status"],
        }),
        ("Dispensa", {
            "fields": ["etp_dispensado", "fundamento_dispensa_etp"],
        }),
        ("Necessidade e requisitos", {
            "fields": ["necessidade_contratacao", "requisitos_contratacao"],
        }),
        ("Mercado e solução", {
            "fields": ["levantamento_mercado", "descricao_solucao", "solucao_em_outros_orgaos", "software_livre_avaliado"],
        }),
        ("Quantitativos e custos", {
            "fields": ["estimativa_quantidade", "estimativa_custo", "tco_total"],
        }),
        ("Parcelamento e correlatas", {
            "fields": ["justificativa_parcelamento", "contratacoes_correlatas"],
        }),
        ("Alinhamento e resultados", {
            "fields": ["alinhamento_pca", "resultados_pretendidos", "providencias_previas"],
        }),
        ("Impactos ambientais e viabilidade", {
            "fields": ["impactos_ambientais", "declaracao_viabilidade"],
        }),
        ("Elaboração assistida por IA", {
            "fields": ["gerado_por_ia", "ia_modelo_utilizado", "ia_revisado_por"],
            "classes": ["collapse"],
        }),
    ]


@admin.register(EquipePlanejamentoTI)
class EquipePlanejamentoTIAdmin(admin.ModelAdmin):
    """
    Registrado em 2026-08-18: o checklist (checklist_instrucao.html) linka
    pra `/admin/planejamento/equipeplanejamentoti/add/?dod=` desde
    2026-08-17, mas o model só existia como inline de DOD — o link dava
    404. Continua havendo o inline em DODAdmin (preenchimento junto com o
    DOD); este registro standalone só existe pra esse link funcionar
    quando a equipe não foi definida na criação do DOD.
    """

    list_display = ["dod", "integrante_requisitante", "integrante_tecnico", "integrante_administrativo", "lider"]
    fields = [
        "dod", "integrante_requisitante", "integrante_tecnico", "integrante_administrativo",
        "lider", "ato_designacao_sei",
    ]


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


class RiscoItemInline(admin.TabularInline):
    model = RiscoItem
    extra = 0
    fields = [
        "descricao_risco", "probabilidade", "impacto", "nivel_risco",
        "responsavel", "acao_preventiva", "acao_contingencia",
    ]
    readonly_fields = ["nivel_risco"]


@admin.register(MatrizRisco)
class MatrizRiscoAdmin(admin.ModelAdmin):
    """
    Registrado em 2026-08-18 junto com matriz_risco_detalhe.html — antes
    nem MatrizRisco nem RiscoItem tinham admin, então o link "Pendente" do
    checklist pra `/admin/planejamento/matrizrisco/add/` dava 404 mesmo
    depois de corrigido o nome (a causa de fato não era só o typo).
    """

    list_display = ["etp", "fase_atual", "qtd_itens"]
    list_filter = ["fase_atual"]
    inlines = [RiscoItemInline]

    @admin.display(description="Riscos")
    def qtd_itens(self, obj):
        return obj.itens.count()


@admin.register(TermoReferencia)
class TermoReferenciaAdmin(admin.ModelAdmin):
    """Registrado em 2026-08-18 — mesma lacuna do MatrizRiscoAdmin acima."""

    list_display = ["etp", "status", "criterio_julgamento", "is_srp", "atualizado_em"]
    list_filter = ["status", "is_servico_continuo", "is_srp"]
    search_fields = ["numero_sei", "objeto", "etp__numero_etp"]

    fieldsets = [
        ("Identificação", {
            "fields": ["etp", "numero_sei", "status", "criterio_julgamento"],
        }),
        ("Objeto e fundamentação", {
            "fields": ["objeto", "fundamentacao_legal", "descricao_solucao", "requisitos_habilitacao"],
        }),
        ("Execução", {
            "fields": [
                "prazo_execucao", "local_execucao", "criterios_medicao",
                "obrigacoes_contratante", "obrigacoes_contratado",
            ],
        }),
        ("Continuidade e SRP", {
            "fields": [
                "is_servico_continuo", "prazo_inicial_meses", "prazo_maximo_meses",
                "is_srp", "justificativa_srp",
            ],
        }),
        ("Tecnologia da Informação", {
            "fields": ["modalidade_remuneracao_ti", "vedacoes_ti_observadas"],
            "classes": ["collapse"],
        }),
        ("Elaboração assistida por IA", {
            "fields": ["gerado_por_ia", "modelo_agu_base"],
            "classes": ["collapse"],
        }),
    ]
