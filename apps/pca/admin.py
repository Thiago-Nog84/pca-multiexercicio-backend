# Admin do modulo PCA

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.utils.html import format_html

from .models import (
    CLASSIFICACAO_CONTINUIDADE,
    DocumentoFormalizacaoDemanda,
    HistoricoFasePCA,
    ItemCatalogo,
    ItemPCA,
    OrcamentoPlanejado,
    PlanoContratacaoAnual,
)


@admin.register(HistoricoFasePCA)
class HistoricoFasePCAAdmin(admin.ModelAdmin):
    list_display = ("pca", "de_status", "para_status", "usuario", "criado_em")
    list_filter = ("pca", "para_status")
    readonly_fields = ("pca", "de_status", "para_status", "usuario", "observacao", "criado_em")

    def has_add_permission(self, request):
        return False  # trilha de auditoria: criada apenas pelo painel de fases

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# --- ItemCatalogo -----------------------------------------------------------

@admin.register(ItemCatalogo)
class ItemCatalogoAdmin(admin.ModelAdmin):
    list_display  = [
        "codigo_catalogo", "descricao_padrao", "categoria_display",
        "classificacao_badge", "modalidade_sugerida", "ativo",
    ]
    list_filter   = ["classificacao", "categoria", "ativo"]
    search_fields = ["codigo_catalogo", "descricao_padrao", "codigo_catmat_catser"]
    ordering      = ["classificacao", "descricao_padrao"]
    list_per_page = 50

    fieldsets = [
        ("Identificacao", {
            "fields": ["codigo_catalogo", "descricao_padrao", "ativo"],
        }),
        ("Classificacao", {
            "fields": ["categoria", "classificacao", "base_normativa"],
        }),
        ("Dados tecnicos", {
            "fields": ["codigo_catmat_catser", "unidade_medida_padrao", "modalidade_sugerida"],
        }),
    ]

    @admin.display(description="Categoria")
    def categoria_display(self, obj):
        return obj.get_categoria_display()

    @admin.display(description="Classificacao")
    def classificacao_badge(self, obj):
        cores = {
            "continuo_fornecimento": "#7A1B28",
            "continuo_servico":      "#9B2335",
            "continuo_servico_mdo":  "#C0392B",
            "eventual":              "#64748b",
        }
        cor = cores.get(obj.classificacao, "#64748b")
        label = obj.get_classificacao_display().split(" (")[0]
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:20px;font-size:.75rem;font-weight:600">{}</span>',
            cor, label,
        )


# --- OrcamentoPlanejado -----------------------------------------------------

class OrcamentoPlanejadoInline(admin.TabularInline):
    model = OrcamentoPlanejado
    extra = 0
    fields = [
        "unidade", "valor_pgj", "valor_fmmp", "valor_fepdc",
        "trava_ativa", "atualizado_por",
    ]
    readonly_fields = ["atualizado_por"]


@admin.register(OrcamentoPlanejado)
class OrcamentoPlanejadoAdmin(admin.ModelAdmin):
    list_display = [
        "unidade", "get_exercicio", "valor_pgj", "valor_fmmp",
        "valor_fepdc", "valor_total_display", "trava_display", "atualizado_em",
    ]
    list_filter  = ["pca__exercicio", "trava_ativa", "unidade"]
    ordering     = ["-pca__exercicio", "unidade__sigla"]
    readonly_fields = ["atualizado_por", "atualizado_em"]

    fieldsets = [
        ("Identificacao", {"fields": ["pca", "unidade"]}),
        ("Tetos por UO (R$)", {"fields": ["valor_pgj", "valor_fmmp", "valor_fepdc"]}),
        ("Controle", {"fields": ["trava_ativa", "atualizado_por", "atualizado_em"]}),
    ]

    def save_model(self, request, obj, form, change):
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Exercicio", ordering="pca__exercicio")
    def get_exercicio(self, obj):
        return obj.pca.exercicio

    @admin.display(description="Total aprovado")
    def valor_total_display(self, obj):
        total = obj.valor_total
        formatted = "R$ {:,.2f}".format(float(total)).replace(",", "X").replace(".", ",").replace("X", ".")
        return format_html("<strong>{}</strong>", formatted)

    @admin.display(description="Trava")
    def trava_display(self, obj):
        if obj.trava_ativa:
            return format_html(
                '<span style="background:#9B2335;color:#fff;padding:2px 8px;'
                'border-radius:20px;font-size:.72rem;font-weight:600">Ativa</span>'
            )
        return format_html(
            '<span style="background:#64748b;color:#fff;padding:2px 8px;'
            'border-radius:20px;font-size:.72rem;">Inativa</span>'
        )


