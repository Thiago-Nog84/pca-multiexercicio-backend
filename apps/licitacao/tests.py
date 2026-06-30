from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import Orgao
from apps.licitacao.models import ProcessoLicitatorio, ItemLicitacao
from apps.srp.models import AtaRegistroPrecos
from apps.contratos.models import Contrato

User = get_user_model()


class LicitacaoVinculoTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="admin", password="123", email="admin@mppi.mp.br")
        self.client = Client()
        self.client.force_login(self.user)

        self.orgao = Orgao.objects.create(sigla="MPPI", nome="Ministério Público do Estado do Piauí")

        self.licitacao = ProcessoLicitatorio.objects.create(
            numero_edital="90001/2026",
            numero_controle_pncp="05805924000189-1-000001/2026-000001",
            processo_sei="19.21.0580.00001.2026",
            ano=2026,
            modalidade=ProcessoLicitatorio.Modalidade.PREGAO_ELETRONICO,
            objeto="Pregão para aquisição de computadores",
            valor_estimado=Decimal("100000.00"),
            valor_homologado=Decimal("95000.00")
        )

        self.item = ItemLicitacao.objects.create(
            licitacao=self.licitacao,
            numero_item=1,
            descricao="Notebook Dell",
            unidade="UN",
            quantidade=Decimal("10.0000"),
            valor_unitario_estimado=Decimal("10000.0000"),
            valor_unitario_homologado=Decimal("9500.0000")
        )

    def test_criacao_processo_licitatorio(self):
        self.assertEqual(str(self.licitacao), "Pregão Eletrônico nº 90001/2026 (2026)")
        self.assertEqual(self.licitacao.itens.count(), 1)

    def test_vinculo_com_arp(self):
        arp = AtaRegistroPrecos.objects.create(
            numero_arp="01/2026",
            processo_licitatorio="90001/2026",
            numero_pncp="05805924000189-1-000001/2026-000001",
            objeto="Registro de Preços Notebook",
            fornecedor_razao_social="Tech Ltda",
            fornecedor_cnpj_cpf="11222333000199",
            orgao_gerenciador=self.orgao,
            data_assinatura=date(2026, 1, 10),
            data_inicio_vigencia=date(2026, 1, 10),
            data_fim_vigencia=date(2027, 1, 10),
            criado_por=self.user
        )
        self.assertEqual(arp.licitacao_origem, self.licitacao)
        self.assertIn(arp, self.licitacao.arps_vinculadas)

    def test_vinculo_com_contrato(self):
        ct = Contrato.objects.create(
            numero_contrato="10/2026",
            numero_pncp="05805924000189-1-000001/2026-000001",
            numero_sei="19.21.0580.00001.2026",
            objeto="Contrato de Aquisição Notebook",
            contratado_razao_social="Tech Ltda",
            contratado_cnpj_cpf="11222333000199",
            orgao=self.orgao,
            valor_inicial=Decimal("50000.00"),
            valor_atual=Decimal("50000.00"),
            saldo_disponivel=Decimal("50000.00"),
            data_assinatura=date(2026, 2, 1),
            data_inicio_vigencia=date(2026, 2, 1),
            data_fim_vigencia=date(2027, 2, 1),
            criado_por=self.user
        )
        self.assertEqual(ct.licitacao_origem, self.licitacao)
        self.assertIn(ct, self.licitacao.contratos_vinculados)

    def test_dashboard_licitacao_view(self):
        url = reverse("licitacao:dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Processos Licitatórios e Contratações Diretas")
        self.assertContains(response, "90001/2026")
