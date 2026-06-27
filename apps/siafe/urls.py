from django.urls import path

from . import views
from .views_contratos import (
    ContratosUGView, ContratoDetalheView, ContratosPaginadoView, ContratoConsultaView,
    ConvenioDetalheView, ConveniosPaginadoView,
)
from .views_execucao import (
    NotasLiquidacaoPorUGView, NotasLiquidacaoPaginadoView,
    NotasReservaPorUGView, DespesasTransacaoPaginadoView,
    OBOrcamentariaPorCredorView, OBExtraOrcamentariaPorCredorView,
    OBRetencaoPorCredorView,
)
from .views_fatos import (
    FatoReservaOrcamentariaView, FatoAquisicaoView, FatoSolicitacaoConsumoView,
    FatoOrdemServicoView, FatoAprovacaoFiscalView,
    FatoEncerramentoAquisicaoView, FatoAnulacaoNPView,
)
from .views_loa import MetaAcaoConsultaView, PropostaDespesaLOAView

app_name = "siafe"

urlpatterns = [

    # --- Nota de Empenho ---
    path("nota-empenho/<int:exercicio>/<str:codigo_ug>/",
         views.NotaEmpenhoPorUGView.as_view(), name="nota-empenho-ug"),
    path("nota-empenho/<int:exercicio>/<str:codigo_ug>/<int:mes>/",
         views.NotaEmpenhoPorUGMesView.as_view(), name="nota-empenho-ug-mes"),
    path("nota-empenho/<int:exercicio>/paginado/",
         views.NotaEmpenhoPaginadoView.as_view(), name="nota-empenho-paginado"),

    # --- Saldo Orcamentario ---
    path("saldo-orcamentario/<int:exercicio>/<str:codigo_ug>/",
         views.SaldoOrcamentarioAnualView.as_view(), name="saldo-orcamentario-anual"),
    path("saldo-orcamentario/<int:exercicio>/mensal/<int:mes>/",
         views.SaldoOrcamentarioMensalView.as_view(), name="saldo-orcamentario-mensal"),

    # --- Estrutura Classificatoria ---
    path("estrutura/<int:exercicio>/acoes/",
         views.AcoesView.as_view(), name="acoes"),
    path("estrutura/<int:exercicio>/naturezas-despesa/",
         views.NaturezasDespesaView.as_view(), name="naturezas-despesa"),
    path("estrutura/<int:exercicio>/elementos-despesa/",
         views.ElementosDespesaView.as_view(), name="elementos-despesa"),
    path("estrutura/<int:exercicio>/programas/",
         views.ProgramasView.as_view(), name="programas"),

    # --- Credores ---
    path("credores/<int:exercicio>/",
         views.CredoresView.as_view(), name="credores"),
    path("credores/<int:exercicio>/<str:codigo>/",
         views.CredorDetalheView.as_view(), name="credor-detalhe"),

    # --- Saldo Contabil ---
    path("saldo-contabil/<int:exercicio>/<int:mes>/<str:conta>/<str:codigo_ug>/",
         views.SaldoContabilMensalView.as_view(), name="saldo-contabil-mensal"),

    # --- CONTRATOS E CONVENIOS ---
    path("contratos/<int:exercicio>/ug/<str:codigo_ug>/",
         ContratosUGView.as_view(), name="contratos-por-ug"),
    path("contratos/<int:exercicio>/<str:codigo_contrato>/",
         ContratoDetalheView.as_view(), name="contrato-detalhe"),
    path("contratos/<int:exercicio>/lista/",
         ContratosPaginadoView.as_view(), name="contratos-lista"),
    path("contratos/<int:exercicio>/consulta/",
         ContratoConsultaView.as_view(), name="contratos-consulta"),
    path("convenios/<int:exercicio>/<str:codigo_convenio>/",
         ConvenioDetalheView.as_view(), name="convenio-detalhe"),
    path("convenios/<int:exercicio>/lista/",
         ConveniosPaginadoView.as_view(), name="convenios-lista"),

    # --- EXECUCAO ORCAMENTARIA ---
    path("exec-orcamentaria/<int:exercicio>/<str:codigo_ug>/liquidacoes/",
         NotasLiquidacaoPorUGView.as_view(), name="liquidacoes-ug"),
    path("exec-orcamentaria/<int:exercicio>/liquidacoes/lista/",
         NotasLiquidacaoPaginadoView.as_view(), name="liquidacoes-lista"),
    path("exec-orcamentaria/<int:exercicio>/<str:codigo_ug>/reservas/",
         NotasReservaPorUGView.as_view(), name="reservas-ug"),
    path("exec-orcamentaria/<int:exercicio>/transacoes/",
         DespesasTransacaoPaginadoView.as_view(), name="despesas-transacao"),

    # --- EXECUCAO FINANCEIRA ---
    path("exec-financeira/<int:exercicio>/<str:codigo_credor>/ob-orcamentaria/",
         OBOrcamentariaPorCredorView.as_view(), name="ob-orcamentaria-credor"),
    path("exec-financeira/<int:exercicio>/<str:codigo_credor>/ob-extra/",
         OBExtraOrcamentariaPorCredorView.as_view(), name="ob-extra-credor"),
    path("exec-financeira/<int:exercicio>/<str:codigo_credor>/ob-retencao/",
         OBRetencaoPorCredorView.as_view(), name="ob-retencao-credor"),

    # --- FATOS DE CONTRATOS ---
    path("fatos/<int:exercicio>/reserva-orcamentaria/",
         FatoReservaOrcamentariaView.as_view(), name="fato-reserva"),
    path("fatos/<int:exercicio>/aquisicao/",
         FatoAquisicaoView.as_view(), name="fato-aquisicao"),
    path("fatos/<int:exercicio>/solicitacao-consumo/",
         FatoSolicitacaoConsumoView.as_view(), name="fato-consumo"),
    path("fatos/<int:exercicio>/ordem-servico/",
         FatoOrdemServicoView.as_view(), name="fato-ordem-servico"),
    path("fatos/<int:exercicio>/aprovacao-fiscal/",
         FatoAprovacaoFiscalView.as_view(), name="fato-aprovacao-fiscal"),
    path("fatos/<int:exercicio>/encerramento-aquisicao/",
         FatoEncerramentoAquisicaoView.as_view(), name="fato-encerramento"),
    path("fatos/<int:exercicio>/anulacao-np/",
         FatoAnulacaoNPView.as_view(), name="fato-anulacao-np"),

    # --- PLANEJAMENTO LOA ---
    path("loa/<int:exercicio>/meta-acao/",
         MetaAcaoConsultaView.as_view(), name="loa-meta-acao"),
    path("loa/<int:exercicio>/proposta-despesa/",
         PropostaDespesaLOAView.as_view(), name="loa-proposta-despesa"),
]
