from django.contrib import admin

from .models import Aditivo, Apostilamento, Contrato, OrdemFornecimento


class AditivoInline(admin.TabularInline):
    model = Aditivo
    extra = 0
    fields = ("numero_aditivo", "tipo", "data_assinatura", "nova_data_fim_vigencia", "valor_acrescimo")
    readonly_fields = ("numero_aditivo",)


class ApostilamentoInline(admin.TabularInline):
    model = Apostilamento
    extra = 0
    fields = ("numero_apostilamento", "tipo", "data_apostilamento", "valor_anterior", "valor_novo")
    readonly_fields = ("numero_apostilamento",)


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = (
        "numero_contrato",
        "orgao",
        "unidade_requisitante",
        "contratado_razao_social",
        "tipo",
        "status",
        "data_fim_vigencia",
        "valor_atual",
    )
    list_filter = (
        "status",
        "tipo",
        "orgao",
        "unidade_requisitante",
    )
    search_fields = (
        "numero_contrato",
        "numero_sei",
        "contratado_razao_social",
        "contratado_cnpj_cpf",
        "objeto",
        "codigo_siafe",
    )
    autocomplete_fields = ["unidade_requisitante"]
    readonly_fields = ("criado_em", "atualizado_em", "valor_empenhado", "ultima_atualizacao_siafe")
    inlines = [AditivoInline, ApostilamentoInline]

    fieldsets = (
        ("Identificação", {
            "fields": (
                "numero_contrato", "numero_sei", "numero_pncp",
                "tipo", "objeto", "status",
            )
        }),
        ("Partes", {
            "fields": (
                "orgao", "unidade_requisitante",
                "contratado_razao_social", "contratado_cnpj_cpf",
            )
        }),
        ("Valores", {
            "fields": (
                "valor_inicial", "valor_atual", "saldo_disponivel",
            )
        }),
        ("Execução Orçamentária (SIAFE)", {
            "fields": ("codigo_siafe", "valor_empenhado", "ultima_atualizacao_siafe"),
            "classes": ("collapse",),
        }),
        ("Vigência", {
            "fields": (
                "data_assinatura", "data_inicio_vigencia", "data_fim_vigencia",
                "data_publicacao_pncp",
            )
        }),
        ("Vínculos", {
            "fields": ("item_pca", "arp_origem", "arp_externa_origem"),
            "classes": ("collapse",),
        }),
        ("Fiscalização", {
            "fields": ("gestor", "fiscal_tecnico", "fiscal_administrativo"),
            "classes": ("collapse",),
        }),
        ("Observações e Auditoria", {
            "fields": ("observacoes", "criado_por", "criado_em", "atualizado_em"),
            "classes": ("collapse",),
        }),
    )

    def get_search_fields(self, request):
        return self.search_fields


@admin.register(Aditivo)
class AditivoAdmin(admin.ModelAdmin):
    list_display = ("contrato", "numero_aditivo", "tipo", "data_assinatura", "valor_acrescimo")
    list_filter = ("tipo",)
    search_fields = ("contrato__numero_contrato", "objeto_aditivo")
    autocomplete_fields = ["contrato"]


@admin.register(Apostilamento)
class ApostilamentoAdmin(admin.ModelAdmin):
    list_display = ("contrato", "numero_apostilamento", "tipo", "data_apostilamento", "valor_novo")
    list_filter = ("tipo",)
    search_fields = ("contrato__numero_contrato", "descricao")
    autocomplete_fields = ["contrato"]


@admin.register(OrdemFornecimento)
class OrdemFornecimentoAdmin(admin.ModelAdmin):
    list_display = ("numero_ordem", "contrato", "unidade_requisitante", "valor", "data_emissao", "status")
    list_filter = ("status", "unidade_requisitante")
    search_fields = ("numero_ordem", "contrato__numero_contrato", "descricao")
    autocomplete_fields = ["contrato"]
