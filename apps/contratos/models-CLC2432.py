from decimal import Decimal

from django.conf import settings
from django.db import models

# Ato PGJ 1415/2024: serviços contínuos — prazo mín. 24 meses, máx. 120 meses
# Ato PGJ 0462/2013: fiscalização de contratos (mantido até revogação expressa)
# Equipe de gestão TI (quadripartite) — Res. CNMP 283/2024, art. 36


class Contrato(models.Model):
    STATUS = [
        ("vigente", "Vigente"),
        ("suspenso", "Suspenso"),
        ("rescindido", "Rescindido"),
        ("encerrado", "Encerrado"),
    ]

    orgao = models.ForeignKey("core.Orgao", on_delete=models.CASCADE)
    processo_licitatorio = models.ForeignKey(
        "licitacao.ProcessoLicitatorio", null=True, blank=True, on_delete=models.SET_NULL
    )
    numero_contrato = models.CharField(max_length=30)
    ano = models.PositiveSmallIntegerField()
    numero_sei = models.CharField(max_length=30, blank=True, help_text="Número do processo SEI/MPPI do contrato")
    objeto = models.TextField()
    contratado_cnpj = models.CharField(max_length=18)
    contratado_razao = models.CharField(max_length=255)
    valor_inicial = models.DecimalField(max_digits=16, decimal_places=2)
    valor_atual = models.DecimalField(max_digits=16, decimal_places=2)
    data_assinatura = models.DateField()
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField()
    # Serviços contínuos — Ato PGJ 1415/2024
    is_servico_continuo = models.BooleanField(default=False)
    prazo_maximo_meses = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Máx. 120 meses — art. 5º Ato PGJ 1415/2024"
    )
    status = models.CharField(max_length=15, choices=STATUS, default="vigente")
    # Gestão — Ato PGJ 1414/2024 + Ato PGJ 0462/2013
    gestor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="contratos_geridos"
    )
    fiscal_adm = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="contratos_fiscal_adm"
    )
    fiscal_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="contratos_fiscal_tecnico"
    )
    # TI — Res. CNMP 283/2024, art. 36 (quadripartite)
    fiscal_requisitante_ti = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contratos_fiscal_req_ti",
    )
    is_contrato_ti = models.BooleanField(default=False)
    # PNCP
    pncp_id = models.CharField(max_length=100, blank=True)
    publicado_pncp = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("orgao", "numero_contrato", "ano")

    def __str__(self):
        return f"Contrato {self.numero_contrato}/{self.ano}"

    @property
    def saldo_contratual(self):
        empenhado = self.ordens_fornecimento.filter(status__in=["emitida", "atendida"]).aggregate(
            total=models.Sum("valor_total")
        )["total"] or Decimal("0")
        return self.valor_atual - empenhado

    @property
    def dias_para_vencimento(self):
        from django.utils import timezone

        return (self.data_fim_vigencia - timezone.now().date()).days

    @property
    def exige_alerta_renovacao(self):
        """
        Res. CNMP 283/2024, art. 39: verificação com mínimo 120 dias de antecedência
        para prorrogação/renovação de contratos de TI.
        """
        if self.is_contrato_ti:
            return self.dias_para_vencimento <= 120
        return self.dias_para_vencimento <= 90


class Aditivo(models.Model):
    TIPO = [
        ("prazo", "Prorrogação de prazo"),
        ("valor", "Acréscimo de valor"),
        ("prazo_valor", "Prazo e valor"),
        ("supressao", "Supressão"),
        ("objeto", "Alteração de objeto"),
    ]

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="aditivos")
    numero = models.PositiveSmallIntegerField()
    tipo = models.CharField(max_length=20, choices=TIPO)
    data_assinatura = models.DateField()
    novo_valor = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    nova_data_fim = models.DateField(null=True, blank=True)
    fundamento_legal = models.CharField(max_length=100)
    justificativa = models.TextField()
    numero_sei = models.CharField(max_length=30, blank=True)
    pncp_id = models.CharField(max_length=100, blank=True)
    publicado_pncp = models.BooleanField(default=False)

    def clean(self):
        """Valida prazo máximo para serviços contínuos (Ato PGJ 1415/2024)."""
        from django.core.exceptions import ValidationError

        if self.nova_data_fim and self.contrato.is_servico_continuo:
            meses = (self.nova_data_fim.year - self.contrato.data_inicio_vigencia.year) * 12 + (
                self.nova_data_fim.month - self.contrato.data_inicio_vigencia.month
            )
            prazo_max = self.contrato.prazo_maximo_meses or 120
            if meses > prazo_max:
                raise ValidationError(
                    f"Prazo total ({meses} meses) supera o máximo de {prazo_max} meses "
                    f"para serviços contínuos — art. 5º Ato PGJ 1415/2024."
                )


class Apostilamento(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="apostilamentos")
    numero = models.PositiveSmallIntegerField()
    data = models.DateField()
    descricao = models.TextField()
    numero_sei = models.CharField(max_length=30, blank=True)
    novo_indice_reajuste = models.CharField(max_length=50, blank=True)


class OrdemFornecimento(models.Model):
    """
    Ordem de Fornecimento / Ordem de Serviço (OS/OFB).
    Res. CNMP 283/2024, art. 38: OS/OFB para contratos de TI com campos obrigatórios.
    """

    STATUS = [("emitida", "Emitida"), ("atendida", "Atendida"), ("cancelada", "Cancelada")]

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="ordens_fornecimento")
    numero = models.CharField(max_length=30)
    data_emissao = models.DateField()
    data_entrega_prevista = models.DateField()
    data_atendimento = models.DateField(null=True, blank=True)
    descricao = models.TextField()
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS, default="emitida")
    # Para OS de TI (Res. CNMP 283/2024, art. 38)
    volume_servico = models.TextField(blank=True, help_text="Pontos de função, sprints, horas etc.")
    cronograma_execucao = models.TextField(blank=True)
    responsavel_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="oss_responsavel"
    )
