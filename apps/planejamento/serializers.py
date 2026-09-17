from rest_framework import serializers
from .models import (
    DocumentoOficializacaoDemanda,
    EquipePlanejamentoTI,
    ETP,
    MatrizRisco,
    RiscoItem,
    TermoReferencia,
)


class EquipePlanejamentoTISerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipePlanejamentoTI
        fields = "__all__"


class RiscoItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiscoItem
        fields = "__all__"


class MatrizRiscoSerializer(serializers.ModelSerializer):
    itens = RiscoItemSerializer(many=True, read_only=True)

    class Meta:
        model = MatrizRisco
        fields = "__all__"


class TermoReferenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TermoReferencia
        fields = "__all__"


class ETPSerializer(serializers.ModelSerializer):
    matriz_risco = MatrizRiscoSerializer(read_only=True)
    termo_referencia = TermoReferenciaSerializer(read_only=True)

    class Meta:
        model = ETP
        fields = "__all__"


class DocumentoOficializacaoDemandaListSerializer(serializers.ModelSerializer):
    valor_total = serializers.DecimalField(source="valor_total_estimado", max_digits=16, decimal_places=2, read_only=True)
    quantidade_itens = serializers.IntegerField(source="itens.count", read_only=True)

    class Meta:
        model = DocumentoOficializacaoDemanda
        fields = [
            "id",
            "pca",
            "identificador",
            "numero_sei",
            "objeto",
            "status",
            "unidade_orcamentaria",
            "natureza_objeto",
            "solucao_tic",
            "item_continuado",
            "com_demo",
            "grau_prioridade",
            "quantidade_itens",
            "valor_total",
            "criado_em",
        ]


class DocumentoOficializacaoDemandaDetailSerializer(serializers.ModelSerializer):
    equipe_planejamento_ti = EquipePlanejamentoTISerializer(read_only=True)
    etp = ETPSerializer(read_only=True)
    valor_total = serializers.DecimalField(source="valor_total_estimado", max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = DocumentoOficializacaoDemanda
        fields = "__all__"
