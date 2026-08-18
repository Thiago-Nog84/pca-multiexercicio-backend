"""Views Django Templates — Criação do DOD (Documento de Oficialização da Demanda).

Segue o mesmo padrão do apps/pca/views_cadastro.py (CadastroGrupoDemandaView):
View simples, extração manual de request.POST, transaction.atomic() e
full_clean() explícito — sem Django Forms/ModelForms, por consistência com
o resto do sistema.
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil, UnidadeRequisitante
from apps.pca.models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual

from .models import (
    UO_ITEM_PARA_DOD,
    DocumentoOficializacaoDemanda,
    EquipePlanejamentoTI,
    unidade_orcamentaria_dos_itens,
)

Usuario = get_user_model()

_ROTULO_UO = dict(DocumentoOficializacaoDemanda.UNIDADE_ORCAMENTARIA)


def _anotar_uo(itens):
    """
    Anota cada ItemPCA com a unidade orçamentária dele já traduzida para o
    vocabulário do DOD (`uo_dod` + `uo_dod_label`), para o template mostrar a
    fonte de recurso de cada item e o JS agrupar por ela.

    Anotação em cima da instância (não é campo do model): é só apresentação,
    não vale a pena um `annotate()` com Case/When só pra traduzir 3 códigos.
    """
    lista = list(itens)
    for item in lista:
        item.uo_dod = UO_ITEM_PARA_DOD.get(item.unidade_orcamentaria, "")
        item.uo_dod_label = _ROTULO_UO.get(item.uo_dod, "—")
    return lista


def _validar_uo_unica(itens_ids):
    """
    Um DOD = uma fonte de recurso. Decidido com Thiago em 2026-08-18: o
    modelo SEI tem UM campo de unidade orçamentária na seção 3, então juntar
    itens de fundos diferentes no mesmo processo produziria um documento que
    não fecha com o próprio dado.

    Isso não é raro por acidente: 7 das 11 unidades com itens aprovados no
    PCA 2026 têm demandas em mais de uma UO. Por isso a checagem é aqui no
    servidor (o JS da tela só antecipa o aviso) e o backlog do checklist já
    vem separado por fonte.

    Devolve `(codigo_uo, mensagem_de_erro)` — mensagem vazia quando está ok.
    """
    itens = list(
        ItemPCA.objects.filter(pk__in=itens_ids).only("pk", "codigo_pca", "unidade_orcamentaria")
    )
    codigo, encontrados = unidade_orcamentaria_dos_itens(itens)
    if len(encontrados) <= 1:
        return codigo, ""

    por_uo = []
    for uo in encontrados:
        codigos = sorted(
            i.codigo_pca or f"#{i.pk}"
            for i in itens
            if UO_ITEM_PARA_DOD.get(i.unidade_orcamentaria, "") == uo
        )
        por_uo.append(f"{_ROTULO_UO.get(uo, uo)}: {', '.join(codigos)}")
    return "", (
        "Um DOD só pode reunir itens de uma mesma unidade orçamentária, "
        "porque o documento declara uma única fonte de recurso. Os itens "
        "marcados estão divididos em " + str(len(encontrados)) + " fontes — "
        + " | ".join(por_uo)
        + ". Abra um DOD para cada fonte."
    )


def _unidades_do_usuario(user):
    """
    IDs de UnidadeRequisitante em que o usuário tem Perfil de acesso ativo.
    """
    return set(
        Perfil.objects.filter(usuario=user, ativo=True, unidade__isnull=False)
        .values_list("unidade_id", flat=True)
    )


def _unidades_permitidas(user):
    """
    Unidades que o usuário pode escolher para preencher um DOD: as suas
    (via Perfil ativo) — ou todas, se for superusuário.

    Decidido com Thiago em 2026-08-17: cada DOD é preenchido para UMA
    unidade requisitante (identificada logo no topo da tela) e só pode
    reunir itens dessa mesma unidade — reforça, no nível da tela, a mesma
    trava de permissão que já existia (ver `validar_itens_dod` e o histórico
    desta view).
    """
    qs = UnidadeRequisitante.objects.filter(ativo=True).order_by("sigla")
    if user.is_superuser:
        return qs
    return qs.filter(pk__in=_unidades_do_usuario(user))


def _itens_elegiveis(pca, unidade, excluir_dod=None):
    """
    Itens que podem entrar num DOD deste PCA e desta unidade: já aprovados
    (integral ou parcial no PCA) e ainda não vinculados a OUTRO DOD com
    status "aberto".

    Replica aqui, para não oferecer na tela algo que o signal
    `validar_itens_dod` (planejamento/models.py) recusaria ao salvar — mas a
    validação de verdade continua no signal, disparado no dod.itens.add().
    A restrição de unidade, por ser regra de permissão (depende de quem está
    pedindo, não do dado em si), é checada aqui e de novo em
    `DODCriarView.post`/`DODEditarView.post`, não no signal do model.

    `excluir_dod`: usado por `DODEditarView` — os itens já vinculados a ESTE
    DOD não podem ficar de fora da lista só porque o próprio DOD está
    "aberto" (a exclusão de "outro DOD aberto" não deve contar o DOD que
    está sendo editado).
    """
    if unidade is None:
        return ItemPCA.objects.none()
    qs = (
        ItemPCA.objects
        .filter(
            dfd__pca=pca,
            dfd__unidade=unidade,
            status_aprovacao__in=["aprovada_integral", "aprovada_parcial"],
        )
        .select_related("dfd", "dfd__unidade", "dfd__requisitante")
        .order_by("codigo_pca")
    )
    bloqueados = Q(documentos_oficializacao__status="aberto")
    if excluir_dod is not None:
        bloqueados &= ~Q(documentos_oficializacao=excluir_dod)
    return qs.exclude(bloqueados).distinct()


@method_decorator(login_required, name="dispatch")
class DODCriarView(View):
    """
    GET  /planejamento/dods/novo/?pca_id=&unidade_id=&itens=1,2,3  -> formulário
    POST /planejamento/dods/novo/                                   -> cria o DOD (+ equipe opcional)
    """

    template_name = "planejamento/dod_form.html"

    def get(self, request):
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca_id = request.GET.get("pca_id")
        pca = (todos_pcas.filter(pk=pca_id).first() if pca_id else None) or todos_pcas.first()

        unidades_disponiveis = _unidades_permitidas(request.user)
        unidade_id = request.GET.get("unidade_id")
        unidade = unidades_disponiveis.filter(pk=unidade_id).first() if unidade_id else None
        # Só 1 unidade possível: escolhe sozinho, sem precisar o usuário clicar.
        if unidade is None and unidades_disponiveis.count() == 1:
            unidade = unidades_disponiveis.first()

        itens_pre_selecionados = set()
        itens_param = request.GET.get("itens", "")
        if itens_param:
            itens_pre_selecionados = {int(i) for i in itens_param.split(",") if i.isdigit()}

        sem_unidade_vinculada = not request.user.is_superuser and not unidades_disponiveis.exists()

        itens_elegiveis = _anotar_uo(_itens_elegiveis(pca, unidade)) if pca else []
        # UO já vem decidida pelas demandas: só é mostrada, nunca digitada.
        uo_derivada, _ = unidade_orcamentaria_dos_itens(
            [i for i in itens_elegiveis if i.pk in itens_pre_selecionados]
        )

        # Demandas (DFDs) da unidade/PCA escolhidos — alimenta a busca textual
        # do campo Identificador (ver dod_form.html): em vez de digitar um
        # rótulo do zero, o usuário busca a demanda de origem e o campo (e os
        # itens dela) são preenchidos automaticamente. Serializado como lista
        # de dicts pra ir direto num `json_script` no template.
        demandas_unidade = []
        if pca and unidade:
            demandas_unidade = list(
                DocumentoFormalizacaoDemanda.objects.filter(pca=pca, unidade=unidade)
                .order_by("-criado_em")
                .values("pk", "numero_dfd", "numero_sei", "descricao_objeto")
            )

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "unidades_disponiveis": unidades_disponiveis,
            "unidade": unidade,
            "precisa_escolher_unidade": unidade is None and unidades_disponiveis.count() > 1,
            "itens_elegiveis": itens_elegiveis,
            "itens_pre_selecionados": itens_pre_selecionados,
            "unidade_orcamentaria_derivada": uo_derivada,
            "unidade_orcamentaria_labels": _ROTULO_UO,
            "demandas_unidade": demandas_unidade,
            "usuarios": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
            "unidade_orcamentaria_choices": DocumentoOficializacaoDemanda.UNIDADE_ORCAMENTARIA,
            "natureza_objeto_choices": DocumentoOficializacaoDemanda.NATUREZA_OBJETO,
            "grau_prioridade_choices": DocumentoOficializacaoDemanda.GRAU_PRIORIDADE,
            "natureza_ti": DocumentoOficializacaoDemanda.NATUREZA_TI,
            "sem_unidade_vinculada": sem_unidade_vinculada,
            "tem_detalhamento": False,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        pca_id = request.POST.get("pca_id")
        unidade_id = request.POST.get("unidade_id")
        identificador = request.POST.get("identificador", "").strip()
        itens_ids = [i for i in request.POST.getlist("itens") if i.isdigit()]

        if not pca_id:
            messages.error(request, "Selecione o PCA.")
            return redirect("planejamento:dod_novo")

        unidades_disponiveis = _unidades_permitidas(request.user)
        unidade = unidades_disponiveis.filter(pk=unidade_id).first() if unidade_id else None
        if not unidade:
            messages.error(
                request,
                "Selecione a unidade requisitante para a qual este DOD está sendo preenchido.",
            )
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}")

        if not identificador:
            messages.error(request, "Informe o identificador do DOD.")
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}&unidade_id={unidade.pk}")
        if not itens_ids:
            messages.error(request, "Selecione ao menos um item do PCA para compor o DOD.")
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}&unidade_id={unidade.pk}")

        # Trava de permissão por unidade — a tela já só OFERECE itens da
        # unidade escolhida (ver _itens_elegiveis), mas isso sozinho não
        # impede um POST forjado com o pk de um item de outra unidade. Cada
        # DOD é de UMA unidade só: todo item tem que ser dessa mesma
        # unidade declarada no topo da tela. Decidido com Thiago em
        # 2026-08-17.
        fora_da_unidade = ItemPCA.objects.filter(pk__in=itens_ids).exclude(dfd__unidade=unidade)
        if fora_da_unidade.exists():
            nomes = ", ".join(i.codigo_pca or f"#{i.pk}" for i in fora_da_unidade)
            messages.error(
                request,
                f"Todos os itens do DOD precisam ser da unidade {unidade.sigla}. "
                f"Fora dessa unidade: {nomes}.",
            )
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}&unidade_id={unidade.pk}")

        # A unidade orçamentária NÃO vem do POST: é derivada dos itens (cada
        # ItemPCA já a traz do DFD). Se os itens marcados misturarem fontes,
        # não há UO única possível e o DOD não é criado.
        unidade_orcamentaria, erro_uo = _validar_uo_unica(itens_ids)
        if erro_uo:
            messages.error(request, erro_uo)
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}&unidade_id={unidade.pk}")

        pca = get_object_or_404(PlanoContratacaoAnual, pk=pca_id)
        natureza_objeto = request.POST.get("natureza_objeto", "").strip()

        try:
            with transaction.atomic():
                dod = DocumentoOficializacaoDemanda(
                    pca=pca,
                    identificador=identificador,
                    numero_sei=request.POST.get("numero_sei", "").strip(),
                    objeto=request.POST.get("objeto", "").strip(),
                    unidade_orcamentaria=unidade_orcamentaria,
                    natureza_objeto=natureza_objeto,
                    contratacao_correlata=request.POST.get("contratacao_correlata") == "1",
                    contratacao_correlata_qual=request.POST.get("contratacao_correlata_qual", "").strip(),
                    grau_prioridade=request.POST.get("grau_prioridade", "").strip(),
                    previsao_inicio_execucao=request.POST.get("previsao_inicio_execucao") or None,
                    previsao_termino_execucao=request.POST.get("previsao_termino_execucao") or None,
                    objetivos_estrategicos=request.POST.get("objetivos_estrategicos", "").strip(),
                    alinhamento_pdtic=request.POST.get("alinhamento_pdtic", "").strip(),
                    necessidade_contratacao=request.POST.get("necessidade_contratacao", "").strip(),
                    motivacao_justificativa=request.POST.get("motivacao_justificativa", "").strip(),
                    objetivo_contratacao=request.POST.get("objetivo_contratacao", "").strip(),
                    meta_contratacao=request.POST.get("meta_contratacao", "").strip(),
                    indicador_resultado=request.POST.get("indicador_resultado", "").strip(),
                    responsavel_preenchimento=request.user if request.user.is_authenticated else None,
                )
                dod.full_clean()
                dod.save()

                # dod.itens.add() dispara o signal validar_itens_dod (m2m_changed,
                # pre_add) — é ali que moram as regras de negócio (aprovação no
                # PCA, exclusividade de DOD aberto, mesmo PCA do item). Se algum
                # item não passar, o signal levanta ValidationError e a transação
                # inteira é desfeita (nenhum DOD "quebrado" fica salvo).
                dod.itens.add(*itens_ids)

                equipe_preenchida = any(
                    request.POST.get(campo)
                    for campo in ("integrante_requisitante", "integrante_tecnico", "integrante_administrativo")
                )
                if equipe_preenchida or natureza_objeto == DocumentoOficializacaoDemanda.NATUREZA_TI:
                    equipe = EquipePlanejamentoTI(
                        dod=dod,
                        integrante_requisitante_id=request.POST.get("integrante_requisitante") or None,
                        integrante_tecnico_id=request.POST.get("integrante_tecnico") or None,
                        integrante_administrativo_id=request.POST.get("integrante_administrativo") or None,
                        lider=request.POST.get("lider", "requisitante"),
                        ato_designacao_sei=request.POST.get("ato_designacao_sei", "").strip(),
                    )
                    # EquipePlanejamentoTI.clean() é quem decide (via
                    # dod.natureza_objeto) se os 3 papéis distintos são
                    # obrigatórios aqui — regra condicional implementada em
                    # 2026-08-17 a pedido do Thiago.
                    equipe.full_clean()
                    equipe.save()

        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"DOD não cadastrado: {detalhe}")
            return redirect(f"/planejamento/dods/novo/?pca_id={pca_id}&unidade_id={unidade.pk}")

        messages.success(request, f"DOD \"{identificador}\" cadastrado com {len(itens_ids)} item(ns).")
        return redirect("planejamento:dod_detalhe", pk=dod.pk)


@method_decorator(login_required, name="dispatch")
class DODDetalheView(View):
    """
    GET /planejamento/dods/<pk>/ — ficha do DOD já cadastrado.

    Fecha o ciclo da tela de criação: até 2026-08-17 quem salvava um DOD caía
    direto no admin do Django, sem nenhuma tela do sistema que mostrasse o
    documento. Reúne aqui o que antes só dava para ver espalhado — dados do
    documento, itens vinculados, equipe de planejamento e o estado dos
    artefatos que dependem dele (ETP, Matriz de Risco, Termo de Referência).

    A unidade requisitante NÃO é campo do model: cada DOD é de uma unidade só
    (regra da tela de criação, ver `_unidades_permitidas`), então ela é
    derivada dos DFDs dos itens. Se algum caminho antigo tiver deixado itens
    de unidades diferentes, todas aparecem — melhor expor a inconsistência do
    que escondê-la mostrando só a primeira.
    """

    template_name = "planejamento/dod_detalhe.html"

    def get(self, request, pk):
        dod = get_object_or_404(
            DocumentoOficializacaoDemanda.objects.select_related(
                "pca",
                "responsavel_preenchimento",
                "equipe_planejamento_ti",
                "etp",
                "etp__matriz_risco",
                "etp__termo_referencia",
            ),
            pk=pk,
        )

        itens = list(
            dod.itens.select_related("dfd", "dfd__unidade").order_by("codigo_pca")
        )

        # getattr(..., None) funciona em OneToOne reverso porque o
        # RelatedObjectDoesNotExist do Django herda de AttributeError — mesmo
        # padrão já usado em views_checklist._montar_processos.
        etp = getattr(dod, "etp", None)
        equipe = getattr(dod, "equipe_planejamento_ti", None)

        unidades = sorted(
            {item.dfd.unidade for item in itens if item.dfd_id and item.dfd.unidade_id},
            key=lambda u: u.sigla,
        )
        dfds = sorted(
            {item.dfd for item in itens if item.dfd_id},
            key=lambda d: d.numero_dfd or "",
        )

        # Blocos de texto das seções 8-10 do modelo SEI 1465317, na ordem do
        # documento. Como lista de tuplas para o template só iterar e pular o
        # que estiver vazio — evita repetir o mesmo {% if %} sete vezes.
        campos_texto = [
            ("Objetivos estratégicos", dod.objetivos_estrategicos),
            ("Alinhamento ao PDTIC", dod.alinhamento_pdtic),
            ("Necessidade da contratação", dod.necessidade_contratacao),
            ("Motivação / justificativa", dod.motivacao_justificativa),
            ("Objetivo da contratação", dod.objetivo_contratacao),
            ("Meta a ser alcançada", dod.meta_contratacao),
            ("Indicador de resultado", dod.indicador_resultado),
        ]

        context = {
            "dod": dod,
            "itens": itens,
            "campos_texto": campos_texto,
            "tem_fundamentacao": any(texto for _, texto in campos_texto),
            "valor_total": sum(
                (item.valor_total_estimado or Decimal("0") for item in itens), Decimal("0")
            ),
            "unidades": unidades,
            "dfds": dfds,
            "equipe": equipe,
            "etp": etp,
            "matriz_risco": getattr(etp, "matriz_risco", None) if etp else None,
            "termo_referencia": getattr(etp, "termo_referencia", None) if etp else None,
            "qtd_parciais": sum(
                1 for item in itens if item.status_aprovacao == "aprovada_parcial"
            ),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class DODEditarView(View):
    """
    GET/POST /planejamento/dods/<pk>/editar/ — edita um DOD já cadastrado.

    Reaproveita o MESMO template de criação (dod_form.html) em "modo
    edição" (contexto tem `dod` preenchido) — evita duplicar um formulário
    de ~20 campos. Unidade e PCA ficam FIXOS, derivados dos itens já
    vinculados: trocar unidade no meio do caminho invalidaria os itens já
    escolhidos (cada DOD é de uma unidade só, mesma regra da criação).
    Todo o resto — identificação, itens vinculados, informações gerais,
    equipe de planejamento, alinhamento/fundamentação — continua editável.

    A busca de demandas (DFD) que alimenta o autocomplete do Identificador
    na criação não faz sentido aqui (o identificador já existe) — o
    template esconde essa caixa quando `dod` está no contexto.
    """

    template_name = "planejamento/dod_form.html"

    def get(self, request, pk):
        dod = get_object_or_404(
            DocumentoOficializacaoDemanda.objects.select_related("pca")
            .prefetch_related("itens__dfd__unidade"),
            pk=pk,
        )
        unidade = self._unidade_do_dod(dod)
        equipe = getattr(dod, "equipe_planejamento_ti", None)

        tem_detalhamento = any([
            dod.objetivos_estrategicos, dod.alinhamento_pdtic, dod.necessidade_contratacao,
            dod.motivacao_justificativa, dod.objetivo_contratacao, dod.meta_contratacao,
            dod.indicador_resultado,
        ])

        itens_elegiveis = _anotar_uo(
            _itens_elegiveis(dod.pca, unidade, excluir_dod=dod)
        ) if unidade else []
        itens_pre_selecionados = set(dod.itens.values_list("pk", flat=True))
        uo_derivada, _ = unidade_orcamentaria_dos_itens(
            [i for i in itens_elegiveis if i.pk in itens_pre_selecionados]
        )

        context = {
            "dod": dod,
            "equipe": equipe,
            "tem_detalhamento": tem_detalhamento,
            "pca": dod.pca,
            "todos_pcas": PlanoContratacaoAnual.objects.order_by("-exercicio"),
            "unidades_disponiveis": (
                UnidadeRequisitante.objects.filter(pk=unidade.pk) if unidade else UnidadeRequisitante.objects.none()
            ),
            "unidade": unidade,
            "precisa_escolher_unidade": False,
            "itens_elegiveis": itens_elegiveis,
            "itens_pre_selecionados": itens_pre_selecionados,
            "unidade_orcamentaria_derivada": uo_derivada or dod.unidade_orcamentaria,
            "unidade_orcamentaria_labels": _ROTULO_UO,
            "demandas_unidade": [],
            "usuarios": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
            "unidade_orcamentaria_choices": DocumentoOficializacaoDemanda.UNIDADE_ORCAMENTARIA,
            "natureza_objeto_choices": DocumentoOficializacaoDemanda.NATUREZA_OBJETO,
            "grau_prioridade_choices": DocumentoOficializacaoDemanda.GRAU_PRIORIDADE,
            "natureza_ti": DocumentoOficializacaoDemanda.NATUREZA_TI,
            "sem_unidade_vinculada": False,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        dod = get_object_or_404(DocumentoOficializacaoDemanda, pk=pk)
        unidade = self._unidade_do_dod(dod)
        itens_ids = [i for i in request.POST.getlist("itens") if i.isdigit()]

        identificador = request.POST.get("identificador", "").strip()
        if not identificador:
            messages.error(request, "Informe o identificador do DOD.")
            return redirect("planejamento:dod_editar", pk=dod.pk)
        if not itens_ids:
            messages.error(request, "Selecione ao menos um item do PCA para compor o DOD.")
            return redirect("planejamento:dod_editar", pk=dod.pk)

        # Mesma trava de permissão da criação: nenhum item fora da unidade
        # do DOD, mesmo que alguém force um pk pelo POST.
        fora_da_unidade = ItemPCA.objects.filter(pk__in=itens_ids).exclude(dfd__unidade=unidade)
        if fora_da_unidade.exists():
            nomes = ", ".join(i.codigo_pca or f"#{i.pk}" for i in fora_da_unidade)
            messages.error(
                request,
                f"Todos os itens do DOD precisam ser da unidade {unidade.sigla}. "
                f"Fora dessa unidade: {nomes}.",
            )
            return redirect("planejamento:dod_editar", pk=dod.pk)

        # Mesma derivação da criação: trocar os itens pode trocar a fonte de
        # recurso do DOD, e misturar fontes continua barrado na edição.
        unidade_orcamentaria, erro_uo = _validar_uo_unica(itens_ids)
        if erro_uo:
            messages.error(request, erro_uo)
            return redirect("planejamento:dod_editar", pk=dod.pk)

        natureza_objeto = request.POST.get("natureza_objeto", "").strip()

        try:
            with transaction.atomic():
                dod.identificador = identificador
                dod.numero_sei = request.POST.get("numero_sei", "").strip()
                dod.objeto = request.POST.get("objeto", "").strip()
                dod.unidade_orcamentaria = unidade_orcamentaria
                dod.natureza_objeto = natureza_objeto
                dod.contratacao_correlata = request.POST.get("contratacao_correlata") == "1"
                dod.contratacao_correlata_qual = request.POST.get("contratacao_correlata_qual", "").strip()
                dod.grau_prioridade = request.POST.get("grau_prioridade", "").strip()
                dod.previsao_inicio_execucao = request.POST.get("previsao_inicio_execucao") or None
                dod.previsao_termino_execucao = request.POST.get("previsao_termino_execucao") or None
                dod.objetivos_estrategicos = request.POST.get("objetivos_estrategicos", "").strip()
                dod.alinhamento_pdtic = request.POST.get("alinhamento_pdtic", "").strip()
                dod.necessidade_contratacao = request.POST.get("necessidade_contratacao", "").strip()
                dod.motivacao_justificativa = request.POST.get("motivacao_justificativa", "").strip()
                dod.objetivo_contratacao = request.POST.get("objetivo_contratacao", "").strip()
                dod.meta_contratacao = request.POST.get("meta_contratacao", "").strip()
                dod.indicador_resultado = request.POST.get("indicador_resultado", "").strip()
                dod.full_clean()
                dod.save()

                # Reconcilia a lista de itens em vez de recriar o M2M do zero:
                # remove() não passa pelo signal (não precisa — tirar item de
                # um DOD não quebra nenhuma regra), add() dispara
                # validar_itens_dod de novo para os que entraram agora.
                atuais = set(dod.itens.values_list("pk", flat=True))
                novos = {int(i) for i in itens_ids}
                a_remover = atuais - novos
                a_adicionar = novos - atuais
                if a_remover:
                    dod.itens.remove(*a_remover)
                if a_adicionar:
                    dod.itens.add(*a_adicionar)

                self._salvar_equipe(request, dod, natureza_objeto)

        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"DOD não salvo: {detalhe}")
            return redirect("planejamento:dod_editar", pk=dod.pk)

        messages.success(request, f"DOD \"{dod.identificador}\" atualizado.")
        return redirect("planejamento:dod_detalhe", pk=dod.pk)

    @staticmethod
    def _salvar_equipe(request, dod, natureza_objeto):
        equipe_preenchida = any(
            request.POST.get(campo)
            for campo in ("integrante_requisitante", "integrante_tecnico", "integrante_administrativo")
        )
        equipe = getattr(dod, "equipe_planejamento_ti", None)

        if not equipe_preenchida and natureza_objeto != DocumentoOficializacaoDemanda.NATUREZA_TI:
            # Campos todos vazios e a natureza não exige equipe: se havia
            # uma equipe de uma edição anterior, ela fica órfã de sentido —
            # remove em vez de deixar dado morto no banco.
            if equipe is not None:
                equipe.delete()
            return

        if equipe is None:
            equipe = EquipePlanejamentoTI(dod=dod)
        equipe.integrante_requisitante_id = request.POST.get("integrante_requisitante") or None
        equipe.integrante_tecnico_id = request.POST.get("integrante_tecnico") or None
        equipe.integrante_administrativo_id = request.POST.get("integrante_administrativo") or None
        equipe.lider = request.POST.get("lider", "requisitante")
        equipe.ato_designacao_sei = request.POST.get("ato_designacao_sei", "").strip()
        equipe.full_clean()
        equipe.save()

    @staticmethod
    def _unidade_do_dod(dod):
        item = next((i for i in dod.itens.all() if i.dfd_id and i.dfd.unidade_id), None)
        return item.dfd.unidade if item else None
