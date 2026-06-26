"""
Views de Controle de Prazos e Riscos e Pendencias -- Modulo PCA
"""
import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ItemPCA, PlanoContratacaoAnual


def _pca_default(todos_pcas):
    """Retorna o PCA do ano corrente; se nao existir, o mais recente."""
    ano = datetime.date.today().year
    return todos_pcas.filter(exercicio=ano).first() or todos_pcas.first()


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

        itens_qs = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status="suspenso")
            .select_related("dfd", "dfd__unidade", "dfd__pca")
            .order_by("data_pretendida_conclusao", "dfd__unidade__sigla", "codigo_pca")
        ) if pca else ItemPCA.objects.none()

        if setor_filtro:
            itens_qs = itens_qs.filter(dfd__unidade__sigla=setor_filtro)
        if busca:
            itens_qs = itens_qs.filter(
                Q(codigo_pca__icontains=busca) | Q(descricao__icontains=busca)
            )

        # Classificar cada item
        itens_anotados = []
        contadores = {"vencido": 0, "proximo": 0, "no_prazo": 0, "concluido": 0, "sem_prazo": 0}

        for item in itens_qs:
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
            })

        setores = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status="suspenso")
            .values_list("dfd__unidade__sigla", flat=True)
            .distinct()
            .order_by("dfd__unidade__sigla")
        ) if pca else []

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
        }
        return render(request, self.template_name, context)


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
