from decimal import Decimal
from django.db import models


class ProcessoLicitatorio(models.Model):
    class Modalidade(models.TextChoices):
        PREGAO_ELETRONICO = "pregao_eletronico", "Pregão Eletrônico"
        PREGAO_PRESENCIAL = "pregao_presencial", "Pregão Presencial"
        CONCORRENCIA_ELETRONICA = "concorrencia_eletronica", "Concorrência Eletrônica"
        CONCORRENCIA_PRESENCIAL = "concorrencia_presencial", "Concorrência Presencial"
        CONCURSO = "concurso", "Concurso"
        DISPENSA = "dispensa", "Dispensa de Licitação"
        INEXIGIBILIDADE = "inexigibilidade", "Inexigibilidade"
        OUTROS = "outros", "Outras Modalidades"

    numero_edital = models.CharField("Número do Edital/Aviso", max_length=50, default="", db_index=True)
    numero_controle_pncp = models.CharField("Número de Controle PNCP", max_length=100, blank=True, db_index=True)
    numero_compra_api = models.CharField("ID Compra Compras.gov", max_length=50, blank=True, db_index=True)
    ano = models.PositiveIntegerField("Ano", default=2026)
    modalidade = models.CharField("Modalidade", max_length=30, choices=Modalidade.choices, default=Modalidade.PREGAO_ELETRONICO)
    situacao = models.CharField("Situação", max_length=50, blank=True, default="Publicado")
    objeto = models.TextField("Objeto")
    processo_sei = models.CharField("Processo Administrativo/SEI", max_length=100, blank=True)
    valor_estimado = models.DecimalField("Valor Estimado (R$)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    valor_homologado = models.DecimalField("Valor Homologado (R$)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    data_publicacao = models.DateField("Data de Publicação", null=True, blank=True)
    data_homologacao = models.DateField("Data de Homologação/Atualização", null=True, blank=True)
    link_pncp = models.URLField("Link PNCP", max_length=500, blank=True)
    lei = models.CharField("Amparo Legal / Lei", max_length=50, default="Lei 14.133/2021")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Processo Licitatório"
        verbose_name_plural = "Processos Licitatórios"
        ordering = ["-ano", "-data_publicacao", "-id"]

    def __str__(self):
        return f"{self.get_modalidade_display()} nº {self.numero_edital} ({self.ano})"

    @property
    def arps_vinculadas(self):
        from apps.srp.models import AtaRegistroPrecos
        if self.numero_controle_pncp:
            prefixo = self.numero_controle_pncp.split("-0000")[0] if "-0000" in self.numero_controle_pncp else self.numero_controle_pncp
            qs = AtaRegistroPrecos.objects.filter(numero_pncp__icontains=prefixo)
            if qs.exists():
                return qs
        if self.numero_edital:
            num_limpo = self.numero_edital.lstrip("0")
            if num_limpo and len(num_limpo) > 2:
                qs = AtaRegistroPrecos.objects.filter(processo_licitatorio__icontains=num_limpo)
                if qs.exists():
                    return qs
        return AtaRegistroPrecos.objects.none()

    @property
    def contratos_vinculados(self):
        from apps.contratos.models import Contrato
        if self.numero_controle_pncp:
            prefixo = self.numero_controle_pncp.split("-0000")[0] if "-0000" in self.numero_controle_pncp else self.numero_controle_pncp
            qs = Contrato.objects.filter(numero_pncp__icontains=prefixo)
            if qs.exists():
                return qs
        if self.processo_sei and len(self.processo_sei) > 5:
            qs = Contrato.objects.filter(numero_sei__icontains=self.processo_sei)
            if qs.exists():
                return qs
        return Contrato.objects.none()


class ItemLicitacao(models.Model):
    licitacao = models.ForeignKey(ProcessoLicitatorio, on_delete=models.CASCADE, related_name="itens")
    numero_item = models.PositiveIntegerField("Número do Item")
    descricao = models.TextField("Descrição")
    unidade = models.CharField("Unidade", max_length=50, blank=True)
    quantidade = models.DecimalField("Quantidade", max_digits=15, decimal_places=4, default=Decimal("0.0000"))
    valor_unitario_estimado = models.DecimalField("Valor Unit. Estimado (R$)", max_digits=15, decimal_places=4, default=Decimal("0.0000"))
    valor_unitario_homologado = models.DecimalField("Valor Unit. Homologado (R$)", max_digits=15, decimal_places=4, default=Decimal("0.0000"))
    fornecedor_vencedor = models.CharField("Fornecedor Vencedor", max_length=200, blank=True)
    cnpj_vencedor = models.CharField("CNPJ Vencedor", max_length=20, blank=True)

    class Meta:
        verbose_name = "Item de Licitação"
        verbose_name_plural = "Itens de Licitação"
        ordering = ["numero_item"]

    def __str__(self):
        return f"Item {self.numero_item} - {self.licitacao.numero_edital}"
