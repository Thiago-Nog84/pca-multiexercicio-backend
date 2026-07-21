"""
Exportação em PDF do relatório de demandas do PCA.

O relatório respeita RIGOROSAMENTE os filtros aplicados na tela
(`/pca/demandas/`) — reaproveita `filtrar_demandas()`, a mesma função que
alimenta a listagem, para que o documento não possa divergir do que o
usuário vê.

Agrupa por unidade requisitante, com subtotais por unidade e total geral,
cabeçalho institucional do MPPI e numeração de páginas.

Motor: xhtml2pdf (Python puro). WeasyPrint exigiria o runtime GTK
instalado no sistema, o que não é viável no Windows dos usuários.
"""

import datetime
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views import View

from .models import ItemPCA, PlanoContratacaoAnual
from .views_template import _resolver_pca, filtrar_demandas


def _rotulo(choices, valor):
    """Traduz o valor bruto de um filtro para o label legível."""
    for chave, label in choices:
        if chave == valor:
            return label
    return valor


@method_decorator(login_required, name="dispatch")
class ExportarDemandasPDFView(View):
    """GET /pca/demandas/exportar.pdf?<mesmos filtros da tela>"""

    template_name = "pca/relatorio_demandas_pdf.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)
        itens_qs, filtros = filtrar_demandas(request, pca)

        # Agrupamento por unidade requisitante, com subtotais.
        # Itens sem DFD/unidade caem em "Sem unidade" para não sumirem do relatorio.
        grupos = {}
        for item in itens_qs:
            unidade = getattr(item.dfd, "unidade", None)
            chave = unidade.sigla if unidade else "Sem unidade"
            grupo = grupos.setdefault(
                chave,
                {"unidade": unidade, "sigla": chave, "itens": [], "total": 0, "qtd": 0},
            )
            grupo["itens"].append(item)
            grupo["total"] += item.valor_total_estimado or 0
            grupo["qtd"] += 1

        grupos_ordenados = [grupos[k] for k in sorted(grupos)]

        total_geral = itens_qs.aggregate(t=Sum("valor_total_estimado"))["t"] or 0

        # Descricao textual dos filtros ativos — impressa no cabecalho para
        # que o leitor do PDF saiba que recorte esta vendo.
        filtros_ativos = []
        if filtros["q"]:
            filtros_ativos.append(f'Busca: "{filtros["q"]}"')
        if filtros["status"]:
            filtros_ativos.append(f'Status: {_rotulo(ItemPCA.STATUS, filtros["status"])}')
        if filtros["aprovacao"]:
            filtros_ativos.append(
                f'Situação: {_rotulo(ItemPCA.STATUS_APROVACAO, filtros["aprovacao"])}'
            )
        if filtros["categoria"]:
            filtros_ativos.append(
                f'Categoria: {_rotulo(ItemPCA.CATEGORIAS, filtros["categoria"])}'
            )
        if filtros["modalidade"]:
            filtros_ativos.append(
                f'Modalidade: {_rotulo(ItemPCA.MODALIDADE, filtros["modalidade"])}'
            )
        if filtros["unidade"]:
            from apps.core.models import UnidadeRequisitante

            u = UnidadeRequisitante.objects.filter(pk=filtros["unidade"]).first()
            if u:
                filtros_ativos.append(f"Unidade: {u.sigla}")

        context = {
            "pca": pca,
            "grupos": grupos_ordenados,
            "total_geral": total_geral,
            "total_itens": itens_qs.count(),
            "filtros_ativos": filtros_ativos,
            "gerado_em": datetime.datetime.now(),
            "gerado_por": request.user.get_full_name() or request.user.get_username(),
        }

        # ?preview=1 renderiza como HTML — util para ajustar o layout sem
        # precisar abrir o PDF a cada mudanca.
        if request.GET.get("preview"):
            return render(request, self.template_name, context)

        html = render_to_string(self.template_name, context, request=request)

        from xhtml2pdf import pisa

        buffer = BytesIO()
        status = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
        if status.err:
            return HttpResponse(
                "Não foi possível gerar o PDF. Tente novamente ou use ?preview=1 "
                "para visualizar o relatório em HTML.",
                status=500,
            )

        exercicio = pca.exercicio if pca else "geral"
        nome = f"demandas_pca_{exercicio}_{datetime.date.today():%Y%m%d}.pdf"

        resposta = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return resposta
