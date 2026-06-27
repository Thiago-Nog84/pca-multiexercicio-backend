"""
Módulo SRP — Sistema de Registro de Preços
Lei 14.133/2021, arts. 82–86 | Decreto Federal 11.462/2023
Decreto Estadual 21.938/2023 (subsidiário para o MPPI)
4 dimensões obrigatórias:
  1. ARPs originadas       — atas geradas pelo MPPI como órgão gerenciador
  2. Contratações          — pedidos de fornecimento decorrentes de ARP própria
  3. Caronas cedidas       — adesões de outros órgãos à ARP do MPPI
  4. Caronas recebidas     — ARPs de outros órgãos às quais o MPPI aderiu
REGRA CRÍTICA (Decreto 11.462/2023, art. 9º):
  O quantitativo total de adesões por item não pode ultrapassar 50% do
  quantitativo originalmente registrado. Violação gera nulidade contratual
  e exposição ao TCU. A validação é feita em AdesaoARP.save().
"""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
class AtaRegistroPrecos(models.Model):
    """
    ARP originada pelo MPPI como órgão gerenciador.
    Fundamento: arts. 82–86 NLLC + Decreto 11.462/2023, art. 4º.
    """
    STATUS = [
        ("vigente", "Vigente"),
        ("suspensa", "Suspensa"),
        ("cancelada", "Cancelada"),
        ("encerrada", "Encerrada (vigência expirada)"),
    ]
    MODALIDADE_ORIGEM = [
        ("pregao_eletronico", "Pregão Eletrônico"),
        ("concorrencia", "Concorrência"),
        ("dispensa_srp", "Dispensa para SRP (art. 75, §7º NLLC)"),
    ]
    orgao_gerenciador = models.ForeignKey(
        "core.Orgao",
        on_delete=models.PROTECT,
        related_name="arps_gerenciadas",
    )
    numero_arp = models.CharField(
        max_length=30,
        help_text="Número sequencial da ARP no exercício (ex: 001/2027)",
    )
    # Integração API Compras.gov.br
    codigo_uasg_gerenciadora = models.CharField(
        max_length=10,
        blank=True,
        help_text="Código UASG do órgão gerenciador (MPPI = 926092). "
                  "Necessário para consultar e sincronizar dados via API Compras.gov.br.",
    )
    numero_controle_pncp_ata = models.CharField(
        max_length=100,
        blank=True,
        help_text="Número de controle da ata no PNCP (retornado pela API Compras.gov.br)",
    )
    id_compra_compras_gov = models.CharField(
        max_length=100,
        blank=True,
        help_text="Identificador único da compra no Compras.gov.br (campo idCompra da API)",
    )
    importada_da_api = models.BooleanField(
        default=False,
        help_text="Indica se a ARP foi importada automaticamente via API Compras.gov.br",
    )
    numero_sei = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo SEI/MPPI (obrigatório para rastreabilidade)",
    )
    numero_pncp = models.CharField(
        max_length=100,
        blank=True,
        help_text="Identificador de publicação no PNCP (condição de eficácia — art. 174 NLLC)",
    )
    objeto = models.TextField()
    modalidade_origem = models.CharField(max_length=20, choices=MODALIDADE_ORIGEM)
    processo_licitatorio = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo licitatório que originou a ARP",
    )
    fornecedor_razao_social = models.CharField(max_length=255)
    fornecedor_cnpj_cpf = models.CharField(max_length=18)
    data_assinatura = models.DateField()
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField(
        help_text="Máximo 12 meses da assinatura (Decreto 11.462/2023, art. 4º, §2º)",
    )
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)
    link_ata_pncp = models.URLField(
        max_length=300,
        blank=True,
        help_text="URL da ata no PNCP (ex: https://pncp.gov.br/app/atas/05805924000189/2024/16/1). "
                  "Usada para consultar contratos e histórico via PNCP REST API.",
    )
    link_documento_mppi = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="Link do documento (MPPI)",
        help_text=(
            "URL do texto integral da ARP publicado no site do MPPI "
            "(ex: https://www.mppi.mp.br/internet/wp-content/uploads/2025/12/ARP-54-2025_merged.pdf). "
            "Exibido como botão 'Ver texto da ARP' na página de detalhe."
        ),
    )
    # Prorrogação de vigência (Termo Aditivo — art. 84 Lei 14.133/2021)
    prorrogada = models.BooleanField(
        default=False,
        verbose_name="Prorrogada",
        help_text="Vigência prorrogada por Termo Aditivo",
    )
    data_fim_vigencia_original = models.DateField(
        null=True, blank=True,
        verbose_name="Fim vigência original",
        help_text="Data fim original antes da prorrogação",
    )
    quantitativos_renovados = models.BooleanField(
        default=False,
        verbose_name="Quantitativos renovados",
        help_text="Se True, os quantitativos foram renovados junto com a prorrogação",
    )
    data_prorrogacao = models.DateField(
        null=True, blank=True,
        verbose_name="Data da prorrogação",
        help_text="Data de publicação da prorrogação no PNCP",
    )
    status = models.CharField(max_length=15, choices=STATUS, default="vigente")
    usa_lotes = models.BooleanField(
        default=False,
        verbose_name="Usa lotes",
        help_text=(
            "Marque quando a licitação foi dividida em lotes (ex: Lote 1 – Material de "
            "Escritório, Lote 2 – Café). Desmarque para indicar lote único. "
            "Quando marcado, cada ItemARP deve ter o campo 'numero_lote' preenchido."
        ),
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Ata de Registro de Preços"
        verbose_name_plural = "Atas de Registro de Preços"
        ordering = ["-data_inicio_vigencia"]
        unique_together = ("orgao_gerenciador", "numero_arp")
    def __str__(self):
        return f"ARP {self.numero_arp} — {self.fornecedor_razao_social[:40]}"
    @property
    def esta_vigente(self):
        from datetime import date
        return self.status == "vigente" and self.data_fim_vigencia >= date.today()
class ItemARP(models.Model):
    """
    Item registrado na ARP com quantidade, valor unitário e saldo disponível.
    O saldo é debitado automaticamente a cada ContratacaoDecorrente ou AdesaoARP.
    """
    BANCO_REFERENCIA = [
        ("catmat", "CATMAT (Catálogo de Materiais)"),
        ("catser", "CATSER (Catálogo de Serviços)"),
        ("sinapi", "SINAPI (Sistema Nacional de Pesquisa de Custos)"),
        ("orse", "ORSE (Orçamento de Obras e Serviços de Engenharia)"),
        ("outro", "Outro"),
    ]
    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    numero_lote = models.CharField(
        max_length=20,
        blank=True,
        help_text="Número do lote ao qual o item pertence (ex: Lote 1, Lote 2)",
    )
    numero_item = models.PositiveIntegerField()
    # Catálogo e referência
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    codigo_referencia_banco = models.CharField(
        max_length=30,
        blank=True,
        help_text="Código de referência em banco de custos (ex: código SINAPI 91871, ORSE 9718)",
    )
    banco_referencia = models.CharField(
        max_length=10,
        choices=BANCO_REFERENCIA,
        blank=True,
        help_text="Banco de preços de referência utilizado (SINAPI, ORSE, CATMAT, etc.)",
    )
    descricao = models.TextField()
    unidade_fornecimento = models.CharField(max_length=30)
    quantidade_registrada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    # Integração API Compras.gov.br
    codigo_item_compras_gov = models.IntegerField(
        null=True,
        blank=True,
        help_text="codigoItem retornado pela API Compras.gov.br (código PDM/CATMAT numérico)",
    )
    maximo_adesao_api = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Quantidade máxima para adesão (carona) conforme API Compras.gov.br. "
                  "Se zero, carona não está liberada no sistema — exige SEI de autorização.",
    )
    importado_da_api = models.BooleanField(
        default=False,
        help_text="Indica se o item foi importado via API Compras.gov.br",
    )
    # Saldo calculado — atualizado a cada contratação/adesão
    quantidade_contratada = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0")
    )
    quantidade_cedida_carona = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Total cedido a órgãos aderentes via carona",
    )
    class Meta:
        verbose_name = "Item de ARP"
        ordering = ["numero_item"]
        unique_together = ("arp", "numero_item")

    def __str__(self):
        return f"Item {self.numero_item} — {self.descricao[:50]}"

    def clean(self):
        """Exige numero_lote quando a ARP usa lotes."""
        if self.arp_id and self.arp.usa_lotes and not (self.numero_lote or "").strip():
            raise ValidationError(
                "Esta ARP está dividida em lotes. "
                "Informe o número do lote (campo 'numero_lote') para este item."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------ #
    # Propriedades de quantidade                                           #
    # ------------------------------------------------------------------ #

    @property
    def quantidade_disponivel(self):
        return self.quantidade_registrada - self.quantidade_contratada - self.quantidade_cedida_carona

    # ------------------------------------------------------------------ #
    # Propriedades de valor (R$)                                          #
    # Permite planejar aquisições com base no saldo financeiro da ARP.    #
    # ------------------------------------------------------------------ #

    @property
    def valor_total_registrado(self):
        """Valor total registrado na ARP para este item (quantidade × preço unitário)."""
        return self.quantidade_registrada * self.valor_unitario

    @property
    def valor_total_contratado(self):
        """
        Soma dos valores efetivamente contratados via ContratacaoDecorrente.
        Usa o valor_total de cada contratação (pode diferir do preço da ARP em ajustes).
        """
        from django.db.models import Sum as _Sum
        result = self.contratacoes.exclude(status="cancelado").aggregate(
            total=_Sum("valor_total")
        )["total"]
        return result or Decimal("0")

    @property
    def valor_cedido_carona(self):
        """Valor total cedido a órgãos aderentes (caronas autorizadas)."""
        from django.db.models import Sum as _Sum
        result = self.adesoes.filter(status="autorizada").aggregate(
            total=_Sum("valor_total")
        )["total"]
        return result or Decimal("0")

    @property
    def valor_disponivel(self):
        """
        Saldo financeiro disponível na ARP:
          registrado − contratado − cedido_carona.
        Não considera compromissos futuros do PCA.
        """
        return self.valor_total_registrado - self.valor_total_contratado - self.valor_cedido_carona

    @property
    def valor_comprometido_pca(self):
        """
        Valor comprometido por demandas aprovadas no PCA, calculado como:
          Σ (quantidade_comprometida × valor_unitario_do_item).
        Representa aquisições certas — não é saldo disponível.
        """
        result = self.vinculos_pca.aggregate(
            total=models.Sum("quantidade_comprometida")
        )["total"]
        qtd = result or Decimal("0")
        return qtd * self.valor_unitario

    @property
    def valor_disponivel_eventual(self):
        """
        Saldo financeiro não comprometido com PCA e ainda não contratado.
        Fórmula: registrado − comprometido_pca − contratado − cedido_carona.
        Exemplo: ARP R$ 120k − PCA R$ 50k − contratado R$ 60k = R$ 10k eventual.
        """
        return (
            self.valor_total_registrado
            - self.valor_comprometido_pca
            - self.valor_total_contratado
            - self.valor_cedido_carona
        )

    @property
    def limite_carona_por_aderente(self):
        """
        50% do quantitativo por item por órgão aderente.
        Decreto 11.462/2023, art. 9º.
        """
        return self.quantidade_registrada * Decimal("0.5")
    @property
    def quantidade_comprometida_pca(self):
        """
        Soma das quantidades vinculadas a demandas aprovadas no PCA (aquisição certa).
        NÃO deve ser somada com quantidade_disponivel — são naturezas distintas:
        uma é dotação comprometida, a outra é registro em ata.
        Exemplo: ARP com 5 veículos → PCA comprometeu 1 → quantidade_comprometida_pca = 1.
        """
        result = self.vinculos_pca.aggregate(
            total=models.Sum("quantidade_comprometida")
        )["total"]
        return result or Decimal("0")
    @property
    def quantidade_disponivel_eventual(self):
        """
        Saldo da ARP não comprometido com demanda do PCA e ainda não contratado.
        Representa itens que podem ser eventualmente adquiridos ou cedidos via carona.
        Fórmula: registrada − comprometida_pca − contratada − cedida_carona.
        Exemplo: 5 registrados − 1 PCA − 0 contratados − 0 caronas = 4 eventuais.
        """
        return (
            self.quantidade_registrada
            - self.quantidade_comprometida_pca
            - self.quantidade_contratada
            - self.quantidade_cedida_carona
        )
class VinculoPCAItemARP(models.Model):
    """
    Vínculo entre uma demanda aprovada no PCA e um item da ARP.
    Representa a quantidade "comprometida" pela demanda do PCA,
    em contraste com o saldo disponível na ARP para eventual aquisição.
    Exemplo:
        ItemARP: 5 veículos sedan registrados
        ItemPCA (CAA): demanda de 1 veículo sedan aprovada no PCA 2027
        VinculoPCAItemARP.quantidade_comprometida = 1
        → 1 veículo é aquisição certa (dotação comprometida)
        → 4 veículos são eventuais (disponíveis na ARP sem compromisso orçamentário)
    Um ItemARP pode ter vários vínculos (demandas de unidades diferentes
    ou exercícios diferentes — multiexercício). A soma nunca pode exceder
    a quantidade_registrada na ARP.
    Também resolve o cenário de lotes: múltiplos ItemPCAs (detergente, sabão,
    saco de lixo) podem ser vinculados ao mesmo ItemARP quando agrupados em lote.
    """
    item_pca = models.ForeignKey(
        "pca.ItemPCA",
        on_delete=models.CASCADE,
        related_name="vinculos_arp",
        limit_choices_to={"is_srp": True},
        help_text="Apenas itens marcados como SRP podem ser vinculados a uma ARP",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        on_delete=models.CASCADE,
        related_name="vinculos_pca",
    )
    quantidade_comprometida = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text=(
            "Quantidade do PCA vinculada a este item da ARP. "
            "É a demanda certa — não pode ser somada ao saldo disponível."
        ),
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vinculos_pca_arp_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "Vínculo PCA × ARP"
        verbose_name_plural = "Vínculos PCA × ARP"
        unique_together = ("item_pca", "item_arp")
    def __str__(self):
        return (
            f"PCA Item {self.item_pca_id} → ARP Item {self.item_arp_id} "
            f"({self.quantidade_comprometida})"
        )
    def clean(self):
        """
        Valida:
        1. Que a ARP está vigente (status='vigente' e dentro do prazo).
        2. Que a soma das quantidades comprometidas não excede a quantidade registrada.
        3. Coerência de lote: se ItemPCA tem numero_lote_pca e ItemARP tem numero_lote,
           os valores devem coincidir para evitar vínculos cruzados entre lotes.
        """
        from datetime import date
        # Regra 1 — Vigência da ARP
        arp = self.item_arp.arp
        if arp.status != "vigente":
            raise ValidationError(
                f"A ARP {arp.numero_arp} está com status '{arp.get_status_display()}'. "
                f"Só é possível vincular demandas a ARPs vigentes."
            )
        if arp.data_fim_vigencia < date.today():
            raise ValidationError(
                f"A ARP {arp.numero_arp} venceu em {arp.data_fim_vigencia:%d/%m/%Y}. "
                f"Não é possível vincular demandas a ARPs com vigência expirada."
            )
        # Regra 2 — Não exceder quantidade registrada
        total_ja_comprometido = (
            VinculoPCAItemARP.objects.filter(item_arp=self.item_arp)
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum("quantidade_comprometida"))["total"]
            or Decimal("0")
        )
        novo_total = total_ja_comprometido + self.quantidade_comprometida
        if novo_total > self.item_arp.quantidade_registrada:
            raise ValidationError(
                f"Total comprometido ({novo_total}) excede a quantidade registrada "
                f"na ARP ({self.item_arp.quantidade_registrada}). "
                f"Já comprometido: {total_ja_comprometido} | "
                f"Tentativa: {self.quantidade_comprometida}."
            )
        # Regra 3 — Coerência de lote
        # Só valida quando ambos os lados têm lote informado; se um está vazio,
        # não há como afirmar incompatibilidade (tolerância para dados parciais).
        lote_pca = (self.item_pca.numero_lote_pca or "").strip()
        lote_arp = (self.item_arp.numero_lote or "").strip()
        if lote_pca and lote_arp and lote_pca != lote_arp:
            raise ValidationError(
                f"Incompatibilidade de lote: o ItemPCA está no lote '{lote_pca}' "
                f"mas o ItemARP selecionado pertence ao lote '{lote_arp}' da ARP "
                f"{arp.numero_arp}. Vincule itens do mesmo lote."
            )
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
class ContratacaoDecorrente(models.Model):
    """
    Pedido de fornecimento emitido com base em ARP própria do MPPI.
    Cada contratação debita o saldo do ItemARP correspondente.
    Fundamento: Decreto 11.462/2023, art. 7º.
    """
    STATUS = [
        ("emitido", "Emitido"),
        ("em_execucao", "Em execução"),
        ("concluido", "Concluído"),
        ("cancelado", "Cancelado"),
    ]
    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.PROTECT,
        related_name="contratacoes_decorrentes",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        on_delete=models.PROTECT,
        related_name="contratacoes",
    )
    numero_pedido = models.CharField(max_length=30)
    numero_contrato = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Número do contrato",
        help_text=(
            "Número formal do contrato decorrente desta ARP (ex: 123/2026). "
            "Distinto do número do pedido — é o instrumento contratual assinado."
        ),
    )
    exercicio = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Exercício",
        help_text=(
            "Ano fiscal em que a contratação foi emitida. "
            "Permite calcular o saldo consumido por ano na ARP."
        ),
    )
    numero_sei = models.CharField(max_length=30, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    data_emissao = models.DateField()
    data_entrega_prevista = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="emitido")
    unidade_requisitante = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratacoes_decorrentes",
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratacoes_decorrentes_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "Contratação Decorrente de ARP"
        verbose_name_plural = "Contratações Decorrentes de ARP"
    def __str__(self):
        ref = self.numero_contrato or self.numero_pedido
        return f"{ref} — ARP {self.arp.numero_arp}"

    def save(self, *args, **kwargs):
        """
        Debita o saldo do item ao criar e preenche `exercicio`
        automaticamente a partir de `data_emissao` quando não informado.
        """
        if self.data_emissao and not self.exercicio:
            self.exercicio = self.data_emissao.year
        if not self.pk:
            # Nova contratação — debita saldo
            self.item_arp.quantidade_contratada += self.quantidade
            self.item_arp.save(update_fields=["quantidade_contratada"])
        super().save(*args, **kwargs)
