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
    list_filter = (
        "status", "modalidade_origem", "substituido_por_cadastro_reserva",
        "vinculos_unidades__unidade",
    )
    search_fields = (
        "numero_arp", "objeto", "fornecedor_razao_social", "fornecedor_cnpj_cpf",
        "fornecedor_original_razao_social", "fornecedor_original_cnpj_cpf",
    )
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
        ("Fornecedor (detentor atual)", {
            "fields": ("fornecedor_razao_social", "fornecedor_cnpj_cpf"),
        }),
        ("Substituição por cadastro de reserva", {
            "classes": ("collapse",),
            "description": (
                "Preencher quando o vencedor original desistiu e a ata passou a outro "
                "fornecedor do cadastro de reserva (art. 82, §4º da Lei 14.133/2021). "
                "O novo detentor é registrado com o PREÇO DELE — por isso o valor dos "
                "itens passa a divergir legitimamente do resultado homologado no PNCP, "
                "que continua exibindo o vencedor original."
            ),
            "fields": (
                "substituido_por_cadastro_reserva",
                "fornecedor_original_razao_social", "fornecedor_original_cnpj_cpf",
                "data_substituicao", "motivo_substituicao",
            ),
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


@admin.register(ContratacaoDecorrente)
class ContratacaoDecorrenteAdmin(admin.ModelAdmin):
    list_display = [
        "numero_contrato", "numero_pedido", "arp", "unidade_orcamentaria",
        "unidade_requisitante", "valor_total", "exercicio", "status",
    ]
    list_filter = ["status", "unidade_orcamentaria", "exercicio"]
    list_editable = ["unidade_orcamentaria"]  # preenchimento rápido da fonte
    search_fields = ["numero_contrato", "numero_pedido", "item_arp__descricao", "arp__numero_arp"]
    autocomplete_fields = ["arp", "item_arp"]
    raw_id_fields = ["unidade_requisitante"]


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
    actions = ["importar_para_contratos_locais"]

    @admin.display(description="Vigente?", boolean=True)
    def esta_vigente_display(self, obj):
        return obj.esta_vigente

    @admin.action(description="Importar selecionados para o Cadastro Geral de Contratos (MPPI)")
    def importar_para_contratos_locais(self, request, queryset):
        import re
        from datetime import date
        from apps.contratos.models import Contrato
        from apps.core.models import Orgao

        orgao_padrao = Orgao.objects.first()
        if not orgao_padrao:
            self.message_user(request, "Erro: Nenhum Órgão (MPPI) cadastrado no sistema.", level="error")
            return

        def _norm(s):
            m = re.match(r"^0*(\d+)[/-](\d{4})", str(s or "").strip())
            return f"{int(m.group(1))}/{m.group(2)}" if m else str(s or "").strip()

        locais_norm = {_norm(n): n for n in Contrato.objects.values_list("numero_contrato", flat=True)}
        criados = 0

        for cc in queryset:
            norm_num = _norm(cc.numero)
            if norm_num in locais_norm:
                continue

            dt_ini = cc.vigencia_inicio or date.today()
            dt_fim = cc.vigencia_fim or date.today()

            Contrato.objects.create(
                orgao=orgao_padrao,
                numero_contrato=cc.numero,
                objeto=cc.objeto or f"Contrato importado via Comprasnet {cc.numero}",
                contratado_razao_social=cc.fornecedor_nome or "Fornecedor não informado",
                contratado_cnpj_cpf=cc.fornecedor_cnpj or "",
                valor_inicial=cc.valor_global or 0,
                valor_atual=cc.valor_global or 0,
                saldo_disponivel=cc.valor_global or 0,
                data_assinatura=dt_ini,
                data_inicio_vigencia=dt_ini,
                data_fim_vigencia=dt_fim,
                tipo="servico_nao_continuo",
            )
            criados += 1

        self.message_user(request, f"{criados} contrato(s) importado(s) com sucesso para o Cadastro Geral de Contratos.")


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