# --- PlanoContratacaoAnual --------------------------------------------------

@admin.register(PlanoContratacaoAnual)
class PlanoContratacaoAnualAdmin(admin.ModelAdmin):
    list_display  = ["exercicio", "orgao", "status", "data_aprovacao_pgj", "criado_em"]
    list_filter   = ["status", "exercicio"]
    search_fields = ["exercicio"]
    ordering      = ["-exercicio"]
    inlines       = [OrcamentoPlanejadoInline]

    fieldsets = [
        ("Identificacao", {
            "fields": ["orgao", "exercicio", "status"],
        }),
        ("Prazos do ciclo PCA", {
            "fields": [
                "prazo_coleta_inicio", "prazo_coleta_fim",
                "prazo_consolidacao_fim", "prazo_aprovacao_fim",
            ],
            "classes": ["collapse"],
        }),
        ("Aprovacao e publicacao", {
            "fields": [
                "data_aprovacao_pgj", "aprovado_por", "observacoes_pgj",
                "data_publicacao_pncp", "pncp_sequencial",
            ],
            "classes": ["collapse"],
        }),
    ]


# --- DocumentoFormalizacaoDemanda -------------------------------------------

class ItemPCAInline(admin.TabularInline):
    model = ItemPCA
    extra = 0
    fields = [
        "numero_item", "descricao", "categoria",
        "quantidade_estimada", "valor_unitario_estimado",
        "valor_total_estimado", "status",
    ]
    show_change_link = True


@admin.register(DocumentoFormalizacaoDemanda)
class DocumentoFormalizacaoDemandaAdmin(admin.ModelAdmin):
    list_display  = [
        "numero_dfd", "get_exercicio", "unidade",
        "status", "grau_prioridade", "criado_em",
    ]
    list_filter   = ["pca__exercicio", "status", "grau_prioridade", "unidade"]
    search_fields = ["numero_dfd", "numero_sei", "descricao_objeto"]
    inlines       = [ItemPCAInline]

    fieldsets = [
        ("Identificacao", {
            "fields": ["pca", "unidade", "numero_sei", "numero_dfd"],
        }),
        ("Conteudo", {
            "fields": [
                "descricao_objeto", "justificativa", "prazo_necessidade",
                "grau_prioridade", "status", "requisitante",
            ],
        }),
    ]

    @admin.display(description="Exercicio", ordering="pca__exercicio")
    def get_exercicio(self, obj):
        return obj.pca.exercicio


# --- ItemPCA ----------------------------------------------------------------

@admin.action(description="Renovar itens selecionados para o proximo exercicio")
def renovar_para_proximo_exercicio(modeladmin, request, queryset):
    from django.http import HttpResponseRedirect
    ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
    return HttpResponseRedirect(f"/pca/renovacao/?ids={ids}")


