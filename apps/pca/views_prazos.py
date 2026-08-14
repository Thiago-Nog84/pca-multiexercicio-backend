"""
Views de Controle de Prazos e Riscos e Pendencias -- Modulo PCA
"""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil

from .models import HistoricoDataItemPCA, ItemPCA, PlanoContratacaoAnual

# Perfis que podem remarcar datas — mesmo criterio do painel de Fases do PCA.
PERFIS_GESTORES = ("apg", "autoridade")

# Campos editaveis pela tela, na ordem em que aparecem na tabela.
CAMPOS_DATA = [chave for chave, _ in HistoricoDataItemPCA.CAMPOS]

MESES_PT = [
    (1, "Janeiro"), (2, "Fevereiro"), (3, "Marco"), (4, "Abril"),
    (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
    (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
]


def _pca_default(todos_pcas):
    """Retorna o PCA do ano corrente; se nao existir, o mais recente."""
    ano = datetime.date.today().year
    return todos_pcas.filter(exercicio=ano).first() or todos_pcas.first()


def _pode_editar_datas(user):
    """Só APG/Autoridade (ou superuser) remarcam prazos."""
    if user.is_superuser:
        return True
    return Perfil.objects.filter(
        usuario=user, perfil__in=PERFIS_GESTORES, ativo=True
    ).exists()


def _unidades_do_usuario(user):
    """
    Siglas das unidades em que o usuario tem Perfil ativo.

    Retorna None quando o usuario NAO deve ser restringido (superuser ou
    perfil gestor) — assim a view distingue "ve tudo" de "nao tem unidade
    nenhuma" (lista vazia, que nao deve ver nada).
    """
    if user.is_superuser or _pode_editar_datas(user):
        return None
    siglas = (
        Perfil.objects.filter(usuario=user, ativo=True, unidade__isnull=False)
        .values_list("unidade__sigla", flat=True)
        .distinct()
    )
    return list(siglas)


def _classificar_prazo(item, hoje):
    """Retorna (classe_css, label) baseado na data_pretendida_conclusao."""
    if item.status == "concluido" or item.data_conclusao_efetiva:
        return "success", "Concluido"
    if not item.data_pretendida_conclusao:
        return "secondary", "Sem prazo"
    delta = (item.data_pretendida_conclusao - hoje).days
    if delta < 0:
        return "danger", "Vencido"
    if delta <= 30:
        return "warning", "Proximo"
    return "success", "No prazo"


# ---------------------------------------------------------------------------
# Controle de Prazos
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class ControlePrazosView(View):
    template_name = "pca/prazos.html"

    def get(self, request):
        hoje = datetime.date.today()

        exercicio_param = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        if exercicio_param:
            pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio_param).first()
        else:
            pca = _pca_default(todos_pcas)

        status_prazo_filtro = request.GET.get("status_prazo", "")
        setor_filtro = request.GET.get("setor", "")
        busca = request.GET.get("q", "").strip()
        mes_filtro = request.GET.get("mes", "")

        itens_qs = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status="suspenso")
            .select_related("dfd", "dfd__unidade", "dfd__pca")
            .order_by("data_pretendida_conclusao", "dfd__unidade__sigla", "codigo_pca")
        ) if pca else ItemPCA.objects.none()

        # Requisitante enxerga apenas as demandas da(s) propria(s) unidade(s).
        unidades_permitidas = _unidades_do_usuario(request.user)
        if unidades_permitidas is not None:
            itens_qs = itens_qs.filter(dfd__unidade__sigla__in=unidades_permitidas)

        if setor_filtro:
            itens_qs = itens_qs.filter(dfd__unidade__sigla=setor_filtro)
        if busca:
            itens_qs = itens_qs.filter(
                Q(codigo_pca__icontains=busca) | Q(descricao__icontains=busca)
            )
        if mes_filtro.isdigit() and 1 <= int(mes_filtro) <= 12:
            itens_qs = itens_qs.filter(data_pretendida_conclusao__month=int(mes_filtro))

        itens = list(itens_qs)

        # Ultima alteracao de data por item — 1 query para a pagina inteira.
        ultima_alteracao = {}
        for registro in (
            HistoricoDataItemPCA.objects
            .filter(item__in=itens)
            .select_related("usuario")
            .order_by("item_id", "-criado_em")
        ):
            ultima_alteracao.setdefault(registro.item_id, registro)

        # Classificar cada item
        itens_anotados = []
        contadores = {"vencido": 0, "proximo": 0, "no_prazo": 0, "concluido": 0, "sem_prazo": 0}

        for item in itens:
            cls, label = _classificar_prazo(item, hoje)
            chave = label.lower().replace(" ", "_")
            if chave in contadores:
                contadores[chave] += 1

            if status_prazo_filtro and label.lower() != status_prazo_filtro.lower():
                continue

            dias_restantes = None
            if item.data_pretendida_conclusao and item.status != "concluido":
                dias_restantes = (item.data_pretendida_conclusao - hoje).days

            itens_anotados.append({
                "item": item,
                "cls": cls,
                "label": label,
                "dias_restantes": dias_restantes,
                "ultima_alteracao": ultima_alteracao.get(item.pk),
            })

        setores_qs = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status="suspenso")
        ) if pca else ItemPCA.objects.none()
        if unidades_permitidas is not None:
            setores_qs = setores_qs.filter(dfd__unidade__sigla__in=unidades_permitidas)
        setores = (
            setores_qs
            .values_list("dfd__unidade__sigla", flat=True)
            .distinct()
            .order_by("dfd__unidade__sigla")
        )

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "itens": itens_anotados,
            "contadores": contadores,
            "hoje": hoje,
            "status_prazo_filtro": status_prazo_filtro,
            "setor_filtro": setor_filtro,
            "busca": busca,
            "setores": list(setores),
            "mes_filtro": mes_filtro,
            "meses": MESES_PT,
            "pode_editar": _pode_editar_datas(request.user),
            "restrito_a_unidade": unidades_permitidas is not None,
            "campos_data": HistoricoDataItemPCA.CAMPOS,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        """Remarca uma data de um ItemPCA e registra a alteracao no historico."""
        destino = f"{request.path}?{request.POST.get('querystring', '')}"

        if not _pode_editar_datas(request.user):
            messages.error(
                request,
                "Você não tem permissão para alterar prazos "
                "(requer perfil APG ou Autoridade Competente).",
            )
            return redirect(destino)

        campo = request.POST.get("campo")
        if campo not in CAMPOS_DATA:
            messages.error(request, "Campo de data inválido.")
            return redirect(destino)

        item = ItemPCA.objects.filter(pk=request.POST.get("item_id")).first()
        if item is None:
            messages.error(request, "Demanda não encontrada.")
            return redirect(destino)

        valor_bruto = (request.POST.get("valor") or "").strip()
        if valor_bruto:
            try:
                nova_data = datetime.date.fromisoformat(valor_bruto)
            except ValueError:
                messages.error(request, "Data inválida.")
                return redirect(destino)
        else:
            nova_data = None  # permite limpar a data

        data_atual = getattr(item, campo)
        if data_atual == nova_data:
            return redirect(destino)

        justificativa = (request.POST.get("justificativa") or "").strip()
        rotulo = dict(HistoricoDataItemPCA.CAMPOS)[campo]

        # Adiar a conclusao prevista muda o indicador de atraso — exige motivo.
        adiamento = (
            campo == "data_pretendida_conclusao"
            and data_atual is not None
            and nova_data is not None
            and nova_data > data_atual
        )
        if adiamento and not justificativa:
            messages.error(
                request,
                "Justificativa é obrigatória para adiar a conclusão prevista.",
            )
            return redirect(destino)

        with transaction.atomic():
            HistoricoDataItemPCA.objects.create(
                item=item,
                campo=campo,
                de_data=data_atual,
                para_data=nova_data,
                usuario=request.user,
                justificativa=justificativa,
            )
            setattr(item, campo, nova_data)
            item.save(update_fields=[campo])

        messages.success(
            request,
            f"{rotulo} da demanda {item.codigo_pca} atualizada para "
            f"{nova_data.strftime('%d/%m/%Y') if nova_data else '—'}.",
        )
        return redirect(destino)


