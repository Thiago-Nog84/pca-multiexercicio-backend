"""
Cadastro de demandas em grupo — PCA 2027.

Ato PGJ 1381/2024 exige um DFD por demanda, mas nao exige um item por vez:
esta tela cria 1 DocumentoFormalizacaoDemanda + N ItemPCA numa unica
submissao (ex: "Acucar e cafe" com 2 itens), em vez do fluxo atual em que
cada ItemPCA e criado isoladamente via admin/API.

Quando um item usa ARP propria, a tela busca (via ItensARPDisponiveisJSON)
as atas vigentes que ja tem aquele item cadastrado e mostra o saldo real
disponivel (ItemARP.quantidade_disponivel_eventual), que ja desconta
comprometimento no PCA, contratacoes e caronas. Ao escolher uma ARP, o
numero_lote_pca do ItemPCA e preenchido automaticamente a partir do
numero_lote do ItemARP, garantindo coerencia com a validacao feita em
VinculoPCAItemARP.clean() (regra 3 - coerencia de lote).

Quando o tipo_demanda indica que a demanda ja e atendida por um contrato
em vigor (renovacao, aditivo, apostilamento ou repactuacao — em vez de
"nova"), a tela busca (via ContratosVigentesDisponiveisJSON) os contratos
vigentes do MPPI que casam com a descricao, mostrando o saldo_disponivel
do proprio Contrato. Isso substitui o campo "Numero do Contrato" de texto
livre, sem validacao, que o sistema de referencia usa: aqui o vinculo e
a um Contrato real e o valor estimado do item e checado contra o saldo
disponivel antes de salvar.

O campo Descricao tem autocomplete (via DescricaoAutocompleteJSON) que busca
tanto no ItemCatalogo (biblioteca institucional, sem preco) quanto no
historico real de ItemPCA de exercicios anteriores (com preco e quantidade
da ultima contratacao) — evita redigitar um item que a unidade ja comprou
antes e da uma referencia de preco real, nao so a descricao padrao.

A busca de contrato vigente (ContratosVigentesDisponiveisJSON) tambem cruza
com srp.ContratoARP — contratos decorrentes de ARP importados via API
(dadosabertos.compras.gov.br / PNCP, comando `importar_contratos_arp`).
Contratos ja cadastrados manualmente em contratos.Contrato aparecem
vinculaveis normalmente; contratos vistos so na API (ainda sem Contrato
correspondente) aparecem como sugestao informativa, com link para
cadastra-los (formulario do admin pre-preenchido com os dados da API).
Isso garante que a busca esteja sempre lastreada em dado de API
(compras.gov.br/PNCP), nunca em texto livre ou leitura do site do MPPI.
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views import View

from apps.core.models import UnidadeRequisitante

from .models import (
    CLASSIFICACAO_CONTINUIDADE,
    DocumentoFormalizacaoDemanda,
    ItemCatalogo,
    ItemPCA,
    PlanoContratacaoAnual,
)


def _pca_atual():
    hoje = datetime.date.today()
    return (
        PlanoContratacaoAnual.objects.filter(exercicio=hoje.year).first()
        or PlanoContratacaoAnual.objects.order_by("-exercicio").first()
    )


def _decimal(valor, default="0"):
    """Converte string de formulario (aceita virgula) em Decimal, com fallback seguro."""
    if valor in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(valor).replace(",", "."))
    except InvalidOperation:
        return Decimal(default)


@method_decorator(login_required, name="dispatch")
class CadastroGrupoDemandaView(View):
    """
    GET  /pca/cadastro-grupo/  -> formulario com N linhas de item dentro de 1 grupo
    POST /pca/cadastro-grupo/  -> cria o DFD + os ItemPCA (e vinculos de ARP) numa transacao
    """

    template_name = "pca/cadastro_grupo.html"

    def get(self, request):
        pca = _pca_atual()
        context = {
            "pca": pca,
            "todos_pcas": PlanoContratacaoAnual.objects.order_by("-exercicio"),
            "unidades": UnidadeRequisitante.objects.filter(ativo=True).order_by("sigla"),
            "categoria_choices": ItemPCA.CATEGORIAS,
            "tipo_demanda_choices": ItemPCA.TIPO_DEMANDA,
            "modalidade_choices": ItemPCA.MODALIDADE,
            "normativo_choices": ItemPCA.NORMATIVO,
            "uo_choices": ItemPCA.UNIDADE_ORCAMENTARIA,
            "continuidade_choices": CLASSIFICACAO_CONTINUIDADE,
            "grau_prioridade_choices": [("baixo", "Baixo"), ("medio", "Médio"), ("alto", "Alto")],
        }
        return render(request, self.template_name, context)

    def post(self, request):
        from apps.contratos.models import Contrato
        from apps.srp.models import ItemARP, VinculoPCAItemARP

        pca_id = request.POST.get("pca_id")
        unidade_id = request.POST.get("unidade_id")
        nome_grupo = request.POST.get("descricao_objeto", "").strip()
        justificativa = request.POST.get("justificativa", "").strip()
        prazo_necessidade = request.POST.get("prazo_necessidade") or None
        grau_prioridade = request.POST.get("grau_prioridade", "medio")
        numero_sei = request.POST.get("numero_sei", "").strip()
        linhas = [l for l in request.POST.get("linhas", "").split(",") if l.strip()]

        if not nome_grupo:
            messages.error(request, "Informe o nome/objeto do grupo de demandas.")
            return redirect("pca:cadastro_grupo")
        if not linhas:
            messages.error(request, "Adicione ao menos um item ao grupo antes de salvar.")
            return redirect("pca:cadastro_grupo")

        pca = get_object_or_404(PlanoContratacaoAnual, pk=pca_id)
        unidade = get_object_or_404(UnidadeRequisitante, pk=unidade_id)

        itens_criados = []
        try:
            with transaction.atomic():
                count_dfds = DocumentoFormalizacaoDemanda.objects.filter(pca=pca, unidade=unidade).count()
                numero_dfd = f"DFD-{pca.exercicio}-{unidade.sigla}-{count_dfds + 1:02d}"

                dfd = DocumentoFormalizacaoDemanda.objects.create(
                    pca=pca,
                    unidade=unidade,
                    numero_sei=numero_sei,
                    numero_dfd=numero_dfd,
                    descricao_objeto=nome_grupo,
                    justificativa=justificativa or f"Demanda de grupo: {nome_grupo}.",
                    prazo_necessidade=prazo_necessidade or datetime.date(pca.exercicio, 12, 31),
                    grau_prioridade=grau_prioridade,
                    status="rascunho",
                    requisitante=request.user if request.user.is_authenticated else None,
                )

                ultimo_num = 0
                for idx in linhas:
                    p = f"item_{idx}_"
                    descricao = request.POST.get(p + "descricao", "").strip()
                    categoria = request.POST.get(p + "categoria", "").strip()
                    unidade_fornecimento = request.POST.get(p + "unidade_fornecimento", "").strip()

                    if not descricao or not categoria or not unidade_fornecimento:
                        raise ValidationError(
                            f"Item na linha {idx}: descrição, categoria e unidade de fornecimento "
                            f"são obrigatórios."
                        )

                    quantidade_estimada = _decimal(request.POST.get(p + "quantidade_estimada"))
                    valor_unitario_estimado = _decimal(request.POST.get(p + "valor_unitario_estimado"))
                    if quantidade_estimada <= 0 or valor_unitario_estimado <= 0:
                        raise ValidationError(
                            f"Item \"{descricao[:40]}\": quantidade e valor unitário devem ser maiores que zero."
                        )

                    item_arp_id = request.POST.get(p + "item_arp_id") or None
                    contrato_id = request.POST.get(p + "contrato_id") or None
                    item_catalogo_id = request.POST.get(p + "item_catalogo_id") or None

                    ultimo_num += 1
                    item = ItemPCA(
                        dfd=dfd,
                        numero_item=ultimo_num,
                        categoria=categoria,
                        codigo_catmat_catser=request.POST.get(p + "codigo_catmat_catser", "").strip(),
                        descricao=descricao,
                        unidade_fornecimento=unidade_fornecimento,
                        quantidade_estimada=quantidade_estimada,
                        valor_unitario_estimado=valor_unitario_estimado,
                        valor_total_estimado=quantidade_estimada * valor_unitario_estimado,
                        tipo_demanda=request.POST.get(p + "tipo_demanda", "nova"),
                        modalidade=request.POST.get(p + "modalidade", "pregao_eletronico"),
                        normativo=request.POST.get(p + "normativo", "14133_2021"),
                        unidade_orcamentaria=request.POST.get(p + "unidade_orcamentaria", "pgj"),
                        classificacao_continuidade=request.POST.get(p + "classificacao_continuidade", "eventual"),
                        status="nao_iniciado",
                    )

                    item_arp = None
                    if item_arp_id:
                        try:
                            item_arp = ItemARP.objects.select_related("arp").get(pk=item_arp_id)
                        except ItemARP.DoesNotExist:
                            raise ValidationError(
                                f"Item \"{descricao[:40]}\": a ARP selecionada não foi encontrada "
                                f"(pode ter sido alterada). Refaça a busca de ARP para este item."
                            )
                        item.is_srp = True
                        # Copia o numero_lote do ItemARP para garantir coerencia com
                        # VinculoPCAItemARP.clean() (regra de compatibilidade de lote).
                        item.numero_lote_pca = item_arp.numero_lote

                    if contrato_id:
                        try:
                            contrato = Contrato.objects.get(pk=contrato_id)
                        except Contrato.DoesNotExist:
                            raise ValidationError(
                                f"Item \"{descricao[:40]}\": o contrato selecionado não foi "
                                f"encontrado (pode ter sido alterado). Refaça a busca."
                            )
                        hoje = datetime.date.today()
                        if contrato.status != "vigente" or contrato.data_fim_vigencia < hoje:
                            raise ValidationError(
                                f"Item \"{descricao[:40]}\": o contrato {contrato.numero_contrato} "
                                f"não está mais vigente. Busque novamente ou cadastre como nova contratação."
                            )
                        if item.valor_total_estimado > contrato.saldo_disponivel:
                            raise ValidationError(
                                f"Item \"{descricao[:40]}\": valor estimado "
                                f"(R$ {item.valor_total_estimado}) excede o saldo disponível do "
                                f"contrato {contrato.numero_contrato} (R$ {contrato.saldo_disponivel})."
                            )
                        item.contrato_vigente = contrato
                        if not item.data_vencimento_contrato_anterior:
                            item.data_vencimento_contrato_anterior = contrato.data_fim_vigencia

                    if item_catalogo_id:
                        # Vinculo apenas informativo (autocomplete) — se o catalogo
                        # tiver sido alterado/removido nesse meio tempo, nao bloqueia
                        # o cadastro do grupo, so deixa de linkar.
                        item.item_catalogo = ItemCatalogo.objects.filter(pk=item_catalogo_id).first()

                    item.full_clean(exclude=["codigo_pca"])
                    item.save()
                    itens_criados.append(item)

                    if item_arp is not None:
                        qtd_vinculo = _decimal(
                            request.POST.get(p + "quantidade_comprometida"),
                            default=str(quantidade_estimada),
                        )
                        vinculo = VinculoPCAItemARP(
                            item_pca=item,
                            item_arp=item_arp,
                            quantidade_comprometida=qtd_vinculo,
                            criado_por=request.user if request.user.is_authenticated else None,
                        )
                        # full_clean() valida vigencia da ARP, saldo disponivel e
                        # coerencia de lote — mensagem de erro ja vem pronta do model.
                        vinculo.full_clean()
                        vinculo.save()

        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"Grupo não cadastrado: {detalhe}")
            return redirect("pca:cadastro_grupo")

        messages.success(
            request,
            f"Grupo \"{nome_grupo}\" cadastrado com {len(itens_criados)} item(ns) em {numero_dfd}."
        )
        return redirect("pca:demandas")


@method_decorator(login_required, name="dispatch")
class ItensARPDisponiveisJSON(View):
    """
    GET /pca/api/arp-itens-disponiveis.json?q=<descricao ou codigo CATMAT/CATSER>

    Busca itens de ARPs vigentes que casam com o texto digitado, para o
    cadastro em grupo escolher a fonte quando o item usa modalidade
    "ARP própria". Retorna o saldo real (quantidade_disponivel_eventual),
    que ja desconta o que outras demandas do PCA ja comprometeram, o que
    ja foi contratado e o que ja foi cedido em carona.
    """

    def get(self, request):
        from apps.srp.models import ItemARP

        q = request.GET.get("q", "").strip()
        if len(q) < 3:
            return JsonResponse({"itens": []})

        hoje = datetime.date.today()
        qs = (
            ItemARP.objects
            .filter(arp__status="vigente", arp__data_fim_vigencia__gte=hoje)
            .filter(Q(descricao__unaccent__icontains=q) | Q(codigo_catmat_catser__icontains=q))
            .select_related("arp")
            .order_by("arp__numero_arp", "numero_item")[:30]
        )

        itens = [
            {
                "id": it.pk,
                "arp_id": it.arp_id,
                "arp_numero": it.arp.numero_arp,
                "lote": it.numero_lote or "",
                "fornecedor": it.arp.fornecedor_razao_social,
                "vigencia_fim": it.arp.data_fim_vigencia.strftime("%d/%m/%Y"),
                "numero_item": it.numero_item,
                "descricao": it.descricao[:150],
                "unidade_fornecimento": it.unidade_fornecimento,
                "valor_unitario": float(it.valor_unitario),
                "quantidade_registrada": float(it.quantidade_registrada),
                "quantidade_contratada": float(it.quantidade_contratada),
                "quantidade_comprometida_pca": float(it.quantidade_comprometida_pca),
                "quantidade_disponivel_eventual": float(it.quantidade_disponivel_eventual),
            }
            for it in qs
        ]
        return JsonResponse({"itens": itens})


@method_decorator(login_required, name="dispatch")
class ContratosVigentesDisponiveisJSON(View):
    """
    GET /pca/api/contratos-vigentes-disponiveis.json?q=<objeto, numero ou fornecedor>

    Busca contratos vigentes do MPPI que casam com o texto digitado, para o
    cadastro em grupo escolher a fonte quando a demanda ja e atendida por um
    contrato em vigor (tipo_demanda = renovacao/aditivo/apostilamento/
    repactuacao), em vez de exigir nova licitacao.

    Diferente do sistema de referencia (campo "Numero do Contrato" de texto
    livre, sem nenhuma validacao), aqui o vinculo e a um Contrato real e o
    saldo_disponivel e mostrado e checado antes de salvar o item.

    Retorna DUAS listas:
    - "contratos": registros de contratos.Contrato (cadastro manual local,
      com saldo_disponivel/gestor/fiscal) — vinculaveis diretamente
      (contrato_id), pois ItemPCA.contrato_vigente e FK para este model.
    - "contratos_api": registros de srp.ContratoARP, importados via API
      (dadosabertos.compras.gov.br / PNCP pelo comando
      `importar_contratos_arp`) que casam com a busca mas AINDA NAO tem
      um Contrato correspondente cadastrado localmente. Sao apenas
      informativos (nao tem saldo_disponivel/gestor/fiscal rastreados) —
      a tela oferece um link para cadastra-los como Contrato real
      (formulario do admin pre-preenchido a partir do dado da API), o que
      os torna vinculaveis na proxima busca. Isso garante que a busca
      esteja sempre lastreada em dado de API, conforme exigido, mesmo
      quando o contrato ainda nao foi formalizado no modulo de Contratos.
    """

    def get(self, request):
        from apps.contratos.models import Contrato
        from apps.srp.models import ContratoARP

        q = request.GET.get("q", "").strip()
        if len(q) < 3:
            return JsonResponse({"contratos": [], "contratos_api": []})

        hoje = datetime.date.today()

        qs = (
            Contrato.objects
            .filter(status="vigente", data_fim_vigencia__gte=hoje)
            .filter(
                Q(objeto__unaccent__icontains=q)
                | Q(numero_contrato__icontains=q)
                | Q(contratado_razao_social__unaccent__icontains=q)
            )
            .order_by("-data_assinatura")[:20]
        )

        contratos = [
            {
                "id": c.pk,
                "numero_contrato": c.numero_contrato,
                "tipo_display": c.get_tipo_display(),
                "objeto": c.objeto[:150],
                "contratado": c.contratado_razao_social,
                "vigencia_fim": c.data_fim_vigencia.strftime("%d/%m/%Y"),
                "dias_para_vencimento": c.dias_para_vencimento,
                "valor_atual": float(c.valor_atual),
                "saldo_disponivel": float(c.saldo_disponivel),
            }
            for c in qs
        ]

        # Numeros de contrato ja cadastrados localmente — nao repetir na lista da API
        numeros_ja_cadastrados = set(
            Contrato.objects.values_list("numero_contrato", flat=True)
        )

        qs_api = (
            ContratoARP.objects
            # Vigencia desconhecida (NULL) NAO esconde o contrato: o dado da API
            # e informativo e o PNCP nem sempre retorna as datas de vigencia
            # (confirmado em 2026-07-07 — contratos 00035/00036 vieram sem elas).
            .filter(Q(data_fim_vigencia__gte=hoje) | Q(data_fim_vigencia__isnull=True))
            .filter(
                Q(arp__objeto__unaccent__icontains=q)
                | Q(numero_contrato__icontains=q)
                | Q(contratado_nome__unaccent__icontains=q)
            )
            .exclude(numero_contrato__in=numeros_ja_cadastrados)
            .select_related("arp")
            .order_by("-data_assinatura")[:20]
        )

        contratos_api = []
        for c in qs_api:
            cadastro_params = {
                "numero_contrato": c.numero_contrato,
                "objeto": (c.arp.objeto if c.arp_id else "")[:500],
                "contratado_razao_social": c.contratado_nome,
                "contratado_cnpj_cpf": c.contratado_cnpj,
                "valor_inicial": str(c.valor_total),
                "valor_atual": str(c.valor_total),
                "numero_pncp": c.numero_pncp,
            }
            if c.data_assinatura:
                cadastro_params["data_assinatura"] = c.data_assinatura.strftime("%Y-%m-%d")
            if c.data_inicio_vigencia:
                cadastro_params["data_inicio_vigencia"] = c.data_inicio_vigencia.strftime("%Y-%m-%d")
            if c.data_fim_vigencia:
                cadastro_params["data_fim_vigencia"] = c.data_fim_vigencia.strftime("%Y-%m-%d")
            if c.arp_id:
                cadastro_params["arp_origem"] = c.arp_id

            contratos_api.append({
                "numero_contrato": c.numero_contrato,
                "arp_numero": c.arp.numero_arp if c.arp_id else "",
                "objeto": (c.arp.objeto[:150] if c.arp_id else ""),
                "contratado": c.contratado_nome,
                "vigencia_fim": c.data_fim_vigencia.strftime("%d/%m/%Y") if c.data_fim_vigencia else "",
                "valor_total": float(c.valor_total),
                "fonte": "compras.gov.br / PNCP (importar_contratos_arp)",
                "link_cadastrar": "/admin/contratos/contrato/add/?" + urlencode(cadastro_params),
            })

        return JsonResponse({"contratos": contratos, "contratos_api": contratos_api})


@method_decorator(login_required, name="dispatch")
class DescricaoAutocompleteJSON(View):
    """
    GET /pca/api/descricao-autocomplete.json?q=<texto>

    Autocomplete do campo Descricao no cadastro em grupo. Busca em duas
    fontes e retorna separadamente:

    - "catalogo": ItemCatalogo ativo (biblioteca institucional) — pre-
      preenche categoria, CATMAT/CATSER, unidade de fornecimento e
      classificacao de continuidade, mas nao tem preco.
    - "historico": ItemPCA ja cadastrados em exercicios anteriores (via
      contratacoes/demandas passadas) que casam com o texto — pre-
      preenche tambem quantidade e valor unitario da ultima vez que a
      unidade cadastrou algo parecido, servindo de referencia de preco.
    """

    def get(self, request):
        q = request.GET.get("q", "").strip()
        if len(q) < 2:
            return JsonResponse({"catalogo": [], "historico": []})

        catalogo_qs = (
            ItemCatalogo.objects
            .filter(ativo=True)
            .filter(
                Q(descricao_padrao__unaccent__icontains=q)
                | Q(codigo_catalogo__icontains=q)
                | Q(codigo_catmat_catser__icontains=q)
            )
            .order_by("descricao_padrao")[:8]
        )
        catalogo = [
            {
                "id": c.pk,
                "descricao": c.descricao_padrao,
                "categoria": c.categoria,
                "codigo_catmat_catser": c.codigo_catmat_catser,
                "unidade_fornecimento": c.unidade_medida_padrao,
                "classificacao_continuidade": c.classificacao,
                "base_normativa": c.base_normativa,
            }
            for c in catalogo_qs
        ]

        historico_qs = (
            ItemPCA.objects
            .filter(descricao__unaccent__icontains=q)
            .exclude(status="suspenso")
            .select_related("dfd__pca", "dfd__unidade")
            .order_by("-dfd__pca__exercicio", "-numero_item")[:8]
        )
        historico = [
            {
                "id": h.pk,
                "descricao": h.descricao,
                "categoria": h.categoria,
                "codigo_catmat_catser": h.codigo_catmat_catser,
                "unidade_fornecimento": h.unidade_fornecimento,
                "classificacao_continuidade": h.classificacao_continuidade,
                "valor_unitario_estimado": float(h.valor_unitario_estimado),
                "quantidade_estimada": float(h.quantidade_estimada),
                "exercicio": h.dfd.pca.exercicio,
                "unidade_sigla": h.dfd.unidade.sigla,
            }
            for h in historico_qs
        ]

        return JsonResponse({"catalogo": catalogo, "historico": historico})