@admin.register(ItemPCA)
class ItemPCAAdmin(admin.ModelAdmin):
    list_display = [
        "codigo_pca", "descricao_curta", "get_exercicio",
        "categoria", "classificacao_continuidade_badge",
        "modalidade", "valor_total_estimado", "status",
    ]
    list_filter = [
        "dfd__pca__exercicio", "status_aprovacao", "status", "categoria",
        "classificacao_continuidade", "tipo_demanda", "modalidade",
    ]
    search_fields     = ["codigo_pca", "descricao", "codigo_catmat_catser"]
    readonly_fields   = ["codigo_pca", "analisado_por", "analisado_em"]
    autocomplete_fields = ["item_catalogo"]
    raw_id_fields     = ["origem_item", "item_pai"]
    actions           = [renovar_para_proximo_exercicio]
    list_per_page     = 50

    fieldsets = [
        ("Identificacao", {
            "fields": ["codigo_pca", "dfd", "numero_item"],
        }),
        ("Catalogo e Continuidade", {
            "fields": ["item_catalogo", "classificacao_continuidade", "origem_item"],
            "description": (
                "Selecione um item do catalogo para pre-preencher automaticamente "
                "a descricao, categoria e classificacao. "
                "O campo 'origem_item' vincula esta demanda ao item do exercicio anterior."
            ),
        }),
        ("Objeto da Contratacao", {
            "fields": [
                "categoria", "codigo_catmat_catser", "descricao",
                "unidade_fornecimento", "quantidade_estimada",
                "valor_unitario_estimado", "valor_total_estimado",
            ],
        }),
        ("Analise da Demanda", {
            "fields": [
                "status_aprovacao", "motivo_analise",
                "quantidade_solicitada", "valor_unitario_solicitado",
                "analisado_por", "analisado_em",
            ],
            "description": (
                "Veredito da area gestora. Aprovacao parcial e nao aprovacao exigem "
                "motivo (a unidade requisitante ve essa justificativa). Os campos "
                "'solicitada/solicitado' preservam o pedido original quando ha corte."
            ),
        }),
        ("Contratacao", {
            "fields": [
                "tipo_demanda", "modalidade", "normativo",
                "unidade_orcamentaria", "is_srp",
                "numero_lote_pca", "justificativa_srp",
            ],
        }),
        ("Prazos", {
            "fields": [
                "data_vencimento_contrato_anterior", "data_pretendida_conclusao",
                "data_envio_pgea", "data_finalizacao_licitacao", "data_conclusao_efetiva",
            ],
            "classes": ["collapse"],
        }),
        ("Execucao e rastreabilidade", {
            "fields": ["status", "valor_empenhado", "etp", "item_pai", "observacoes"],
            "classes": ["collapse"],
        }),
    ]

    class Media:
        js  = ["pca/admin/catalogo_autofill.js"]
        css = {"all": ["pca/admin/catalogo_autofill.css"]}

    @admin.display(description="Descricao")
    def descricao_curta(self, obj):
        d = obj.descricao
        return d[:65] + "..." if len(d) > 65 else d

    @admin.display(description="Exercicio", ordering="dfd__pca__exercicio")
    def get_exercicio(self, obj):
        return obj.dfd.pca.exercicio

    @admin.display(description="Continuidade")
    def classificacao_continuidade_badge(self, obj):
        cores = {
            "continuo_fornecimento": "#7A1B28",
            "continuo_servico":      "#9B2335",
            "continuo_servico_mdo":  "#C0392B",
            "eventual":              "#94a3b8",
        }
        cor = cores.get(obj.classificacao_continuidade, "#94a3b8")
        label = dict(CLASSIFICACAO_CONTINUIDADE).get(
            obj.classificacao_continuidade, obj.classificacao_continuidade
        ).split(" (")[0]
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 7px;'
            'border-radius:20px;font-size:.72rem;font-weight:600">{}</span>',
            cor, label,
        )

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "catalogo-detalhe/<int:pk>/",
                self.admin_site.admin_view(self._catalogo_detalhe),
                name="pca_itempca_catalogo_detalhe",
            ),
        ]
        return extra + urls

    def _catalogo_detalhe(self, request, pk):
        try:
            item = ItemCatalogo.objects.get(pk=pk, ativo=True)
            payload = {
                "id":                    item.pk,
                "codigo_catalogo":       item.codigo_catalogo,
                "descricao_padrao":      item.descricao_padrao,
                "categoria":             item.categoria,
                "classificacao":         item.classificacao,
                "codigo_catmat_catser":  item.codigo_catmat_catser,
                "unidade_medida_padrao": item.unidade_medida_padrao,
                "modalidade_sugerida":   item.modalidade_sugerida,
                "base_normativa":        item.base_normativa,
            }
        except ItemCatalogo.DoesNotExist:
            payload = {}
        return JsonResponse(payload)
