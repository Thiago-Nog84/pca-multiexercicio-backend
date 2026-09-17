from rest_framework import serializers
from .models import ProcessoLicitatorio, ItemLicitacao


class ItemLicitacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemLicitacao
        fields = "__all__"


class ProcessoLicitatorioListSerializer(serializers.ModelSerializer):
    modalidade_display = serializers.CharField(source="get_modalidade_display", read_only=True)
    quantidade_itens = serializers.IntegerField(source="itens.count", read_only=True)

    class Meta:
        model = ProcessoLicitatorio
        fields = [
            "id",
            "numero_edital",
            "numero_controle_pncp",
            "numero_compra_api",
            "ano",
            "modalidade",
            "modalidade_display",
            "situacao",
            "objeto",
            "processo_sei",
            "valor_estimado",
            "valor_homologado",
            "data_publicacao",
            "data_homologacao",
            "link_pncp",
            "lei",
            "quantidade_itens",
        ]


class ProcessoLicitatorioDetailSerializer(serializers.ModelSerializer):
    modalidade_display = serializers.CharField(source="get_modalidade_display", read_only=True)
    itens = ItemLicitacaoSerializer(many=True, read_only=True)

    class Meta:
        model = ProcessoLicitatorio
        fields = "__all__"
