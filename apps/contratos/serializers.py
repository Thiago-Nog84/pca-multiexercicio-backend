from rest_framework import serializers
from .models import Contrato, Aditivo, Apostilamento, OrdemFornecimento
from .models_empenho import Empenho, EmpenhoProduto
from .models_conformidade import ChecklistConformidade, ItemChecklist


class AditivoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Aditivo
        fields = "__all__"


class ApostilamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Apostilamento
        fields = "__all__"


class OrdemFornecimentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdemFornecimento
        fields = "__all__"


class EmpenhoProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmpenhoProduto
        fields = "__all__"


class EmpenhoSerializer(serializers.ModelSerializer):
    produtos = EmpenhoProdutoSerializer(many=True, read_only=True)

    class Meta:
        model = Empenho
        fields = "__all__"


class ItemChecklistSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemChecklist
        fields = "__all__"


class ChecklistConformidadeSerializer(serializers.ModelSerializer):
    itens = ItemChecklistSerializer(many=True, read_only=True)
    responsavel_nome = serializers.CharField(source="responsavel.get_full_name", read_only=True)

    class Meta:
        model = ChecklistConformidade
        fields = "__all__"


class ContratoListSerializer(serializers.ModelSerializer):
    unidade_sigla = serializers.CharField(source="unidade_requisitante.sigla", read_only=True)
    fornecedor_nome = serializers.CharField(source="fornecedor.razao_social", read_only=True)

    class Meta:
        model = Contrato
        fields = [
            "id",
            "numero_contrato",
            "numero_sei",
            "numero_pncp",
            "tipo",
            "objeto",
            "status",
            "fornecedor",
            "fornecedor_nome",
            "contratado_razao_social",
            "contratado_cnpj_cpf",
            "unidade_requisitante",
            "unidade_sigla",
            "data_assinatura",
            "data_inicio_vigencia",
            "data_fim_vigencia",
            "valor_inicial",
            "valor_atual",
            "valor_empenhado",
            "saldo_disponivel",
        ]


class ContratoDetailSerializer(serializers.ModelSerializer):
    unidade_sigla = serializers.CharField(source="unidade_requisitante.sigla", read_only=True)
    fornecedor_nome = serializers.CharField(source="fornecedor.razao_social", read_only=True)
    aditivos = AditivoSerializer(many=True, read_only=True)
    apostilamentos = ApostilamentoSerializer(many=True, read_only=True)
    empenhos = EmpenhoSerializer(many=True, read_only=True)
    checklists = ChecklistConformidadeSerializer(many=True, read_only=True)

    class Meta:
        model = Contrato
        fields = "__all__"