class AdesaoARP(models.Model):
    """
    Carona CEDIDA: outro órgão aderiu à ARP do MPPI.
    Valida o limite de 50% do quantitativo por item por aderente.
    Fundamento: Decreto 11.462/2023, art. 9º.
    ATENÇÃO: violação do limite de 50% gera nulidade contratual
    e exposição ao TCU (Acórdão TCU 1507/2024).
    """
    STATUS = [
        ("solicitada", "Solicitada"),
        ("autorizada", "Autorizada"),
        ("recusada", "Recusada"),
        ("cancelada", "Cancelada"),
    ]
    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.PROTECT,
        related_name="adesoes",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        on_delete=models.PROTECT,
        related_name="adesoes",
    )
    orgao_aderente_nome = models.CharField(max_length=255)
    orgao_aderente_cnpj = models.CharField(max_length=18)
    quantidade_solicitada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    data_solicitacao = models.DateField()
    data_autorizacao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="solicitada")
    numero_sei_autorizacao = models.CharField(max_length=30, blank=True)
    observacoes = models.TextField(blank=True)
    autorizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adesoes_autorizadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "Adesão à ARP (Carona Cedida)"
        verbose_name_plural = "Adesões à ARP (Caronas Cedidas)"
    def __str__(self):
        return f"Carona — {self.orgao_aderente_nome[:40]} → ARP {self.arp.numero_arp}"
    def clean(self):
        """
        Valida:
        1. Limite de 50% por item por órgão aderente (Decreto 11.462/2023, art. 9º).
        2. Se maximo_adesao_api == 0 (carona bloqueada no Compras.gov), exige SEI
           de autorização — o MPPI pode liberar via SEI mesmo quando o sistema
           central indica bloqueio por questão cadastral.
        """
        # Regra 1 — Limite de 50%
        limite = self.item_arp.limite_carona_por_aderente
        total_ja_cedido = (
            AdesaoARP.objects.filter(
                item_arp=self.item_arp,
                orgao_aderente_cnpj=self.orgao_aderente_cnpj,
                status="autorizada",
            )
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum("quantidade_solicitada"))["total"]
            or Decimal("0")
        )
        if total_ja_cedido + self.quantidade_solicitada > limite:
            raise ValidationError(
                f"Limite de 50% por item por aderente excedido "
                f"(Decreto 11.462/2023, art. 9º). "
                f"Limite: {limite} | Já cedido: {total_ja_cedido} | "
                f"Solicitado: {self.quantidade_solicitada}."
            )
        # Regra 2 — Carona bloqueada no Compras.gov (maximoAdesao = 0)
        # Não bloqueia o cadastro, mas exige SEI de autorização do MPPI
        if (
            self.item_arp.maximo_adesao_api is not None
            and self.item_arp.maximo_adesao_api == Decimal("0")
            and not self.numero_sei_autorizacao
        ):
            raise ValidationError(
                "Esta ARP está com carona desabilitada no Compras.gov.br "
                "(maximoAdesao = 0). Para prosseguir, informe o número do "
                "processo SEI/MPPI que autoriza a adesão."
            )
    def save(self, *args, **kwargs):
        self.full_clean()
        if self.status == "autorizada" and not self.pk:
            self.item_arp.quantidade_cedida_carona += self.quantidade_solicitada
            self.item_arp.save(update_fields=["quantidade_cedida_carona"])
        super().save(*args, **kwargs)
