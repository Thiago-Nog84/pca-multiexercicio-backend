from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver


# Tradução do código de unidade orçamentária do ItemPCA (apps.pca) para o
# código usado aqui no DOD. São os MESMOS três fundos, gravados com códigos
# diferentes por um acidente histórico já registrado nos comentários de
# `UNIDADE_ORCAMENTARIA` abaixo: o DOD nasceu com "fmmpi"/"fpdc" e o resto do
# sistema (ItemPCA, contratos, srp) usa "fmmp"/"fepdc", com ~1.100 ItemPCA já
# gravados. Enquanto essa padronização cross-app não acontece, toda travessia
# entre os dois vocabulários passa por aqui — não espalhar o de/para pelo
# código.
UO_ITEM_PARA_DOD = {
    "pgj": "pgj",
    "fmmp": "fmmpi",
    "fepdc": "fpdc",
}


def unidade_orcamentaria_dos_itens(itens):
    """
    Deriva a unidade orçamentária do DOD a partir dos ItemPCA que o compõem.

    A UO não é digitada no DOD: ela já está cadastrada em cada demanda
    (`ItemPCA.unidade_orcamentaria`, vinda do DFD de origem). Decidido com
    Thiago em 2026-08-18 — o campo da seção 3 do modelo SEI passa a ser
    derivado, e um DOD não pode misturar fontes de recurso (o documento tem
    UM campo de UO, logo UM processo = UMA fonte).

    Devolve `(codigo, codigos_encontrados)`:
      - `codigo`: código no vocabulário do DOD quando todos os itens
        concordam; string vazia se não houver itens OU se houver mistura
        (nesse caso quem chama decide como reclamar).
      - `codigos_encontrados`: lista ordenada de todos os códigos achados —
        `len() > 1` é exatamente o caso de mistura.
    """
    codigos = sorted(
        {UO_ITEM_PARA_DOD.get(i.unidade_orcamentaria, "") for i in itens} - {""}
    )
    return (codigos[0] if len(codigos) == 1 else ""), codigos


