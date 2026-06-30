from django.contrib import admin
from .models import ProcessoLicitatorio, ItemLicitacao


class ItemLicitacaoInline(admin.TabularInline):
    model = ItemLicitacao
    extra = 0
    fields = ("numero_item", "descricao", "unidade", "quantidade", "valor_unitario_homologado", "fornecedor_vencedor", "cnpj_vencedor")


@admin.register(ProcessoLicitatorio)
class ProcessoLicitatorioAdmin(admin.ModelAdmin):
    list_display = ("numero_edital", "ano", "modalidade", "situacao", "valor_homologado", "data_publicacao")
    list_filter = ("ano", "modalidade", "situacao")
    search_fields = ("numero_edital", "numero_controle_pncp", "objeto", "processo_sei")
    inlines = [ItemLicitacaoInline]


@admin.register(ItemLicitacao)
class ItemLicitacaoAdmin(admin.ModelAdmin):
    list_display = ("numero_item", "licitacao", "descricao_curta", "quantidade", "valor_unitario_homologado", "fornecedor_vencedor")
    list_filter = ("licitacao__ano", "licitacao__modalidade")
    search_fields = ("descricao", "fornecedor_vencedor", "cnpj_vencedor")

    def descricao_curta(self, obj):
        return obj.descricao[:50] + "..." if len(obj.descricao) > 50 else obj.descricao
    descricao_curta.short_description = "Descrição"
