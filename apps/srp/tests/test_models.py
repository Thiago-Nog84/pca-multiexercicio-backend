"""
Testes unitários do módulo SRP — Sistema de Registro de Preços.

Cobre as regras de negócio críticas:
  1. Débito automático de saldo em ContratacaoDecorrente.save()
  2. Limite de 50% por item por aderente em AdesaoARP.clean()
  3. Bloqueio de carona sem SEI quando maximo_adesao_api == 0
  4. VinculoPCAItemARP: ARP encerrada / excesso de quantidade / lote incompatível
  5. Propriedades de valor R$ em ItemARP
  6. Preenchimento automático de exercicio em ContratacaoDecorrente.save()
  7. Validação de numero_lote em ItemARP quando usa_lotes=True

Base legal testada:
  - Decreto 11.462/2023, art. 9º (limite carona 50%)
  - Decreto 11.462/2023, art. 4º, §2º (vigência da ARP)
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import Orgao, UnidadeRequisitante
from apps.pca.models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual
from apps.srp.models import (
    AdesaoARP,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ItemARP,
    VinculoPCAItemARP,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

def make_orgao(cnpj="05.805.924/0001-89", sigla="MPPI"):
    return Orgao.objects.create(
        nome="Ministério Público do Estado do Piauí",
        sigla=sigla,
        cnpj=cnpj,
    )


def make_unidade(orgao, sigla="CLC"):
    return UnidadeRequisitante.objects.create(
        orgao=orgao,
        sigla=sigla,
        nome="Coordenadoria de Licitações e Contratos",
    )


def make_arp(orgao, numero_arp="001/2026", status="vigente", dias_fim=335, usa_lotes=False):
    hoje = date.today()
    return AtaRegistroPrecos.objects.create(
        orgao_gerenciador=orgao,
        numero_arp=numero_arp,
        objeto="Material de escritório",
        modalidade_origem="pregao_eletronico",
        fornecedor_razao_social="Fornecedor Teste LTDA",
        fornecedor_cnpj_cpf="12.345.678/0001-90",
        data_assinatura=hoje - timedelta(days=30),
        data_inicio_vigencia=hoje - timedelta(days=30),
        data_fim_vigencia=hoje + timedelta(days=dias_fim),
        status=status,
        usa_lotes=usa_lotes,
    )


def make_item_arp(arp, numero_item=1, qtd=Decimal("100"), preco=Decimal("20.00"),
                  numero_lote="", maximo_adesao_api=None):
    return ItemARP.objects.create(
        arp=arp,
        numero_item=numero_item,
        numero_lote=numero_lote,
        descricao="Papel A4 500 folhas",
        unidade_fornecimento="Resma",
        quantidade_registrada=qtd,
        valor_unitario=preco,
        maximo_adesao_api=maximo_adesao_api,
    )


_item_pca_counter = 0


def make_item_pca(orgao):
    """Cria a cadeia mínima: Orgao → PCA → DFD → ItemPCA (com contador para unicidade)."""
    global _item_pca_counter
    _item_pca_counter += 1

    unidade = UnidadeRequisitante.objects.get_or_create(
        orgao=orgao, sigla="CTI",
        defaults={"nome": "Coordenadoria de TI"},
    )[0]
    pca = PlanoContratacaoAnual.objects.get_or_create(
        orgao=orgao,
        exercicio=2027,
    )[0]
    dfd = DocumentoFormalizacaoDemanda.objects.create(
        pca=pca,
        unidade=unidade,
        descricao_objeto=f"Aquisição de material #{_item_pca_counter}",
        justificativa="Reposição de estoque",
        prazo_necessidade=date.today() + timedelta(days=60),
    )
    return ItemPCA.objects.create(
        dfd=dfd,
        numero_item=_item_pca_counter,
        categoria="material",
        descricao="Papel A4",
        unidade_fornecimento="Resma",
        quantidade_estimada=Decimal("50"),
        valor_unitario_estimado=Decimal("20.00"),
        valor_total_estimado=Decimal("1000.00"),
        tipo_demanda="nova",
        modalidade="arp_propria",
        is_srp=True,
    )


# ---------------------------------------------------------------------------
# 1. Saldo denormalizado — ContratacaoDecorrente.save()
# ---------------------------------------------------------------------------

class ContratacaoDebitaSaldoTest(TestCase):
    """Decreto 11.462/2023, art. 7º — pedido de fornecimento debita saldo da ARP."""

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        self.item = make_item_arp(self.arp, qtd=Decimal("100"))

    def test_criacao_debita_quantidade_contratada(self):
        """Nova ContratacaoDecorrente deve incrementar quantidade_contratada no ItemARP."""
        ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("30"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("600.00"),
            data_emissao=date.today(),
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_contratada, Decimal("30"))

    def test_multiplas_contratacoes_acumulam(self):
        """Duas contratações devem acumular o débito corretamente."""
        for qtd in [Decimal("20"), Decimal("35")]:
            ContratacaoDecorrente.objects.create(
                arp=self.arp,
                item_arp=self.item,
                numero_pedido=f"PF-{qtd}/2026",
                quantidade=qtd,
                valor_unitario=Decimal("20.00"),
                valor_total=qtd * Decimal("20.00"),
                data_emissao=date.today(),
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_contratada, Decimal("55"))

    def test_edicao_nao_debita_novamente(self):
        """Editar uma contratação existente (pk já existe) não deve duplicar o débito."""
        ct = ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("30"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("600.00"),
            data_emissao=date.today(),
        )
        ct.observacoes = "Atualizado"
        ct.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_contratada, Decimal("30"))  # não duplicou


# ---------------------------------------------------------------------------
# 2. Exercício automático — ContratacaoDecorrente.save()
# ---------------------------------------------------------------------------

class ContratacaoExercicioAutoTest(TestCase):
    """Exercício é preenchido automaticamente a partir da data_emissao quando omitido."""

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        self.item = make_item_arp(self.arp)

    def _cria_contratacao(self, data_emissao, exercicio=None):
        kwargs = dict(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido=f"PF-{data_emissao}/2026",
            quantidade=Decimal("5"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("100.00"),
            data_emissao=data_emissao,
        )
        if exercicio is not None:
            kwargs["exercicio"] = exercicio
        return ContratacaoDecorrente.objects.create(**kwargs)

    def test_exercicio_preenchido_automaticamente(self):
        """Sem exercicio informado, deve usar data_emissao.year."""
        ct = self._cria_contratacao(date(2026, 6, 15))
        self.assertEqual(ct.exercicio, 2026)

    def test_exercicio_manual_preservado(self):
        """Exercicio informado manualmente não deve ser sobrescrito."""
        ct = self._cria_contratacao(date(2026, 6, 15), exercicio=2025)
        self.assertEqual(ct.exercicio, 2025)

    def test_exercicio_virada_ano(self):
        """Contratação em dezembro usa o ano correto."""
        ct = self._cria_contratacao(date(2026, 12, 31))
        self.assertEqual(ct.exercicio, 2026)

    def test_numero_contrato_str(self):
        """__str__ exibe numero_contrato quando disponível."""
        ct = self._cria_contratacao(date(2026, 6, 15))
        ct.numero_contrato = "123/2026"
        ct.save()
        self.assertIn("123/2026", str(ct))


# ---------------------------------------------------------------------------
# 3. Limite de carona 50% — AdesaoARP.clean()
# ---------------------------------------------------------------------------

class LimiteCaronaTest(TestCase):
    """Decreto 11.462/2023, art. 9º — 50% por item por órgão aderente."""

    CNPJ_ADERENTE = "98.765.432/0001-10"

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        # 100 unidades registradas → limite por aderente = 50
        self.item = make_item_arp(self.arp, qtd=Decimal("100"))

    def _adesao(self, qtd, status="autorizada", cnpj=None):
        """Cria uma AdesaoARP sem chamar clean() (via update direto após criação básica)."""
        obj = AdesaoARP(
            arp=self.arp,
            item_arp=self.item,
            orgao_aderente_nome="Órgão Aderente Teste",
            orgao_aderente_cnpj=cnpj or self.CNPJ_ADERENTE,
            quantidade_solicitada=qtd,
            valor_unitario=Decimal("20.00"),
            valor_total=qtd * Decimal("20.00"),
            data_solicitacao=date.today(),
            status=status,
        )
        return obj

    def test_adesao_dentro_do_limite_aceita(self):
        """50 unidades = exatamente no limite → deve ser aceito."""
        adesao = self._adesao(Decimal("50"))
        try:
            adesao.clean()
        except ValidationError:
            self.fail("clean() rejeitou adesão dentro do limite de 50%")

    def test_adesao_acima_do_limite_rejeitada(self):
        """51 unidades > 50% → deve lançar ValidationError."""
        adesao = self._adesao(Decimal("51"))
        with self.assertRaises(ValidationError) as ctx:
            adesao.clean()
        self.assertIn("50%", str(ctx.exception))

    def test_acumulo_com_adesoes_anteriores_rejeitado(self):
        """
        30 + 25 = 55 > 50% → a segunda adesão deve ser rejeitada.
        A primeira adesão é salva via SQL direto para não disparar clean() novamente.
        """
        # Salva a primeira adesão sem clean() para simular estado pré-existente
        AdesaoARP.objects.create(
            arp=self.arp,
            item_arp=self.item,
            orgao_aderente_nome="Órgão Aderente Teste",
            orgao_aderente_cnpj=self.CNPJ_ADERENTE,
            quantidade_solicitada=Decimal("30"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("600.00"),
            data_solicitacao=date.today(),
            status="autorizada",
            numero_sei_autorizacao="",  # força bypass do clean() (sem maximo=0)
        )
        # Segunda adesão do mesmo aderente: 30 já autorizados + 25 = 55 > 50
        segunda = self._adesao(Decimal("25"))
        with self.assertRaises(ValidationError):
            segunda.clean()

    def test_aderentes_diferentes_nao_interferem(self):
        """
        Aderente A usa 50% → não impede aderente B de solicitar até 50%.
        """
        # Salva 50 unidades para aderente A
        AdesaoARP.objects.create(
            arp=self.arp,
            item_arp=self.item,
            orgao_aderente_nome="Aderente A",
            orgao_aderente_cnpj="11.111.111/0001-11",
            quantidade_solicitada=Decimal("50"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("1000.00"),
            data_solicitacao=date.today(),
            status="autorizada",
        )
        # Aderente B solicita 50 — deve passar
        adesao_b = self._adesao(Decimal("50"), cnpj="22.222.222/0001-22")
        try:
            adesao_b.clean()
        except ValidationError:
            self.fail("clean() aplicou o limite de aderente A sobre aderente B")


# ---------------------------------------------------------------------------
# 4. Carona bloqueada sem SEI — AdesaoARP.clean()
# ---------------------------------------------------------------------------

class CaronaBloqueadaSemSeiTest(TestCase):
    """Quando maximo_adesao_api == 0, exige numero_sei_autorizacao."""

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        # maximo_adesao_api = 0 → carona bloqueada no Compras.gov
        self.item = make_item_arp(self.arp, qtd=Decimal("100"), maximo_adesao_api=Decimal("0"))

    def _adesao(self, sei=""):
        return AdesaoARP(
            arp=self.arp,
            item_arp=self.item,
            orgao_aderente_nome="Aderente Teste",
            orgao_aderente_cnpj="33.333.333/0001-33",
            quantidade_solicitada=Decimal("10"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("200.00"),
            data_solicitacao=date.today(),
            status="solicitada",
            numero_sei_autorizacao=sei,
        )

    def test_sem_sei_rejeitado(self):
        """maximo_adesao_api = 0 e sem SEI → ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            self._adesao(sei="").clean()
        self.assertIn("SEI", str(ctx.exception))

    def test_com_sei_aceito(self):
        """maximo_adesao_api = 0 mas com SEI informado → deve passar."""
        try:
            self._adesao(sei="19.21.0010.0001234/2026-11").clean()
        except ValidationError:
            self.fail("clean() rejeitou adesão com SEI de autorização informado")

    def test_maximo_nao_zero_nao_exige_sei(self):
        """maximo_adesao_api > 0 → SEI não é obrigatório."""
        item_liberado = make_item_arp(self.arp, numero_item=2, maximo_adesao_api=Decimal("50"))
        adesao = AdesaoARP(
            arp=self.arp,
            item_arp=item_liberado,
            orgao_aderente_nome="Aderente Teste",
            orgao_aderente_cnpj="44.444.444/0001-44",
            quantidade_solicitada=Decimal("10"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("200.00"),
            data_solicitacao=date.today(),
            status="solicitada",
            numero_sei_autorizacao="",
        )
        try:
            adesao.clean()
        except ValidationError as e:
            # Só falha se a exceção for sobre SEI
            if "SEI" in str(e):
                self.fail("Exigiu SEI para item com maximo_adesao_api > 0")


# ---------------------------------------------------------------------------
# 5. VinculoPCAItemARP — vigência e excesso de quantidade
# ---------------------------------------------------------------------------

class VinculoPCAItemARPTest(TestCase):
    """Valida regras de vínculo PCA × ARP."""

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        self.item = make_item_arp(self.arp, qtd=Decimal("10"))
        self.item_pca = make_item_pca(self.orgao)

    def test_vinculo_valido_aceito(self):
        """Vínculo dentro da quantidade e ARP vigente deve ser salvo sem erros."""
        vinculo = VinculoPCAItemARP(
            item_pca=self.item_pca,
            item_arp=self.item,
            quantidade_comprometida=Decimal("5"),
        )
        try:
            vinculo.clean()
        except ValidationError:
            self.fail("clean() rejeitou vínculo válido")

    def test_vinculo_excede_quantidade_rejeitado(self):
        """Comprometer mais que a quantidade_registrada deve lançar ValidationError."""
        vinculo = VinculoPCAItemARP(
            item_pca=self.item_pca,
            item_arp=self.item,
            quantidade_comprometida=Decimal("11"),  # item tem 10 registrados
        )
        with self.assertRaises(ValidationError) as ctx:
            vinculo.clean()
        self.assertIn("excede", str(ctx.exception).lower())

    def test_vinculo_arp_cancelada_rejeitado(self):
        """ARP com status 'cancelada' não pode receber vínculos."""
        arp_cancelada = make_arp(self.orgao, numero_arp="002/2026", status="cancelada")
        item_cancelado = make_item_arp(arp_cancelada, qtd=Decimal("10"))
        vinculo = VinculoPCAItemARP(
            item_pca=self.item_pca,
            item_arp=item_cancelado,
            quantidade_comprometida=Decimal("5"),
        )
        with self.assertRaises(ValidationError) as ctx:
            vinculo.clean()
        self.assertIn("cancelad", str(ctx.exception).lower())

    def test_vinculo_arp_vencida_rejeitado(self):
        """ARP com data_fim_vigencia no passado deve ser rejeitada."""
        arp_vencida = make_arp(
            self.orgao,
            numero_arp="003/2026",
            status="vigente",
            dias_fim=-1,  # venceu ontem
        )
        item_vencido = make_item_arp(arp_vencida, qtd=Decimal("10"))
        vinculo = VinculoPCAItemARP(
            item_pca=self.item_pca,
            item_arp=item_vencido,
            quantidade_comprometida=Decimal("5"),
        )
        with self.assertRaises(ValidationError) as ctx:
            vinculo.clean()
        self.assertIn("venc", str(ctx.exception).lower())

    def test_acumulo_de_vinculos_valida_total(self):
        """
        Dois vínculos: 6 + 5 = 11 > 10 (quantidade_registrada) → o segundo deve ser rejeitado.
        """
        # Primeiro vínculo: 6 unidades
        item_pca_2 = make_item_pca(self.orgao)
        # Usamos update direto para não disparar clean() no primeiro
        VinculoPCAItemARP.objects.create(
            item_pca=item_pca_2,
            item_arp=self.item,
            quantidade_comprometida=Decimal("6"),
        )
        # Segundo vínculo: 5 unidades → total 11 > 10
        vinculo2 = VinculoPCAItemARP(
            item_pca=self.item_pca,
            item_arp=self.item,
            quantidade_comprometida=Decimal("5"),
        )
        with self.assertRaises(ValidationError):
            vinculo2.clean()


# ---------------------------------------------------------------------------
# 6. Propriedades de valor R$ — ItemARP
# ---------------------------------------------------------------------------

class ValorItemARPTest(TestCase):
    """
    Testa as propriedades de valor financeiro adicionadas na v3.1.
    Permite planejar aquisições com base no saldo em R$ da ARP.
    """

    def setUp(self):
        self.orgao = make_orgao()
        self.arp = make_arp(self.orgao)
        # 100 unidades × R$ 20,00 = R$ 2.000,00 registrados
        self.item = make_item_arp(self.arp, qtd=Decimal("100"), preco=Decimal("20.00"))

    def test_valor_total_registrado(self):
        """quantidade_registrada × valor_unitario."""
        self.assertEqual(self.item.valor_total_registrado, Decimal("2000.00"))

    def test_valor_total_contratado_inicial_zero(self):
        """Sem contratações, valor_total_contratado deve ser zero."""
        self.assertEqual(self.item.valor_total_contratado, Decimal("0"))

    def test_valor_total_contratado_soma_contratacoes(self):
        """valor_total_contratado soma as ContratacaoDecorrente não canceladas."""
        ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("30"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("600.00"),
            data_emissao=date.today(),
        )
        ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-002/2026",
            quantidade=Decimal("20"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("400.00"),
            data_emissao=date.today(),
        )
        self.assertEqual(self.item.valor_total_contratado, Decimal("1000.00"))

    def test_valor_total_contratado_exclui_cancelados(self):
        """ContratacaoDecorrente com status='cancelado' não entra no cálculo."""
        ct = ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("30"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("600.00"),
            data_emissao=date.today(),
        )
        ContratacaoDecorrente.objects.filter(pk=ct.pk).update(status="cancelado")
        self.assertEqual(self.item.valor_total_contratado, Decimal("0"))

    def test_valor_disponivel(self):
        """registrado − contratado − cedido_carona."""
        ContratacaoDecorrente.objects.create(
            arp=self.arp,
            item_arp=self.item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("60"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("1200.00"),
            data_emissao=date.today(),
        )
        # R$ 2.000 − R$ 1.200 − R$ 0 = R$ 800
        self.assertEqual(self.item.valor_disponivel, Decimal("800.00"))

    def test_valor_comprometido_pca(self):
        """Soma de VinculoPCAItemARP × valor_unitario."""
        item_pca = make_item_pca(self.orgao)
        VinculoPCAItemARP.objects.create(
            item_pca=item_pca,
            item_arp=self.item,
            quantidade_comprometida=Decimal("25"),
        )
        # 25 × R$ 20,00 = R$ 500,00
        self.assertEqual(self.item.valor_comprometido_pca, Decimal("500.00"))

    def test_valor_disponivel_eventual_cenario_multiexercicio(self):
        """
        Cenário do roadmap: ARP R$ 120k, PCA comprometeu R$ 50k,
        em 2026 contratado R$ 60k → eventual = R$ 10k.
        """
        orgao = make_orgao(cnpj="99.999.999/0001-99", sigla="MPPI2")
        arp = make_arp(orgao, numero_arp="001/2025")
        # 6.000 unidades × R$ 20,00 = R$ 120.000 registrados
        item = make_item_arp(arp, qtd=Decimal("6000"), preco=Decimal("20.00"))

        # Contratado em 2026: 3.000 × R$20 = R$ 60.000
        ContratacaoDecorrente.objects.create(
            arp=arp,
            item_arp=item,
            numero_pedido="PF-001/2026",
            quantidade=Decimal("3000"),
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("60000.00"),
            data_emissao=date(2026, 6, 15),
        )
        # PCA 2027 comprometeu: 2.500 × R$20 = R$ 50.000
        item_pca = make_item_pca(orgao)
        VinculoPCAItemARP.objects.create(
            item_pca=item_pca,
            item_arp=item,
            quantidade_comprometida=Decimal("2500"),
        )
        # eventual = 120k − 50k − 60k − 0 = R$ 10.000
        self.assertEqual(item.valor_disponivel_eventual, Decimal("10000.00"))


# ---------------------------------------------------------------------------
# 7. Validação de lote em ItemARP
# ---------------------------------------------------------------------------

class ItemARPLoteTest(TestCase):
    """ItemARP.clean() exige numero_lote quando AtaRegistroPrecos.usa_lotes=True."""

    def setUp(self):
        self.orgao = make_orgao()

    def test_arp_sem_lotes_aceita_item_sem_lote(self):
        """usa_lotes=False → numero_lote vazio é permitido."""
        arp = make_arp(self.orgao, usa_lotes=False)
        try:
            make_item_arp(arp, numero_lote="")
        except ValidationError:
            self.fail("clean() rejeitou item sem lote em ARP sem lotes")

    def test_arp_com_lotes_rejeita_item_sem_lote(self):
        """usa_lotes=True → numero_lote vazio deve lançar ValidationError."""
        arp = make_arp(self.orgao, usa_lotes=True)
        item = ItemARP(
            arp=arp,
            numero_item=1,
            numero_lote="",
            descricao="Papel A4",
            unidade_fornecimento="Resma",
            quantidade_registrada=Decimal("100"),
            valor_unitario=Decimal("20.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn("lote", str(ctx.exception).lower())

    def test_arp_com_lotes_aceita_item_com_lote(self):
        """usa_lotes=True e numero_lote preenchido → deve ser aceito."""
        arp = make_arp(self.orgao, usa_lotes=True)
        try:
            make_item_arp(arp, numero_lote="Lote 1")
        except ValidationError:
            self.fail("clean() rejeitou item com lote em ARP com lotes")

    def test_arp_com_lotes_aceita_multiplos_lotes(self):
        """Dois itens com lotes diferentes na mesma ARP."""
        arp = make_arp(self.orgao, usa_lotes=True)
        make_item_arp(arp, numero_item=1, numero_lote="Lote 1")
        make_item_arp(arp, numero_item=2, numero_lote="Lote 2")
        self.assertEqual(arp.itens.count(), 2)


# ---------------------------------------------------------------------------
# 8. Propriedade esta_vigente em AtaRegistroPrecos
# ---------------------------------------------------------------------------

class AtaVigenciaTest(TestCase):
    """AtaRegistroPrecos.esta_vigente considera status E data_fim_vigencia."""

    def setUp(self):
        self.orgao = make_orgao()

    def test_vigente_dentro_do_prazo(self):
        arp = make_arp(self.orgao, status="vigente", dias_fim=10)
        self.assertTrue(arp.esta_vigente)

    def test_vigente_prazo_expirado_falso(self):
        arp = make_arp(self.orgao, status="vigente", dias_fim=-1)
        self.assertFalse(arp.esta_vigente)

    def test_status_cancelada_nao_vigente(self):
        arp = make_arp(self.orgao, status="cancelada", dias_fim=10)
        self.assertFalse(arp.esta_vigente)

    def test_status_encerrada_nao_vigente(self):
        arp = make_arp(self.orgao, status="encerrada", dias_fim=10)
        self.assertFalse(arp.esta_vigente)