class DocumentoOficializacaoDemanda(models.Model):
    """
    DOD — Documento de Oficialização da Demanda.

    Formaliza a ABERTURA do processo de contratação para um ou mais itens
    JÁ APROVADOS no PCA vigente — nome escolhido por Thiago em 2026-08-17
    para não confundir com `pca.DocumentoFormalizacaoDemanda` (o "DFD" que
    já existe no sistema, usado na CONSTRUÇÃO do PCA, antes da aprovação).

    Modelo de referência: SEI MPPI 1465317 ("Documento de Formalização da
    Demanda — DFD", modelo institucional v2.0/02-02-2026, anexado por
    Thiago). Apesar do nome oficial no SEI ser "DFD", o conteúdo e o
    momento em que é preenchido — depois do PCA aprovado, autorizando abrir
    a licitação/contratação direta (ver seção 11 do modelo: "as demandas
    constantes neste DFD já foram aprovadas previamente no PCA vigente,
    ficando autorizada a abertura dos respectivos processos...") —
    correspondem ao DOD deste sistema, não ao DFD de construção do PCA.

    Substitui o `LoteContratacao` criado em 2026-08-17 (mesma sessão, antes
    de Thiago anexar o modelo real) — que fazia só o agrupamento de itens.
    Este model absorve esse papel (M2M `itens`) e acrescenta os campos do
    documento oficial.

    Escopo desta rodada (2026-08-17): campos das seções 1-4, 8-11 do
    modelo. DELIBERADAMENTE FORA por ora (ver conversa com Thiago):
      - Seção 5 (Fiscalização proposta do objeto — nome/matrícula/email/
        perfil/ramal): sem model ainda.
      - Seção 7 (Unidade beneficiária da demanda, quando atende unidade
        diferente da requisitante): sem model ainda.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("aberto", "Processo aberto"),
        ("cancelado", "Cancelado"),
    ]

    # Choices conforme o modelo SEI 1465317, seção 3. Thiago confirmou em
    # 2026-08-17 o nome oficial do 3º fundo: "FUNDO ESTADUAL DE PROTEÇÃO E
    # DEFESA DO CONSUMIDOR — FPDC". Uso "fpdc" aqui (código novo, sem dado
    # legado). NÃO renomeei o código já existente noutros lugares do sistema
    # (ItemPCA.UNIDADE_ORCAMENTARIA usa "fepdc"; apps/contratos e apps/srp
    # também usam "fepdc" em vários management commands, com ~220 ItemPCA +
    # registros de Contrato/ContratacaoDecorrente já gravados com esse
    # código) — é uma limpeza maior, cross-app, que decidi não fazer de
    # carona nesta conversa do DOD. Fica registrada a inconsistência
    # temporária: DOD usa "fpdc", o resto do sistema usa "fepdc" para o
    # mesmo fundo, até uma rodada dedicada de padronização.
    UNIDADE_ORCAMENTARIA = [
        ("pgj", "PGJ — Procuradoria-Geral de Justiça"),
        ("fmmpi", "FMMPI — Fundo de Modernização do MPPI"),
        ("fpdc", "FPDC — Fundo Estadual de Proteção e Defesa do Consumidor"),
    ]

    # Reestruturado em 2026-08-18 a pedido de Thiago. Antes eram 7 opções
    # planas (o texto literal do formulário SEI), que misturavam três eixos
    # independentes num campo só e criavam combinações impossíveis de
    # registrar — "fornecimento continuado de solução de TIC", por exemplo,
    # não tinha como ser marcado. Agora: a natureza é UMA de três, e o que
    # antes era sufixo do rótulo virou marcador booleano.
    #
    # As 7 opções antigas viram estas combinações:
    #   servicos_nao_continuados      -> servicos                     (nada marcado)
    #   servicos_continuados_sem_demo -> servicos      + item_continuado
    #   servicos_continuados_com_demo -> servicos      + item_continuado + com_demo
    #   fornecimento_nao_continuado   -> fornecimento                 (nada marcado)
    #   fornecimento_continuado       -> fornecimento  + item_continuado
    #   obras_servicos_engenharia     -> obra_engenharia
    #   solucao_ti                    -> (natureza que couber) + solucao_tic
    # Não houve migração de dados porque a tabela estava vazia (0 DODs).
    NATUREZA_SERVICOS = "servicos"

    NATUREZA_OBJETO = [
        (NATUREZA_SERVICOS, "Serviços"),
        ("fornecimento", "Fornecimentos"),
        ("obra_engenharia", "Obras e serviços de engenharia"),
    ]

    GRAU_PRIORIDADE = [("baixo", "Baixo"), ("medio", "Médio"), ("alto", "Alto")]

    # --- Identificação (cabeçalho + seção 1) ---------------------------
    pca = models.ForeignKey(
        "pca.PlanoContratacaoAnual", on_delete=models.CASCADE, related_name="documentos_oficializacao"
    )
    identificador = models.CharField(
        max_length=60,
        help_text="Rótulo interno do agrupamento, ex: 'Lote 1 — Material de expediente'.",
    )
    numero_sei = models.CharField(max_length=30, blank=True, help_text="Processo SEI Nº")
    objeto = models.TextField(blank=True)
    itens = models.ManyToManyField("pca.ItemPCA", related_name="documentos_oficializacao")
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")

    # --- Informações gerais da contratação (seção 3) -------------------
    unidade_orcamentaria = models.CharField(max_length=10, choices=UNIDADE_ORCAMENTARIA, blank=True)
    natureza_objeto = models.CharField(max_length=30, choices=NATUREZA_OBJETO, blank=True)
    # Marcadores independentes da natureza (ver comentário em NATUREZA_OBJETO).
    solucao_tic = models.BooleanField(
        default=False,
        verbose_name="Solução de TIC",
        help_text="Contratação de solução de Tecnologia da Informação e Comunicação "
                  "(Res. CNMP 283/2024) — exige equipe de planejamento com os 3 papéis.",
    )
    item_continuado = models.BooleanField(
        default=False,
        verbose_name="Item continuado",
        help_text="Serviço ou fornecimento contínuo, nos termos do Ato PGJ 1415/2024.",
    )
    com_demo = models.BooleanField(
        default=False,
        verbose_name="Com dedicação de mão de obra (DEMO)",
        help_text="Só se aplica a serviços.",
    )
    contratacao_correlata = models.BooleanField(
        default=False, help_text="Há necessidade de contratação correlata (providências prévias)?"
    )
    contratacao_correlata_qual = models.TextField(blank=True, help_text="Se sim, qual?")
    grau_prioridade = models.CharField(max_length=10, choices=GRAU_PRIORIDADE, blank=True)
    previsao_inicio_execucao = models.DateField(null=True, blank=True)
    previsao_termino_execucao = models.DateField(null=True, blank=True)

    # --- Alinhamento aos planos estratégicos (seção 8) -----------------
    # "Quais itens do PCA vigente" já é coberto pelo M2M `itens` acima.
    objetivos_estrategicos = models.TextField(
        blank=True, help_text="Objetivos estratégicos, conforme redação do PCA vigente."
    )
    alinhamento_pdtic = models.TextField(
        blank=True, help_text="Ex.: 'Ação 3 — Meta 5'. Texto livre por ora (sem sub-tabela dedicada)."
    )

    # --- Fundamentação (seção 9) e resultados esperados (seção 10) -----
    necessidade_contratacao = models.TextField(blank=True, help_text="Qual a necessidade da contratação?")
    motivacao_justificativa = models.TextField(
        blank=True, help_text="Por que fazer a contratação (motivação/justificativa)?"
    )
    objetivo_contratacao = models.TextField(blank=True, help_text="Qual o objetivo da contratação?")
    meta_contratacao = models.TextField(blank=True, help_text="Qual a meta a ser alcançada com a contratação?")
    indicador_resultado = models.TextField(blank=True, help_text="Qual o indicador (resultado alcançado)?")

    # --- Responsável pelo preenchimento (seção 11) ----------------------
    responsavel_preenchimento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dods_preenchidos",
    )

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Documento de Oficialização da Demanda (DOD)"
        verbose_name_plural = "Documentos de Oficialização da Demanda (DOD)"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.identificador or f"DOD #{self.pk}"

    def clean(self):
        super().clean()
        # DEMO (dedicação exclusiva de mão de obra) é um regime de execução
        # de SERVIÇO — não existe fornecimento nem obra "com DEMO". A tela já
        # desabilita a caixa fora de Serviços; isto garante a regra também em
        # POST forjado, script e admin.
        if self.com_demo and self.natureza_objeto != self.NATUREZA_SERVICOS:
            raise ValidationError({
                "com_demo": "Dedicação de mão de obra (DEMO) só se aplica a serviços.",
            })

    @property
    def exige_equipe_ti(self):
        """
        Se este DOD exige equipe de planejamento com os 3 papéis distintos
        (Res. CNMP 283/2024). Até 2026-08-18 isso era `natureza_objeto ==
        "solucao_ti"`; agora é o marcador próprio, que pode conviver com
        qualquer natureza. Ponto único da regra — `EquipePlanejamentoTI.clean()`,
        as views e o admin consultam esta propriedade.
        """
        return self.solucao_tic

    @property
    def valor_total_estimado(self):
        from django.db.models import Sum
        return self.itens.aggregate(total=Sum("valor_total_estimado"))["total"] or 0


@receiver(m2m_changed, sender=DocumentoOficializacaoDemanda.itens.through)
def validar_itens_dod(sender, instance, action, pk_set, reverse, **kwargs):
    """
    Decidido com Thiago em 2026-08-17, regras de negócio sobre
    `DocumentoOficializacaoDemanda.itens`:

    1. Só ItemPCA já aprovado no PCA (status_aprovacao aprovada_integral ou
       aprovada_parcial) pode entrar num DOD — o próprio texto legal do
       modelo SEI 1465317 diz que as demandas do DOD "já foram aprovadas
       previamente no PCA vigente".
    2. Um ItemPCA não pode estar em mais de um DOD com status "aberto" ao
       mesmo tempo — evita o mesmo item entrar em dois processos.
    3. O item precisa pertencer ao MESMO PlanoContratacaoAnual do DOD (via
       item.dfd.pca) — achado ao montar a tela de criação: sem essa trava,
       nada impedia um DOD do PCA 2027 incluir item do PCA 2026.

    Via signal (não só no admin) para valer também nas telas que ainda vamos
    construir e em qualquer script/command futuro que mexa nesse M2M. Só
    valida o sentido "direto" (dod.itens.add(...)); o sentido reverso
    (item.documentos_oficializacao.add(...)) não é usado hoje em nenhum
    lugar do sistema, então não foi implementado.
    """
    if action != "pre_add" or not pk_set or reverse:
        return

    from apps.pca.models import ItemPCA

    itens = ItemPCA.objects.filter(pk__in=pk_set)

    nao_aprovados = itens.exclude(status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
    if nao_aprovados.exists():
        nomes = ", ".join(i.codigo_pca or f"#{i.pk}" for i in nao_aprovados)
        raise ValidationError(
            f"Item(ns) ainda não aprovado(s) no PCA não podem entrar num DOD: {nomes}."
        )

    conflitantes = (
        itens.filter(documentos_oficializacao__status="aberto")
        .exclude(documentos_oficializacao=instance)
        .distinct()
    )
    if conflitantes.exists():
        nomes = ", ".join(i.codigo_pca or f"#{i.pk}" for i in conflitantes)
        raise ValidationError(
            f"Item(ns) já vinculado(s) a outro DOD aberto: {nomes}."
        )

    fora_do_pca = itens.exclude(dfd__pca=instance.pca_id)
    if fora_do_pca.exists():
        nomes = ", ".join(i.codigo_pca or f"#{i.pk}" for i in fora_do_pca)
        raise ValidationError(
            f"Item(ns) de outro PCA não podem entrar neste DOD ({instance.pca}): {nomes}."
        )


class ETP(models.Model):
    """
    Estudo Técnico Preliminar — art. 18 NLLC + IN SEGES 58/2022.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("em_revisao", "Em revisão"),
        ("aprovado", "Aprovado"),
    ]

    dod = models.OneToOneField(
        DocumentoOficializacaoDemanda, on_delete=models.CASCADE, related_name="etp"
    )
    numero_sei = models.CharField(max_length=30, blank=True)
    numero_etp = models.CharField(max_length=30)
    is_ti = models.BooleanField(default=False)
    necessidade_contratacao = models.TextField()
    requisitos_contratacao = models.TextField()
    levantamento_mercado = models.TextField()
    descricao_solucao = models.TextField()
    estimativa_quantidade = models.TextField()
    estimativa_custo = models.DecimalField(max_digits=16, decimal_places=2, null=True)
    justificativa_parcelamento = models.TextField()
    contratacoes_correlatas = models.TextField(blank=True)
    alinhamento_pca = models.TextField()
    resultados_pretendidos = models.TextField()
    providencias_previas = models.TextField(blank=True)
    impactos_ambientais = models.TextField()
    declaracao_viabilidade = models.BooleanField(default=False)
    tco_total = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    solucao_em_outros_orgaos = models.TextField(blank=True)
    software_livre_avaliado = models.BooleanField(default=False)
    gerado_por_ia = models.BooleanField(default=False)
    ia_modelo_utilizado = models.CharField(max_length=50, blank=True)
    ia_revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="etps_revisados"
    )
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    etp_dispensado = models.BooleanField(default=False)
    fundamento_dispensa_etp = models.CharField(max_length=200, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.numero_etp or f"ETP #{self.pk}"


class EquipePlanejamentoTI(models.Model):
    """
    Equipe de planejamento da contratação (seção 4 do modelo SEI 1465317).

    Movida de ETP para DOD em 2026-08-17: no documento real a equipe é
    designada na ABERTURA do processo, antes do ETP existir — não faz
    sentido esperar o ETP para registrar quem está na equipe.

    Regra implementada em 2026-08-17 (Thiago): os 3 papéis distintos
    (Requisitante/Técnico/Administrativo) só são OBRIGATÓRIOS quando o DOD é
    de contratação de Solução de TIC — exigência da Res. CNMP 283/2024.
    Nos demais casos o campo `integrante_administrativo` fica opcional e não
    há checagem de distinção entre os integrantes — ver `clean()`.

    Desde 2026-08-18 quem responde "é de TIC?" é `dod.exige_equipe_ti`
    (marcador `dod.solucao_tic`), e não mais `natureza_objeto == "solucao_ti"`:
    TIC deixou de ser uma das naturezas e virou marcador, justamente para
    poder conviver com serviço, fornecimento ou obra.

    Nota (ainda não resolvida): o modelo SEI 1465317 mostra, para qualquer
    natureza, uma tabela repetível com só 2 papéis (Integrante Requisitante
    / Integrante Técnico), permitindo várias pessoas no mesmo papel. Este
    model continua com 3 campos fixos (1 pessoa por papel) — não é uma
    tabela repetível. Suficiente para TI (onde é sempre 1 pessoa por papel),
    mas não representa fielmente o caso geral com múltiplos integrantes do
    mesmo papel; fica para quando for pedido generalizar.
    """

    dod = models.OneToOneField(
        DocumentoOficializacaoDemanda, on_delete=models.CASCADE, related_name="equipe_planejamento_ti"
    )
    integrante_requisitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ep_requisitante"
    )
    integrante_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ep_tecnico"
    )
    integrante_administrativo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ep_administrativo"
    )
    lider = models.CharField(
        max_length=20,
        choices=[("requisitante", "Requisitante"), ("tecnico", "Técnico"), ("administrativo", "Administrativo")],
        default="requisitante",
    )
    ato_designacao_sei = models.CharField(max_length=30, blank=True)

    def clean(self):
        super().clean()
        if not self.dod_id:
            return

        if not self.dod.exige_equipe_ti:
            # Fora de TIC, os 3 papéis fixos não são exigidos pela Res. CNMP
            # 283/2024 — nenhuma validação adicional aqui.
            return

        faltando = [
            nome
            for nome, valor in [
                ("Integrante Requisitante", self.integrante_requisitante_id),
                ("Integrante Técnico", self.integrante_tecnico_id),
                ("Integrante Administrativo", self.integrante_administrativo_id),
            ]
            if not valor
        ]
        if faltando:
            raise ValidationError(
                "Contratação de Solução de TI (Res. CNMP 283/2024) exige os 3 papéis "
                f"preenchidos — faltando: {', '.join(faltando)}."
            )

        integrantes = {
            self.integrante_requisitante_id,
            self.integrante_tecnico_id,
            self.integrante_administrativo_id,
        }
        if len(integrantes) < 3:
            raise ValidationError(
                "Contratação de Solução de TI exige 3 pessoas DISTINTAS nos papéis "
                "requisitante/técnico/administrativo — a mesma pessoa não pode ocupar "
                "mais de um papel."
            )


