"""
Modulo de Relatorios -- PCA MPPI
Formatos: CSV (download) e HTML imprimivel (Ctrl+P -> PDF)
"""
import csv
import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import UnidadeRequisitante
from .models import DocumentoFormalizacaoDemanda, ItemPCA, OrcamentoPlanejado, PlanoContratacaoAnual


def _pca_default(todos_pcas):
    ano = datetime.date.today().year
    return todos_pcas.filter(exercicio=ano).first() or todos_pcas.first()


# ---------------------------------------------------------------------------
# Landing page de relatorios
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelatoriosView(View):
    template_name = "pca/relatorios.html"

    def get(self, request):
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        exercicio = request.GET.get("exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)
        setores = UnidadeRequisitante.objects.order_by("sigla")

        # Repassa filtros como query string para os links dos botoes
        filtros = {k: v for k, v in request.GET.items() if k in ("setor", "uo", "tipo", "modalidade", "status") and v}
        filtros_qs = "".join(f"&{k}={v}" for k, v in filtros.items())

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "setores": setores,
            "filtros_qs": filtros_qs,
        }
        return render(request, self.template_name, context)


# ---------------------------------------------------------------------------
# Helpers CSV
# ---------------------------------------------------------------------------

class _EchoBuffer:
    def write(self, value):
        return value


def _csv_response(filename):
    resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------------------------------------------------------------------------
# 1. Base Completa -- todos os itens
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelBaseCompletaView(View):

    def get(self, request):
        formato = request.GET.get("formato", "csv")
        exercicio = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        itens = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .select_related("dfd", "dfd__unidade", "dfd__pca")
            .order_by("dfd__unidade__sigla", "status", "codigo_pca")
        ) if pca else ItemPCA.objects.none()

        if formato == "csv":
            resp = _csv_response(f"pca_{pca.exercicio if pca else 'sem'}_base_completa.csv")
            w = csv.writer(resp)
            w.writerow([
                "Codigo PCA", "Setor", "UO", "Categoria", "Classificacao",
                "Descricao", "Qtd", "Unid. Forn.", "Valor Unit.", "Valor Total",
                "Tipo", "Modalidade", "Normativo", "SRP", "Status",
                "Conclusao Prevista", "Envio PGEA", "Fin. Licitacao", "Conclusao Efetiva",
                "Valor Empenhado", "Lote PCA", "Numero DFD", "Numero SEI",
            ])
            for i in itens:
                w.writerow([
                    i.codigo_pca,
                    i.dfd.unidade.sigla,
                    i.get_unidade_orcamentaria_display(),
                    i.get_categoria_display(),
                    i.get_classificacao_continuidade_display(),
                    i.descricao,
                    i.quantidade_estimada,
                    i.unidade_fornecimento,
                    i.valor_unitario_estimado,
                    i.valor_total_estimado,
                    i.get_tipo_demanda_display(),
                    i.get_modalidade_display(),
                    i.get_normativo_display(),
                    "Sim" if i.is_srp else "Nao",
                    i.get_status_display(),
                    i.data_pretendida_conclusao or "",
                    i.data_envio_pgea or "",
                    i.data_finalizacao_licitacao or "",
                    i.data_conclusao_efetiva or "",
                    i.valor_empenhado,
                    i.numero_lote_pca or "",
                    i.dfd.numero_dfd,
                    i.dfd.numero_sei or "",
                ])
            return resp

        # HTML imprimivel
        return render(request, "pca/rel_base_completa.html", {
            "pca": pca, "itens": itens, "hoje": datetime.date.today(),
            "total_valor": itens.aggregate(s=Sum("valor_total_estimado"))["s"] or 0,
            "total_empenhado": itens.aggregate(s=Sum("valor_empenhado"))["s"] or 0,
        })


# ---------------------------------------------------------------------------
# 2. Orcamento Setorial
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelOrcamentoSetorialView(View):

    def get(self, request):
        formato = request.GET.get("formato", "csv")
        exercicio = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        orcamentos = []
        if pca:
            for orc in OrcamentoPlanejado.objects.filter(pca=pca).select_related("unidade").order_by("unidade__sigla"):
                comprometido = orc.valor_comprometido()
                orcamentos.append({
                    "sigla": orc.unidade.sigla,
                    "nome": orc.unidade.nome,
                    "pgj": orc.valor_pgj,
                    "fmmp": orc.valor_fmmp,
                    "fepdc": orc.valor_fepdc,
                    "total": orc.valor_total,
                    "comprometido": comprometido,
                    "saldo": orc.valor_total - comprometido,
                    "pct": orc.percentual_comprometido(),
                    "trava": orc.trava_ativa,
                })

        if formato == "csv":
            resp = _csv_response(f"pca_{pca.exercicio if pca else 'sem'}_orcamento_setorial.csv")
            w = csv.writer(resp)
            w.writerow(["Setor", "Nome", "Teto PGJ", "Teto FMMP", "Teto FEPDC",
                        "Total Aprovado", "Comprometido", "Saldo", "% Utilizado", "Trava"])
            for r in orcamentos:
                w.writerow([
                    r["sigla"], r["nome"], r["pgj"], r["fmmp"], r["fepdc"],
                    r["total"], r["comprometido"], r["saldo"], f"{r['pct']}%",
                    "Sim" if r["trava"] else "Nao",
                ])
            return resp

        return render(request, "pca/rel_orcamento_setorial.html", {
            "pca": pca, "orcamentos": orcamentos, "hoje": datetime.date.today(),
            "total_aprovado": sum(r["total"] for r in orcamentos),
            "total_comprometido": sum(r["comprometido"] for r in orcamentos),
        })