class ContratoComprasnet(models.Model):
    """
    Contrato importado da API pública do Comprasnet Contratos
    (contratos.comprasnet.gov.br/api/contrato/ug/{uasg}).
    Vinculado à ARP quando o licitacao_numero corresponde ao processo_licitatorio
    de uma AtaRegistroPrecos. O vínculo é opcional — contratos de dispensas ou
    concorrências que não originaram ARPs ficam sem FK.
    """
    SITUACAO = [
        ("Ativo", "Ativo"),
        ("Inativo", "Inativo"),
    ]
    contrato_comprasnet_id = models.IntegerField(
        unique=True,
        help_text="ID interno do contrato na API Comprasnet Contratos",
    )
    arp = models.ForeignKey(
        AtaRegistroPrecos,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_comprasnet",
        help_text="ARP da qual este contrato é decorrente (se identificada)",
    )
    numero = models.CharField(max_length=30, help_text="Número do contrato (ex: 00005/2026)")
    objeto = models.TextField(blank=True)
    fornecedor_nome = models.CharField(max_length=255, blank=True)
    fornecedor_cnpj = models.CharField(max_length=18, blank=True)
    valor_inicial = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    valor_global = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    valor_acumulado = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    vigencia_inicio = models.DateField(null=True, blank=True)
    vigencia_fim = models.DateField(null=True, blank=True)
    data_assinatura = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=20, blank=True, default="Ativo")
    modalidade = models.CharField(max_length=50, blank=True)
    categoria = models.CharField(max_length=50, blank=True)
    licitacao_numero = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do pregão/licitação que originou o contrato",
    )
    processo = models.CharField(max_length=60, blank=True)
    uasg = models.CharField(max_length=10, blank=True)
    importado_em = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Contrato (Comprasnet)"
        verbose_name_plural = "Contratos (Comprasnet)"
        ordering = ["-data_assinatura"]
    def __str__(self):
        return f"Contrato {self.numero} — {self.fornecedor_nome[:40]}"
    @property
    def esta_vigente(self):
        from datetime import date
        return (
            self.situacao == "Ativo"
            and self.vigencia_fim is not None
            and self.vigencia_fim >= date.today()
        )
