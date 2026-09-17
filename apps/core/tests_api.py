"""
Testes de integração para a API REST DRF e assincronia Celery.
"""
from decimal import Decimal
from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.core.models import Orgao, UnidadeRequisitante, Notificacao
from apps.pca.models import PlanoContratacaoAnual, DocumentoFormalizacaoDemanda, ItemPCA
from apps.licitacao.models import ProcessoLicitatorio
from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos

User = get_user_model()


class APIRestIntegrationTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(
            username="admin_api", email="admin@mppi.mp.br", password="password123"
        )
        self.client.force_authenticate(user=self.user)

        self.orgao = Orgao.objects.create(sigla="MPPI", nome="Ministério Público do Piauí", cnpj="00.000.000/0001-91")
        self.unidade = UnidadeRequisitante.objects.create(orgao=self.orgao, sigla="CLC", nome="Licitações e Contratos")
        self.pca = PlanoContratacaoAnual.objects.create(orgao=self.orgao, exercicio=2026, status="coleta")

    def test_core_endpoints(self):
        # /api/v1/core/me/
        resp = self.client.get("/api/v1/core/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["username"], "admin_api")

        # /api/v1/core/orgaos/
        resp = self.client.get("/api/v1/core/orgaos/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

        # /api/v1/core/unidades/
        resp = self.client.get("/api/v1/core/unidades/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_notificacoes_endpoints(self):
        notif = Notificacao.objects.create(
            titulo="Aviso Teste",
            mensagem="Mensagem de teste",
            tipo="info",
            unidade_destino=self.unidade,
        )
        resp = self.client.get("/api/v1/core/notificacoes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp_marcar = self.client.post(f"/api/v1/core/notificacoes/{notif.id}/marcar_lida/")
        self.assertEqual(resp_marcar.status_code, status.HTTP_200_OK)

    def test_celery_task_status_endpoint(self):
        with patch("apps.core.views_tasks.AsyncResult") as mock_async:
            mock_res = MagicMock()
            mock_res.state = "SUCCESS"
            mock_res.ready.return_value = True
            mock_res.successful.return_value = True
            mock_res.result = {"sucesso": True}
            mock_async.return_value = mock_res

            resp = self.client.get("/api/v1/core/tasks/fake-task-id-123/")
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.data["status"], "SUCCESS")
            self.assertEqual(resp.data["ready"], True)
            self.assertEqual(resp.data["result"], {"sucesso": True})

    def test_contratos_endpoints_and_celery_dispatch(self):
        ct = Contrato.objects.create(
            numero_contrato="10/2026",
            tipo="fornecimento",
            objeto="Fornecimento de TI",
            orgao=self.orgao,
            unidade_requisitante=self.unidade,
            valor_inicial=Decimal("1000.00"),
            valor_atual=Decimal("1000.00"),
            saldo_disponivel=Decimal("1000.00"),
            status="vigente",
            data_assinatura=date.today(),
            data_inicio_vigencia=date.today(),
            data_fim_vigencia=date.today(),
            contratado_razao_social="Empresa TI",
            contratado_cnpj_cpf="00111222000133",
        )
        resp = self.client.get("/api/v1/contratos/contratos/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp_dash = self.client.get("/api/v1/contratos/dashboard/")
        self.assertEqual(resp_dash.status_code, status.HTTP_200_OK)
        self.assertIn("estatisticas", resp_dash.data)

        with patch("apps.contratos.views.sincronizar_links_contratos_task.delay") as mock_task:
            mock_res = MagicMock()
            mock_res.id = "task-ct-999"
            mock_task.return_value = mock_res

            resp_sync = self.client.post("/api/v1/contratos/sincronizar-links/", {"uasg": "926092"})
            self.assertEqual(resp_sync.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(resp_sync.data["task_id"], "task-ct-999")

    def test_planejamento_dods_endpoints(self):
        resp = self.client.get("/api/v1/planejamento/dods/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_licitacao_endpoints_and_celery_dispatch(self):
        ProcessoLicitatorio.objects.create(
            numero_edital="01/2026",
            modalidade="pregao_eletronico",
            objeto="Aquisição de computadores",
            ano=2026,
        )
        resp = self.client.get("/api/v1/licitacao/processos/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp_dash = self.client.get("/api/v1/licitacao/dashboard/")
        self.assertEqual(resp_dash.status_code, status.HTTP_200_OK)

        with patch("apps.licitacao.views.sincronizar_licitacoes_pncp_task.delay") as mock_task:
            mock_res = MagicMock()
            mock_res.id = "task-lic-888"
            mock_task.return_value = mock_res

            resp_sync = self.client.post("/api/v1/licitacao/sincronizar-pncp/", {"ano": 2026})
            self.assertEqual(resp_sync.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(resp_sync.data["task_id"], "task-lic-888")

    def test_srp_endpoints_and_celery_dispatch(self):
        resp = self.client.get("/api/v1/srp/arps/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp_dash = self.client.get("/api/v1/srp/dashboard/")
        self.assertEqual(resp_dash.status_code, status.HTTP_200_OK)

        with patch("apps.srp.views.importar_arp_compras_gov_task.delay") as mock_task:
            mock_res = MagicMock()
            mock_res.id = "task-srp-777"
            mock_task.return_value = mock_res

            resp_sync = self.client.post("/api/v1/srp/importar-comprasnet/", {"ano_inicio": 2026})
            self.assertEqual(resp_sync.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(resp_sync.data["task_id"], "task-srp-777")

    def test_pca_batch_creation_and_dashboard(self):
        payload = {
            "pca_id": self.pca.id,
            "unidade_id": self.unidade.id,
            "numero_sei": "19.00.0000.0001/2026",
            "descricao_objeto": "Objeto do DFD em Lote",
            "justificativa": "Justificativa da necessidade",
            "grau_prioridade": "alto",
            "itens": [
                {
                    "descricao": "Item 1 - Caneta",
                    "categoria": "material",
                    "unidade_fornecimento": "CX",
                    "quantidade_estimada": 10,
                    "valor_unitario_estimado": "5.50",
                    "tipo_demanda": "nova",
                    "modalidade": "pregao_eletronico",
                },
                {
                    "descricao": "Item 2 - Caderno",
                    "categoria": "material",
                    "unidade_fornecimento": "UN",
                    "quantidade_estimada": 20,
                    "valor_unitario_estimado": "12.00",
                    "tipo_demanda": "nova",
                    "modalidade": "pregao_eletronico",
                },
            ],
        }
        resp = self.client.post("/api/v1/pca/dfds/cadastro_grupo/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("itens", resp.data)
        self.assertEqual(len(resp.data["itens"]), 2)

        resp_dash = self.client.get(f"/api/v1/pca/dashboard/?pca={self.pca.id}")
        self.assertEqual(resp_dash.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_dash.data["total_demandas"], 2)

    def test_siafe_celery_dispatch(self):
        with patch("apps.siafe.views.sincronizar_execucao_siafe_task.delay") as mock_task:
            mock_res = MagicMock()
            mock_res.id = "task-siafe-666"
            mock_task.return_value = mock_res

            resp = self.client.post("/api/v1/siafe/sincronizar-execucao/", {"ug": "926092"})
            self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(resp.data["task_id"], "task-siafe-666")
