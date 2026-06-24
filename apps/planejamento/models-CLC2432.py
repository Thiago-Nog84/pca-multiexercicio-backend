from django.conf import settings
from django.db import models


class ETP(models.Model):
    """
    Estudo Técnico Preliminar — art. 18 NLLC + IN SEGES 58/2022.
    Aplicada ao MPPI por opção do Ato PGJ 1382/2024.
    Para TI: conteúdo ampliado pela Res. CNMP 283/2024 (arts. 10–16), incluindo TCO.
    Dispensado nas hipóteses do Decreto 21.872/2023, art. 27.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("em_revisao", "Em revisão"),
        ("aprovado", "Aprovado"),
    ]

    item_pca = models.OneToOneField(
        "pca.ItemPCA", on_delete=models.CASCADE, related_name="etp_origem", null=True, blank=True
    )
    numero_sei = models.CharField(max_length=30, blank=True, help_text="Número do processo SEI/MPPI")
    numero_etp = models.CharField(max_length=30)
    is_ti = models.BooleanField(default=False, help_text="Contratação de TIC — aplica Res. CNMP 283/2024")
    # Campos padrão IN SEGES 58/2022
    necessidade_contratacao = models.TextField()
    requisitos_contratacao = models.TextField()
    levantamento_mercado = models.TextField()
    descricao_solucao = models.TextField()
    estimativa_quantidade = models.TextField()
    estimativa_custo = models.DecimalField(max_digits=16, decimal_places=2, null=True)
    justificativa_parcelamento = models.TextField()
    contratacoes_correlatas = models.TextField(blank=True)
    alinhamento_pca = models.TextField(help_text="Vinculação com o PCA vigente")
    resultados_pretendidos = models.TextField()
    providencias_previas = models.TextField(blank=True)
    impactos_ambientais = models.TextField(help_text="Art. 11, I, NLLC — sustentabilidade")
    declaracao_viabilidade = models.BooleanField(default=False)
    # Campos adicionais para TI (Res. CNMP 283/2024, art. 10)
    tco_total = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True,
        help_text="TCO — Total Cost of Ownership (art. 10, Res. CNMP 283/2024)",
    )
    solucao_em_outros_orgaos = models.TextField(
        blank=True, help_text="Res. CNMP 283/2024, art. 10 — levantamento de mercado TI"
    )
    software_livre_avaliado = models.BooleanField(default=False)
    # IA e revisão
    gerado_por_ia = models.BooleanField(default=False)
    ia_modelo_utilizado = models.CharField(max_length=50, blank=True)
    ia_revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="etps_revisados"
    )
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    # Dispensa de ETP (Decreto 21.872/2023, art. 27)
    etp_dispensado = models.BooleanField(default=False)
    fundamento_dispensa_etp = models.CharField(
        max_length=200, blank=True, help_text="Ex: art. 75, I, Lei 14.133/2021 — abaixo do limite"
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.numero_etp or f"ETP #{self.pk}"


class EquipePlanejamentoTI(models.Model):
    """
    Equipe de Planejamento para contratações de TIC.
    Res. CNMP 283/2024, art. 9º — tripartite: Requisitante + Técnico + Administrativo.
    """

    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="equipe_planejamento_ti")
    integrante_requisitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_requisitante"
    )
    integrante_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_tecnico"
    )
    integrante_administrativo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_administrativo"
    )
    lider = models.CharField(
        max_length=20,
        choices=[("requisitante", "Requisitante"), ("tecnico", "Técnico"), ("administrativo", "Administrativo")],
        default="requisitante",
        help_text="Preferencialmente o Requisitante — art. 9º Res. CNMP 283/2024",
    )
    ato_designacao_sei = models.CharField(max_length=30, blank=True)


class MatrizRisco(models.Model):
    """
    Mapa e Matriz de Riscos.
    Decreto 21.872/2023, arts. 29–34; art. 8º, IV, Ato PGJ 1381/2024.
    Matriz obrigatória para contratos acima de 2% do limite do art. 6º, XXII, NLLC.
    Metodologia 5×5 (probabilidade × impacto).
    Para TI: Res. CNMP 283/2024, art. 45.
    """

    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="matriz_risco")
    # Res. CNMP 283/2024, art. 45: mapa deve cobrir todas as três fases
    fase_atual = models.CharField(
        max_length=20,
        choices=[("planejamento", "Planejamento"), ("selecao", "Seleção"), ("gestao", "Gestão")],
        default="planejamento",
    )


class RiscoItem(models.Model):
    PROBABILIDADE = [(1, "Muito baixa"), (2, "Baixa"), (3, "Média"), (4, "Alta"), (5, "Muito alta")]
    IMPACTO = [(1, "Muito baixo"), (2, "Baixo"), (3, "Médio"), (4, "Alto"), (5, "Muito alto")]
    RESPONSAVEL = [("adm", "Administração"), ("contratado", "Contratado"), ("compartilhado", "Compartilhado")]

    matriz = models.ForeignKey(MatrizRisco, on_delete=models.CASCADE, related_name="itens")
    descricao_risco = models.TextField()
    causa = models.TextField()
    consequencia = models.TextField()
    probabilidade = models.PositiveSmallIntegerField(choices=PROBABILIDADE)
    impacto = models.PositiveSmallIntegerField(choices=IMPACTO)
    nivel_risco = models.PositiveSmallIntegerField(editable=False)
    responsavel = models.CharField(max_length=20, choices=RESPONSAVEL)
    acao_preventiva = models.TextField()
    acao_contingencia = models.TextField()

    def save(self, *args, **kwargs):
        self.nivel_risco = self.probabilidade * self.impacto
        super().save(*args, **kwargs)


class TermoReferencia(models.Model):
    """
    Termo de Referência.
    Art. 8º, III, Ato PGJ 1381/2024 + art. 6º, XXIII, NLLC + IN SEGES 81/2022.
    Aplicada ao MPPI por opção do Ato PGJ 1382/2024.
    Para TI: conteúdo ampliado pela Res. CNMP 283/2024 (arts. 17–20).
    Modelo base: AGU (adotado pelo Ato PGJ 1413/2024, §2º).
    Vedações TI: art. 19 Res. CNMP 283/2024 registradas no campo 'vedacoes_ti'.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("em_revisao", "Em revisão"),
        ("appl", "Aguardando análise APPL"),
        ("aprovado", "Aprovado"),
        ("publicado", "Publicado"),
    ]

    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="termo_referencia")
    numero_sei = models.CharField(max_length=30, blank=True)
    objeto = models.TextField()
    fundamentacao_legal = models.TextField(help_text="Inclui referência ao ETP e normativos aplicáveis ao MPPI")
    descricao_solucao = models.TextField()
    requisitos_habilitacao = models.TextField()
    criterio_julgamento = models.CharField(
        max_length=30,
        choices=[
            ("menor_preco", "Menor Preço"),
            ("maior_desconto", "Maior Desconto"),
            ("melhor_tecnica", "Melhor Técnica e Preço"),
            ("maior_retorno", "Maior Retorno Econômico"),
        ],
    )
    prazo_execucao = models.PositiveIntegerField(help_text="Em dias")
    local_execucao = models.TextField()
    obrigacoes_contratante = models.TextField()
    obrigacoes_contratado = models.TextField()
    criterios_medicao = models.TextField()
    # Serviços contínuos — Ato PGJ 1415/2024
    is_servico_continuo = models.BooleanField(default=False)
    prazo_inicial_meses = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Mín. 24 meses para serviços contínuos — art. 5º Ato 1415/2024"
    )
    prazo_maximo_meses = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Máx. 120 meses (prazo decenal)"
    )
    # SRP
    is_srp = models.BooleanField(default=False)
    justificativa_srp = models.TextField(blank=True)
    # TI — Res. CNMP 283/2024
    modalidade_remuneracao_ti = models.CharField(
        max_length=30,
        blank=True,
        choices=[
            ("pontos_funcao", "Pontos de função + horas"),
            ("sprint", "Valor fixo por sprint"),
            ("alocacao", "Alocação vinculada a resultados"),
            ("fixo_mensal", "Valor fixo mensal por sistema"),
            ("fixo_alocacao", "Fixo por alocação com resultados"),
        ],
    )
    vedacoes_ti_observadas = models.BooleanField(
        default=False, help_text="Confirmação de que as vedações do art. 19 Res. CNMP 283/2024 foram observadas"
    )
    # IA e modelo
    gerado_por_ia = models.BooleanField(default=False)
    modelo_agu_base = models.CharField(
        max_length=100, blank=True, help_text="Modelo AGU utilizado como base (Ato PGJ 1413/2024)"
    )
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.objeto[:60]