# ---------------------------------------------------------------------------
# 3. Prazos Criticos
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelPrazosCriticosView(View):

    def get(self, request):
        formato = request.GET.get("formato", "csv")
        exercicio = request.GET.get("exercicio")
        hoje = datetime.date.today()
        limite = hoje + datetime.timedelta(days=120)
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        itens = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status__in=["suspenso", "concluido"])
            .filter(
                Q(data_pretendida_conclusao__lt=hoje) |
                Q(data_pretendida_conclusao__lte=limite)
            )
            .select_related("dfd", "dfd__unidade")
            .order_by("data_pretendida_conclusao")
        ) if pca else ItemPCA.objects.none()

        def status_prazo(item):
            if not item.data_pretendida_conclusao:
                return "Sem prazo"
            d = (item.data_pretendida_conclusao - hoje).days
            if d < 0:
                return f"VENCIDO ({d}d)"
            if d <= 30:
                return f"Critico (+{d}d)"
            return f"Atencao (+{d}d)"

        if formato == "csv":
            resp = _csv_response(f"pca_{pca.exercicio if pca else 'sem'}_prazos_criticos.csv")
            w = csv.writer(resp)
            w.writerow(["Codigo PCA", "Setor", "UO", "Descricao", "Valor Total",
                        "Conclusao Prevista", "Status Prazo", "Status Demanda"])
            for i in itens:
                w.writerow([
                    i.codigo_pca, i.dfd.unidade.sigla,
                    i.get_unidade_orcamentaria_display(),
                    i.descricao[:120], i.valor_total_estimado,
                    i.data_pretendida_conclusao or "",
                    status_prazo(i), i.get_status_display(),
                ])
            return resp

        rows = [{"item": i, "status_prazo": status_prazo(i),
                 "dias": (i.data_pretendida_conclusao - hoje).days if i.data_pretendida_conclusao else None}
                for i in itens]
        return render(request, "pca/rel_prazos_criticos.html", {
            "pca": pca, "rows": rows, "hoje": hoje,
            "qtd_vencidos": sum(1 for r in rows if r["dias"] is not None and r["dias"] < 0),
            "qtd_criticos": sum(1 for r in rows if r["dias"] is not None and 0 <= r["dias"] <= 30),
        })


# ---------------------------------------------------------------------------
# 4. Demandas Suspensas
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelDemandasSuspensasView(View):

    def get(self, request):
        formato = request.GET.get("formato", "csv")
        exercicio = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        itens = (
            ItemPCA.objects
            .filter(dfd__pca=pca, status="suspenso")
            .select_related("dfd", "dfd__unidade", "item_pai")
            .order_by("dfd__unidade__sigla", "codigo_pca")
        ) if pca else ItemPCA.objects.none()

        if formato == "csv":
            resp = _csv_response(f"pca_{pca.exercicio if pca else 'sem'}_suspensas.csv")
            w = csv.writer(resp)
            w.writerow(["Codigo PCA", "Setor", "UO", "Descricao", "Valor Total",
                        "Tipo", "Modalidade", "Codigo Pai", "Observacoes"])
            for i in itens:
                w.writerow([
                    i.codigo_pca, i.dfd.unidade.sigla,
                    i.get_unidade_orcamentaria_display(),
                    i.descricao[:120], i.valor_total_estimado,
                    i.get_tipo_demanda_display(), i.get_modalidade_display(),
                    i.item_pai.codigo_pca if i.item_pai else "",
                    i.observacoes[:200] if i.observacoes else "",
                ])
            return resp

        return render(request, "pca/rel_suspensas.html", {
            "pca": pca, "itens": itens, "hoje": datetime.date.today(),
            "valor_retido": itens.aggregate(s=Sum("valor_total_estimado"))["s"] or 0,
        })


# ---------------------------------------------------------------------------
# 5. Resumo por Modalidade
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RelModalidadeView(View):

    def get(self, request):
        formato = request.GET.get("formato", "csv")
        exercicio = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio).first() if exercicio else _pca_default(todos_pcas)

        from django.db.models import Count
        rows = (
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .exclude(status="suspenso")
            .values("modalidade", "unidade_orcamentaria")
            .annotate(qtd=Count("id"), valor=Sum("valor_total_estimado"))
            .order_by("modalidade", "unidade_orcamentaria")
        ) if pca else []

        if formato == "csv":
            resp = _csv_response(f"pca_{pca.exercicio if pca else 'sem'}_por_modalidade.csv")
            w = csv.writer(resp)
            w.writerow(["Modalidade", "UO", "Qtd Itens", "Valor Total"])
            for r in rows:
                item_tmp = ItemPCA()
                item_tmp.modalidade = r["modalidade"]
                item_tmp.unidade_orcamentaria = r["unidade_orcamentaria"]
                w.writerow([
                    item_tmp.get_modalidade_display(),
                    item_tmp.get_unidade_orcamentaria_display(),
                    r["qtd"], r["valor"],
                ])
            return resp

        return render(request, "pca/rel_modalidade.html", {
            "pca": pca, "rows": list(rows), "hoje": datetime.date.today(),
        })