# ---------------------------------------------------------------------------
# Riscos e Pendencias
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RiscosView(View):
    template_name = "pca/riscos.html"

    def get(self, request):
        hoje = datetime.date.today()
        limite_atencao = hoje + datetime.timedelta(days=120)

        exercicio_param = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        if exercicio_param:
            pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio_param).first()
        else:
            pca = _pca_default(todos_pcas)

        base_qs = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status__in=["suspenso", "concluido"])
            .filter(data_pretendida_conclusao__isnull=False)
            .select_related("dfd", "dfd__unidade")
        ) if pca else ItemPCA.objects.none()

        # Atrasados: data ja passou
        atrasados_qs = (
            base_qs
            .filter(data_pretendida_conclusao__lt=hoje)
            .order_by("data_pretendida_conclusao")
        )

        # Atencao: vence nos proximos 120 dias
        atencao_qs = (
            base_qs
            .filter(
                data_pretendida_conclusao__gte=hoje,
                data_pretendida_conclusao__lte=limite_atencao,
            )
            .order_by("data_pretendida_conclusao")
        )

        def enriquecer(qs):
            resultado = []
            for item in qs:
                dias = (item.data_pretendida_conclusao - hoje).days
                resultado.append({"item": item, "dias": dias})
            return resultado

        atrasados = enriquecer(atrasados_qs)
        atencao = enriquecer(atencao_qs)

        valor_retido = atrasados_qs.aggregate(
            s=Sum("valor_total_estimado")
        )["s"] or 0

        # Por setor -- atrasados
        por_setor_atrasados = (
            atrasados_qs
            .values("dfd__unidade__sigla")
            .annotate(qtd=Count("id"), valor=Sum("valor_total_estimado"))
            .order_by("-qtd")
        )

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "hoje": hoje,
            "atrasados": atrasados,
            "atencao": atencao,
            "qtd_atrasados": len(atrasados),
            "qtd_atencao": len(atencao),
            "valor_retido": valor_retido,
            "por_setor_atrasados": list(por_setor_atrasados),
        }
        return render(request, self.template_name, context)
