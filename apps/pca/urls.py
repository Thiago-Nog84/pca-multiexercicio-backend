from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ConformidadeItemViewSet, DFDViewSet, ItemPCAViewSet, PlanoContratacaoAnualViewSet
from .views_prazos import ControlePrazosView, RiscosView
from .views_relatorios import (
    RelatoriosView,
    RelBaseCompletaView,
    RelOrcamentoSetorialView,
    RelPrazosCriticosView,
    RelDemandasSuspensasView,
    RelModalidadeView,
)
from .views_cadastro import (
    CadastroGrupoDemandaView,
    ContratosVigentesDisponiveisJSON,
    DescricaoAutocompleteJSON,
    ItensARPDisponiveisJSON,
    ValidarCodigoCatalogoJSON,
    VincularItemPCAView,
)
from .views_analise import AnalisarItemPCAView, AnalisarLoteItensPCAView
from .views_relatorio import ExportarDemandasPDFView
from .views_suspensas import DemandasSuspensasView
from .views_template import (
    CatalogoSearchView,
    ClonarPCAView,
    DashboardPCAView,
    DemandasPCAView,
    ItemPCADetalheView,
    OrcamentoView,
    RenovacaoExercicioView,
)
from .views_validacao import ARPsVigentesJSON, ValidacaoDemandas, ValidacaoAcao, ValidacaoVincularARP
from .views_workflow import WorkflowPCAView

router = DefaultRouter()
router.register("planos", PlanoContratacaoAnualViewSet, basename="plano")
router.register("dfds", DFDViewSet, basename="dfd")
router.register("itens", ItemPCAViewSet, basename="item")
router.register("conformidade", ConformidadeItemViewSet, basename="conformidade")

app_name = "pca"

urlpatterns = [
    path("", DashboardPCAView.as_view(), name="dashboard"),
    path("demandas/", DemandasPCAView.as_view(), name="demandas"),
    path(
        "demandas/<int:pk>/analisar/",
        AnalisarItemPCAView.as_view(),
        name="analisar_item",
    ),
    path(
        "demandas/analisar-lote/",
        AnalisarLoteItensPCAView.as_view(),
        name="analisar_lote",
    ),
    path(
        "demandas/exportar.pdf",
        ExportarDemandasPDFView.as_view(),
        name="exportar_demandas_pdf",
    ),
    path("cadastro-grupo/", CadastroGrupoDemandaView.as_view(), name="cadastro_grupo"),
    path("api/arp-itens-disponiveis.json", ItensARPDisponiveisJSON.as_view(), name="arp_itens_disponiveis_json"),
    path(
        "api/contratos-vigentes-disponiveis.json",
        ContratosVigentesDisponiveisJSON.as_view(),
        name="contratos_vigentes_disponiveis_json",
    ),
    path(
        "api/validar-codigo-catalogo.json",
        ValidarCodigoCatalogoJSON.as_view(),
        name="validar_codigo_catalogo_json",
    ),
    path(
        "api/descricao-autocomplete.json",
        DescricaoAutocompleteJSON.as_view(),
        name="descricao_autocomplete_json",
    ),
    path("suspensas/", DemandasSuspensasView.as_view(), name="suspensas"),
    path("workflow/", WorkflowPCAView.as_view(), name="workflow"),
    path("item/<int:pk>/", ItemPCADetalheView.as_view(), name="item_detalhe"),
    path("item/<int:pk>/vincular/", VincularItemPCAView.as_view(), name="vincular_item"),
    path("renovacao/", RenovacaoExercicioView.as_view(), name="renovacao"),
    path("orcamento/", OrcamentoView.as_view(), name="orcamento"),
    path("prazos/", ControlePrazosView.as_view(), name="prazos"),
    path("riscos/", RiscosView.as_view(), name="riscos"),
    path("clonar/", ClonarPCAView.as_view(), name="clonar_pca"),
    path("validar/<int:exercicio>/", ValidacaoDemandas.as_view(), name="validar_demandas"),
    path("validar/<int:exercicio>/acao/", ValidacaoAcao.as_view(), name="validar_acao"),
    path("validar/<int:exercicio>/vincular-arp/", ValidacaoVincularARP.as_view(), name="validar_vincular_arp"),
    path("validar/<int:exercicio>/arps-vigentes.json", ARPsVigentesJSON.as_view(), name="arps_vigentes_json"),
    path("relatorios/", RelatoriosView.as_view(), name="relatorios"),
    path("relatorios/base-completa/", RelBaseCompletaView.as_view(), name="rel_base_completa"),
    path("relatorios/orcamento-setorial/", RelOrcamentoSetorialView.as_view(), name="rel_orcamento_setorial"),
    path("relatorios/prazos-criticos/", RelPrazosCriticosView.as_view(), name="rel_prazos_criticos"),
    path("relatorios/suspensas/", RelDemandasSuspensasView.as_view(), name="rel_suspensas"),
    path("relatorios/modalidade/", RelModalidadeView.as_view(), name="rel_modalidade"),
    path("api/catalogo/", CatalogoSearchView.as_view(), name="catalogo_search"),
    path("api/", include(router.urls)),
]
