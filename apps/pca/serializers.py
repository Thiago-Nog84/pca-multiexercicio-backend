from rest_framework import serializers

from .models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual


class PlanoContratacaoAnualSerializer(serializers.ModelSerializer):
    orgao_sigla = serializers.CharField(source="orgao.sigla", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PlanoContratacaoAnual
        fields = [
            "id",
            "orgao",
            "orgao_sigla",
            "exercicio",
            "status",
            "status_display",
            "prazo_coleta_inicio",
            "prazo_coleta_fim",
            "prazo_consolidacao_fim",
            "prazo_aprovacao_fim",
            "data_aprovacao_pgj",
            "data_publicacao_pncp",
            "pncp_sequencial",
            "aprovado_por",
            "observacoes_pgj",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em", "orgao_sigla", "status_display"]


class ItemPCASerializer(serializers.ModelSerializer):
    categoria_display = serializers.CharField(source="get_categoria_display", read_only=True)
    tipo_contratacao_display = serializers.CharField(
        source="get_tipo_contratacao_display", read_only=True
    )

    class Meta:
        model = ItemPCA
        fields = [
            "id",
            "dfd",
            "numero_item",
            "categoria",
            "categoria_display",
            "codigo_catmat_catser",
            "unidade_fornecimento",
            "quantidade_estimada",
            "descricao",
            "tipo_contratacao",
            "tipo_contratacao_display",
            "valor_unitario_estimado",
            "valor_total_estimado",
            "data_vencimento_contrato_anterior",
            "data_pretendida_conclusao",
            "item_dependente",
            "observacoes",
            "is_srp",
            "justificativa_srp",
            "etp",
        ]
        read_only_fields = ["categoria_display", "tipo_contratacao_display"]


class DocumentoFormalizacaoDemandaSerializer(serializers.ModelSerializer):
    itens = ItemPCASerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    unidade_sigla = serializers.CharField(source="unidade.sigla", read_only=True)

    class Meta:
        model = DocumentoFormalizacaoDemanda
        fields = [
            "id",
            "pca",
            "unidade",
            "unidade_sigla",
            "numero_sei",
            "numero_dfd",
            "descricao_objeto",
            "justificativa",
            "prazo_necessidade",
            "grau_prioridade",
            "status",
            "status_display",
            "requisitante",
            "criado_em",
            "itens",
        ]
        read_only_fields = ["criado_em", "status_display", "unidade_sigla", "itens"]


class PlanoContratacaoAnualDetalhadoSerializer(PlanoContratacaoAnualSerializer):
    """PCA com DFDs e itens aninhados — use na tela de detalhes."""

    dfds = DocumentoFormalizacaoDemandaSerializer(many=True, read_only=True)

    class Meta(PlanoContratacaoAnualSerializer.Meta):
        fields = PlanoContratacaoAnualSerializer.Meta.fields + ["dfds"]
