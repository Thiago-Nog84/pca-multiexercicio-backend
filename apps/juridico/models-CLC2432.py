from decimal import Decimal

from django.conf import settings
from django.db import models

# APPL — Assessoria para Pareceres em Processos Licitatórios (Ato PGJ 1414/2024, art. 14)
# Ato PGJ 1383/2024: dispensa de manifestação jurídica para pequeno valor

# Limites atualizados pelo Decreto Federal 12.807/2025
LIMITE_DISPENSA_I = Decimal("50000.00")  # bens e serviços — art. 75, I
LIMITE_DISPENSA_II = Decimal("100000.00")  # obras e serviços de engenharia — art. 75, II


class ControleJuridico(models.Model):
    """
    Registra se um processo exige ou não manifestação da APPL
    com base no Ato PGJ 1383/2024 e nos limites vigentes.
    """

    SITUACAO = [
        ("dispensado", "Dispensado — Ato PGJ 1383/2024"),
        ("obrigatorio", "Obrigatório — exige manifestação APPL"),
        ("pendente", "Pendente de análise"),
        ("manifestacao_emitida", "Manifestação emitida pela APPL"),
        ("aprovado", "Aprovado pela APPL"),
        ("reprovado", "Reprovado pela APPL"),
    ]

    etp = models.OneToOneField(
        "planejamento.ETP", on_delete=models.CASCADE, related_name="controle_juridico", null=True, blank=True
    )
    valor_estimado = models.DecimalField(max_digits=16, decimal_places=2)
    tipo_contratacao = models.CharField(max_length=30)
    situacao = models.CharField(max_length=25, choices=SITUACAO)
    fundamento_dispensa = models.TextField(
        blank=True, help_text="Ex: art. 75, I — R$ X < R$ 50.000 — Ato PGJ 1383/2024"
    )
    numero_parecer_appl = models.CharField(max_length=30, blank=True)
    data_manifestacao = models.DateField(null=True, blank=True)
    parecer_appl = models.TextField(blank=True)
    numero_sei_parecer = models.CharField(max_length=30, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    @classmethod
    def verificar_dispensa(cls, valor: Decimal, tipo: str, usa_modelo_padrao: bool) -> dict:
        """
        Verifica se a contratação dispensa manifestação da APPL.
        Lógica: Ato PGJ 1383/2024, art. 1º.
        """
        if not usa_modelo_padrao:
            return {"dispensado": False, "motivo": "Contrato não baseado em modelo padronizado do MPPI"}

        limite = LIMITE_DISPENSA_II if tipo == "obras" else LIMITE_DISPENSA_I
        if valor <= limite:
            return {
                "dispensado": True,
                "fundamento": f"Ato PGJ 1383/2024, art. 1º — valor (R$ {valor}) abaixo do limite (R$ {limite})",
            }
        return {"dispensado": False, "motivo": f"Valor (R$ {valor}) supera o limite de dispensa (R$ {limite})"}


class ManifestacaoJuridicoReferencial(models.Model):
    """
    MJR — Manifestação Jurídico Referencial do MPPI.
    Orientações consolidadas da APPL para situações recorrentes.
    Referência: MJR 56/2025, 66/2025, 86/2025, 92/2024, 95/2025.
    """

    TEMAS = [
        ("substituicao_marca", "MJR 56/2025 — Substituição de Marca"),
        ("pagamento_indenizacao", "MJR 66/2025 — Pagamento por Indenização"),
        ("adesao_arp", "MJR 86/2025 — Adesão a ARP (Carona)"),
        ("dispensa_75_i_ii", "MJR 92/2024 — Dispensa Art. 75 I e II"),
        ("prorrogacao_arp", "MJR 95/2025 — Prorrogação de ARP"),
    ]

    numero = models.CharField(max_length=20, unique=True)
    tema = models.CharField(max_length=30, choices=TEMAS)
    titulo = models.CharField(max_length=255)
    ementa = models.TextField()
    conclusao = models.TextField()
    fundamentos_legais = models.TextField()
    numero_sei = models.CharField(max_length=30, blank=True)
    data_publicacao = models.DateField()
    vigente = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Manifestação Jurídico Referencial (MJR)"
        ordering = ["-data_publicacao"]

    def __str__(self):
        return self.numero