class EmpenhoComprasnet(models.Model):
    """
    Empenho importado via API v1 autenticada do Comprasnet Contratos.
    Obtido por PDM (material) ou código de serviço por UASG e ano.
    Permite calcular o total empenhado por item de catálogo (CATMAT/CATSER)
    em um exercício, complementando o saldo das ARPs cujos dados não estão
    disponíveis no dadosabertos.compras.gov.br.
    """
    empenho_comprasnet_id = models.IntegerField(
        unique=True,
        help_text="ID interno do empenho na API Comprasnet Contratos",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="empenhos_comprasnet",
        help_text="Item da ARP ao qual este empenho foi vinculado (por código catmat/catser)",
    )
    contrato = models.ForeignKey(
        ContratoComprasnet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="empenhos",
        help_text="Contrato ao qual este empenho está vinculado (se identificado)",
    )
    numero = models.CharField(max_length=50, blank=True)
    tipo = models.CharField(max_length=50, blank=True)
    codigo_catmat = models.CharField(
        max_length=20,
        blank=True,
        help_text="Código CATMAT/CATSER do item empenhado",
    )
    descricao = models.TextField(blank=True)
    unidade = models.CharField(max_length=30, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    data_emissao = models.DateField(null=True, blank=True)
    ano = models.IntegerField(null=True, blank=True)
    uasg = models.CharField(max_length=10, blank=True)
    importado_em = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Empenho (Comprasnet)"
        verbose_name_plural = "Empenhos (Comprasnet)"
        ordering = ["-data_emissao"]
    def __str__(self):
        return f"Empenho {self.numero} — {self.descricao[:50]}"
class ContratoARP(models.Model):
    """
    Contrato firmado com base em ARP gerenciada pelo MPPI.
    Importado via API dadosabertos.compras.gov.br (/modulo-arp/3_consultarContratosARP).
    Cobre tanto contratações próprias (MPPI como contratante) quanto caronas cedidas
    (outro órgão aderiu à ARP do MPPI e firmou contrato diretamente com o fornecedor).
    """
    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.CASCADE,
        related_name="contratos_arp",
    )
    numero_contrato = models.CharField(
        max_length=100,
        help_text="Número do contrato (ex: 00005/2024)",
    )
    contratado_cnpj = models.CharField(max_length=20, blank=True)
    contratado_nome = models.CharField(max_length=255, blank=True)
    uasg_contratante = models.CharField(
        max_length=10,
        blank=True,
        help_text="UASG que firmou o contrato (pode diferir do gerenciador em caronas)",
    )
    nome_uasg_contratante = models.CharField(max_length=255, blank=True)
    data_assinatura = models.DateField(null=True, blank=True)
    data_inicio_vigencia = models.DateField(null=True, blank=True)
    data_fim_vigencia = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    numero_pncp = models.CharField(max_length=100, blank=True)
    is_carona = models.BooleanField(
        default=False,
        help_text="True quando o contratante é diferente do órgão gerenciador da ARP",
    )
    importado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato decorrente de ARP"
        verbose_name_plural = "Contratos decorrentes de ARP"
        ordering = ["-data_assinatura"]
        unique_together = ("arp", "numero_contrato", "uasg_contratante")

    def __str__(self):
        contratante = self.nome_uasg_contratante or self.uasg_contratante or "?"
        return f"Contrato {self.numero_contrato} — {contratante}"

    @property
    def esta_vigente(self):
        from datetime import date
        return self.data_fim_vigencia is not None and self.data_fim_vigencia >= date.today()