class MatrizRisco(models.Model):
    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="matriz_risco")
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
    fundamentacao_legal = models.TextField()
    descricao_solucao = models.TextField()
    requisitos_habilitacao = models.TextField()
    criterio_julgamento = models.CharField(max_length=30, choices=[
        ("menor_preco", "Menor Preço"), ("maior_desconto", "Maior Desconto"),
        ("melhor_tecnica", "Melhor Técnica e Preço"), ("maior_retorno", "Maior Retorno Econômico"),
    ])
    prazo_execucao = models.PositiveIntegerField()
    local_execucao = models.TextField()
    obrigacoes_contratante = models.TextField()
    obrigacoes_contratado = models.TextField()
    criterios_medicao = models.TextField()
    is_servico_continuo = models.BooleanField(default=False)
    prazo_inicial_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    prazo_maximo_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    is_srp = models.BooleanField(default=False)
    justificativa_srp = models.TextField(blank=True)
    modalidade_remuneracao_ti = models.CharField(max_length=30, blank=True, choices=[
        ("pontos_funcao", "Pontos de função + horas"), ("sprint", "Valor fixo por sprint"),
        ("alocacao", "Alocação vinculada a resultados"), ("fixo_mensal", "Valor fixo mensal por sistema"),
        ("fixo_alocacao", "Fixo por alocação com resultados"),
    ])
    vedacoes_ti_observadas = models.BooleanField(default=False)
    gerado_por_ia = models.BooleanField(default=False)
    modelo_agu_base = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.objeto[:60]
