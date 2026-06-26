import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import UnidadeRequisitante
from .models import ItemPCA, PlanoContratacaoAnual


def _pca_default(todos_pcas):
    ano = datetime.date.today().year
    return todos_pcas.filter(exercicio=ano).first() or todos_pcas.first()


@method_decorator(login_required, name="dispatch")
class DemandasSuspensasView(View):
    template_name = "pca/suspensas.html"

    def get(self, request):
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        exercicio = request.GET.get("exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        # Filtros
        setor = request.GET.get("setor", "")
        uo = request.GET.get("uo", "")
        tipo = request.GET.get("tipo", "")
        q = request.GET.get("q", "").strip()

        qs = ItemPCA.objects.filter(dfd__pca=pca, status="suspenso").select_related(
            "dfd", "dfd__unidade", "item_pai"
        ) if pca else ItemPCA.objects.none()

        if setor:
            qs = qs.filter(dfd__unidade__sigla=setor)
        if uo:
            qs = qs.filter(unidade_orcamentaria=uo)
        if tipo:
            qs = qs.filter(tipo_suspensao=tipo)
        if q:
            qs = qs.filter(
                Q(descricao__icontains=q) | Q(codigo_pca__icontains=q)
            )

        qs = qs.order_by("dfd__unidade__sigla", "tipo_suspensao", "codigo_pca")

        # KPIs
        agg = qs.aggregate(
            valor_retido=Sum("valor_total_estimado"),
            qtd_total=Count("id"),
        )
        qtd_total_tipo = qs.filter(tipo_suspensao="total").count()
        qtd_parcial_tipo = qs.filter(tipo_suspensao="parcial").count()

        # Por setor
        por_setor = (
            qs.values("dfd__unidade__sigla")
            .annotate(qtd=Count("id"), valor=Sum("valor_total_estimado"))
            .order_by("-valor")
        )

        setores = UnidadeRequisitante.objects.order_by("sigla")

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "itens": qs,
            "valor_retido": agg["valor_retido"] or 0,
            "qtd_total": agg["qtd_total"] or 0,
            "qtd_total_tipo": qtd_total_tipo,
            "qtd_parcial_tipo": qtd_parcial_tipo,
            "por_setor": por_setor,
            "setores": setores,
            "filtros": {"setor": setor, "uo": uo, "tipo": tipo, "q": q},
            "hoje": datetime.date.today(),
        }
        return render(request, self.template_name, context)