class ItemContratoARP(models.Model):
    """
    Linha de contrato vinculada a um ItemARP específico.
    Permite rastrear quais itens da ARP foram consumidos por qual contrato.
    """
    contrato = models.ForeignKey(
        ContratoARP,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="itens_contratos",
        help_text="Item da ARP ao qual este item de contrato corresponde",
    )
    numero_item = models.PositiveIntegerField()
    descricao = models.TextField(blank=True)
    unidade = models.CharField(max_length=30, blank=True)
    quantidade_contratada = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    valor_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "Item de contrato (ARP)"
        verbose_name_plural = "Itens de contrato (ARP)"
        ordering = ["numero_item"]
        unique_together = ("contrato", "numero_item")

    def __str__(self):
        return f"Item {self.numero_item} — {self.descricao[:50]}"


class ARPExterna(models.Model):
    """
    Carona RECEBIDA: ARP de outro órgão à qual o MPPI aderiu.
    Fundamento: Decreto 11.462/2023, art. 10.
    """
    STATUS = [
        ("ativa", "Ativa"),
        ("encerrada", "Encerrada"),
        ("cancelada", "Cancelada"),
    ]
    orgao_gerenciador_nome = models.CharField(
        max_length=255,
        help_text="Nome do órgão que originou a ARP",
    )
    orgao_gerenciador_cnpj = models.CharField(max_length=18)
    numero_arp_origem = models.CharField(
        max_length=30,
        help_text="Número da ARP no órgão gerenciador",
    )
    numero_pncp_origem = models.CharField(
        max_length=100,
        blank=True,
        help_text="Identificador PNCP da ARP de origem",
    )
    objeto = models.TextField()
    fornecedor_razao_social = models.CharField(max_length=255)
    fornecedor_cnpj_cpf = models.CharField(max_length=18)
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField()
    numero_sei_adesao = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo SEI/MPPI de adesão",
    )
    quantidade_autorizada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total_autorizado = models.DecimalField(max_digits=16, decimal_places=2)
    quantidade_utilizada = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0")
    )
    status = models.CharField(max_length=15, choices=STATUS, default="ativa")
    unidade_beneficiaria = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_externas",
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_externas_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ARP Externa (Carona Recebida)"
        verbose_name_plural = "ARPs Externas (Caronas Recebidas)"
        ordering = ["-data_inicio_vigencia"]

    def __str__(self):
        return f"ARP {self.numero_arp_origem} — {self.orgao_gerenciador_nome[:40]}"

    @property
    def saldo_remanescente(self):
        return self.quantidade_autorizada - self.quantidade_utilizada

    @property
    def valor_utilizado(self):
        return self.quantidade_utilizada * self.valor_unitario


