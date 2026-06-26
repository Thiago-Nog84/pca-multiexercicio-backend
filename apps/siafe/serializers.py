from rest_framework import serializers

from .models import SiafeLogConsulta


class SiafeLogConsultaSerializer(serializers.ModelSerializer):
    endpoint_display = serializers.CharField(source="get_endpoint_display", read_only=True)
    consultado_por_nome = serializers.CharField(source="consultado_por.get_full_name", read_only=True)

    class Meta:
        model = SiafeLogConsulta
        fields = [
            "id", "endpoint", "endpoint_display", "parametros",
            "status_http", "sucesso", "erro_detalhe",
            "tempo_resposta_ms", "consultado_por_nome", "criado_em",
        ]


# ---------------------------------------------------------------------------
# Serializers de resposta (documentação dos campos retornados pelo SIAFE)
# ---------------------------------------------------------------------------

class NotaEmpenhoSerializer(serializers.Serializer):
    """Campos típicos retornados pelo SIAFE em /nota-empenho."""
    id = serializers.IntegerField(read_only=True)
    codigoDocumento = serializers.CharField(read_only=True)
    codigoUgEmitente = serializers.CharField(read_only=True)
    exercicio = serializers.IntegerField(read_only=True)
    # Campos adicionais passados diretamente como JSON dinâmico


class SaldoOrcamentarioSerializer(serializers.Serializer):
    """Campos típicos do saldo orçamentário anual."""
    codigoUG = serializers.CharField(read_only=True)
    exercicio = serializers.IntegerField(read_only=True)
    dotacaoInicial = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    dotacaoAtual = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    empenhado = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    liquidado = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    pago = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    saldoDisponivel = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
