from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AdesaoARP,
    ARPExterna,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ContratoARP,
    ContratoComprasnet,
    ItemARP,
    VinculoARPUnidade,
    VinculoPCAItemARP,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class ItemARPInline(admin.TabularInline):
    model = ItemARP
    extra = 0
    fields = ("numero_item", "numero_lote", "descricao", "unidade_fornecimento",
              "quantidade_registrada", "valor_unitario", "quantidade_contratada")
    readonly_fields = ("quantidade_contratada",)


class VinculoARPUnidadeInline(admin.TabularInline):
    model = VinculoARPUnidade
    extra = 1
    fields = ("unidade", "papel", "observacoes")
    autocomplete_fields = ("unidade",)
    verbose_name = "Unidade vinculada"
    verbose_name_plural = "Unidades gestoras / demandantes"


# ---------------------------------------------------------------------------
# AtaRegistroPrecos
# ---------------------------------------------------------------------------

@admin.register(AtaRegistroPrecos)
class AtaRegistroPrecosAdmin(admin.ModelAdmin):
    list_display = (
        "numero_arp", "fornecedor_razao_social", "status_badge",
        "data_inicio_vigencia", "data_fim_vigencia",
        "unidades_vinculadas_display",
    )
    list_filter = ("status", "modalidade_origem", "vinculos_unidades__unidade")
    search_fields = ("numero_arp", "objeto", "fornecedor_razao_social", "fornecedor_cnpj_cpf")
    date_hierarchy = "data_inicio_vigencia"
    inlines = [VinculoARPUnidadeInline, ItemARPInline]
    readonly_fields = ("criado_em", "atualizado_em", "importada_da_api")
    fieldsets = (
        ("Identificação", {
            "fields": (
                "orgao_gerenciador", "numero_arp", "objeto",
                "modalidade_origem", "processo_licitatorio",
                "numero_sei", "numero_pncp", "numero_controle_pncp_ata",
            ),
        }),
        ("Fornecedor", {
            "fields": ("fornecedor_razao_social", "fornecedor_cnpj_cpf"),
        }),
        ("Vigência", {
            "fields": (
                "data_assinatura", "data_inicio_vigencia", "data_fim_vigencia", "status",
                "prorrogada", "data_fim_vigencia_original", "data_prorrogacao", "quantitativos_renovados",
            ),
        }),
        ("Integração PNCP / Compras.gov.br", {
            "classes": ("collapse",),
            "fields": (
                "importada_da_api", "codigo_uasg_gerenciadora",
                "id_compra_compras_gov", "link_ata_pncp", "data_publicacao_pncp",
            ),
        }),
        ("Controle", {
            "fields": ("observacoes", "criado_por", "criado_em", "atualizado_em"),
        }),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        cores = {
            "vigente": "success",
            "suspensa": "warning",
            "cancelada": "danger",
            "encerrada": "secondary",
        }
        cor = cores.get(obj.status, "secondary")
        return format_html(
            '<span class="badge text-bg-{}">{}</span>',
            cor, obj.get_status_display()
        )

    @admin.display(description="Setores")
    def unidades_vinculadas_display(self, obj):
        vinculos = obj.vinculos_unidades.select_related("unidade").order_by("papel")
        if not vinculos:
            return "—"
        partes = []
        for v in vinculos:
            icone = "🏛️" if v.papel == "gestora" else "📋"
            partes.append(f"{icone} {v.unidade.sigla}")
        return format_html(", ".join(partes))


# ---------------------------------------------------------------------------
# VinculoARPUnidade (administração standalone)
# ---------------------------------------------------------------------------

@admin.register(VinculoARPUnidade)
class VinculoARPUnidadeAdmin(admin.ModelAdmin):
    list_display = ("arp", "unidade", "papel", "criado_em")
    list_filter = ("papel", "unidade")
    search_fields = ("arp__numero_arp", "unidade__sigla", "unidade__nome")
    autocomplete_fields = ("unidade",)
    raw_id_fields = ("arp",)


# ---------------------------------------------------------------------------
# Outros modelos
# ---------------------------------------------------------------------------

@admin.register(ItemARP)
class ItemARPAdmin(admin.ModelAdmin):
    list_display = ("arp", "numero_item", "descricao", "unidade_fornecimento",
                    "quantidade_registrada", "valor_unitario", "quantidade_contratada")
    list_filter = ("arp__status", "banco_referencia")
    search_fields = ("descricao", "codigo_catmat_catser", "arp__numero_arp")
    list_select_related = ("arp",)


admin.site.register(ContratacaoDecorrente)
admin.site.register(AdesaoARP)
admin.site.register(ARPExterna)
admin.site.register(VinculoPCAItemARP)


# ---------------------------------------------------------------------------
# ContratoComprasnet
# ---------------------------------------------------------------------------

@admin.register(ContratoComprasnet)
class ContratoComprasnetAdmin(admin.ModelAdmin):
    list_display = (
        "numero", "fornecedor_nome", "situacao", "valor_global",
        "vigencia_inicio", "vigencia_fim", "importado_em",
    )
    list_filter = ("situacao", "modalidade", "categoria")
    search_fields = ("numero", "fornecedor_nome", "fornecedor_cnpj", "objeto", "processo")
    date_hierarchy = "vigencia_fim"
    readonly_fields = ("importado_em", "contrato_comprasnet_id")
    list_select_related = ("arp",)

    @admin.display(description="Vigente?", boolean=True)
    def esta_vigente_display(self, obj):
        return obj.esta_vigente


# ---------------------------------------------------------------------------
# ContratoARP
# ---------------------------------------------------------------------------

@admin.register(ContratoARP)
class ContratoARPAdmin(admin.ModelAdmin):
    list_display = (
        "numero_contrato", "contratado_nome", "uasg_contratante",
        "valor_total", "data_inicio_vigencia", "data_fim_vigencia",
        "is_carona", "importado_em",
    )
    list_filter = ("is_carona",)
    search_fields = (
        "numero_contrato", "contratado_nome", "contratado_cnpj",
        "uasg_contratante", "nome_uasg_contratante",
    )
    date_hierarchy = "data_fim_vigencia"
    readonly_fields = ("importado_em",)
    list_select_related = ("arp",)
    raw_id_fields = ("arp",)