# ---------------------------------------------------------------------------
# Vínculo ARP ↔ Unidade Requisitante
# ---------------------------------------------------------------------------

class VinculoARPUnidade(models.Model):
    """
    Associa uma ARP a uma ou mais Unidades Requisitantes,
    indicando o papel de cada unidade:

    - gestora   : unidade responsável pela gestão/controle da ARP
                  (autoriza empenhos, monitora saldo, responde pela ata)
    - demandante: unidade que usa a ARP mas não a gerencia
                  (faz pedidos, recebe material, não autoriza empenhos)

    Exemplos:
        ARP material de consumo → CAA (gestora)
        ARP manutenção predial  → CPPT (gestora)
        ARP combustível         → CAA (gestora), NUPS (demandante)
    """
    PAPEL = [
        ("gestora",    "Gestora — responsável pela ata"),
        ("demandante", "Demandante — usuária da ata"),
    ]

    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.CASCADE,
        related_name="vinculos_unidades",
    )
    unidade = models.ForeignKey(
        "core.UnidadeRequisitante",
        on_delete=models.CASCADE,
        related_name="vinculos_arp",
    )
    papel = models.CharField(max_length=15, choices=PAPEL, default="gestora")
    observacoes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vínculo ARP × Unidade"
        verbose_name_plural = "Vínculos ARP × Unidades"
        unique_together = ("arp", "unidade")
        ordering = ["papel", "unidade__sigla"]

    def __str__(self):
        return (
            f"ARP {self.arp.numero_arp} → {self.unidade.sigla} "
            f"({self.get_papel_display()})"
        )
