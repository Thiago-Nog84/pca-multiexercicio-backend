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
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil, UnidadeRequisitante
from apps.pca.models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual

from .models import DocumentoOficializacaoDemanda, EquipePlanejamentoTI

Usuario = get_user_model()


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


def _itens_elegiveis(pca, unidade):
    """
    Itens que podem entrar num DOD NOVO deste PCA e desta unidade: já
    aprovados (integral ou parcial no PCA) e ainda não vinculados a outro
    DOD com status "aberto".

    Replica aqui, para não oferecer na tela algo que o signal
    `validar_itens_dod` (planejamento/models.py) recusaria ao salvar — mas a
    validação de verdade continua no signal, disparado no dod.itens.add().
    A restrição de unidade, por ser regra de permissão (depende de quem está
    pedindo, não do dado em si), é checada aqui e de novo em
    `DODCriarView.post`, não no signal do model.
    """
    if unidade is None:
        return ItemPCA.objects.none()
    return (
        ItemPCA.objects
        .filter(
            dfd__pca=pca,
            dfd__unidade=unidade,
            status_aprovacao__in=["aprovada_integral", "aprovada_parcial"],
        )
        .exclude(documentos_oficializacao__status="aberto")
        .select_related("dfd", "dfd__unidade", "dfd__requisitante")
        .order_by("codigo_pca")
    )


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
            "itens_elegiveis": _itens_elegiveis(pca, unidade) if pca else ItemPCA.objects.none(),
            "itens_pre_selecionados": itens_pre_selecionados,
            "demandas_unidade": demandas_unidade,
            "usuarios": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
            "unidade_orcamentaria_choices": DocumentoOficializacaoDemanda.UNIDADE_ORCAMENTARIA,
            "natureza_objeto_choices": DocumentoOficializacaoDemanda.NATUREZA_OBJETO,
            "grau_prioridade_choices": DocumentoOficializacaoDemanda.GRAU_PRIORIDADE,
            "natureza_ti": DocumentoOficializacaoDemanda.NATUREZA_TI,
            "sem_unidade_vinculada": sem_unidade_vinculada,
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

        pca = get_object_or_404(PlanoContratacaoAnual, pk=pca_id)
        natureza_objeto = request.POST.get("natureza_objeto", "").strip()

        try:
            with transaction.atomic():
                dod = DocumentoOficializacaoDemanda(
                    pca=pca,
                    identificador=identificador,
                    numero_sei=request.POST.get("numero_sei", "").strip(),
                    objeto=request.POST.get("objeto", "").strip(),
                    unidade_orcamentaria=request.POST.get("unidade_orcamentaria", "").strip(),
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
