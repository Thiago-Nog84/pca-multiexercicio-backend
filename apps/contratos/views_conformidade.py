"""
Avaliação de conformidade documental dos contratos.

Duas telas:
  /contratos/conformidade/            — lista os contratos com o % de cada um
  /contratos/conformidade/<pk>/       — checklist do contrato, editável

Quem preenche: perfis "auditor" (CONINT), "apg" e "autoridade", além de
superusuário. Os demais visualizam. Observação: CONINT é uma unidade
requisitante, não um perfil — os usuários do controle interno devem ter o
perfil "auditor" para poder preencher.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil

from .models import Contrato
from .models_conformidade import ChecklistConformidade, ItemChecklist

PERFIS_CONFORMIDADE = ("auditor", "apg", "autoridade")


def _pode_avaliar(user):
    if user.is_superuser:
        return True
    return Perfil.objects.filter(
        usuario=user, perfil__in=PERFIS_CONFORMIDADE, ativo=True
    ).exists()


@method_decorator(login_required, name="dispatch")
class ConformidadeListaView(View):
    template_name = "contratos/conformidade_lista.html"

    def get(self, request):
        busca = (request.GET.get("q") or "").strip()
        status_filtro = request.GET.get("status", "")
        faixa_filtro = request.GET.get("faixa", "")

        contratos = (
            Contrato.objects
            .select_related("unidade_requisitante", "checklist")
            .prefetch_related("checklist__itens")
            .order_by("-data_assinatura")
        )
        if busca:
            contratos = contratos.filter(
                Q(numero_contrato__icontains=busca)
                | Q(objeto__icontains=busca)
                | Q(contratado_razao_social__icontains=busca)
                | Q(numero_sei__icontains=busca)
            )
        if status_filtro:
            contratos = contratos.filter(status=status_filtro)

        linhas = []
        soma_pct = 0
        contagem_faixa = {"success": 0, "warning": 0, "danger": 0}

        for contrato in contratos:
            checklist = getattr(contrato, "checklist", None)
            pct = checklist.percentual if checklist else 0
            faixa = checklist.faixa if checklist else "danger"
            soma_pct += pct
            contagem_faixa[faixa] += 1

            if faixa_filtro and faixa != faixa_filtro:
                continue

            linhas.append({
                "contrato": contrato,
                "checklist": checklist,
                "percentual": pct,
                "faixa": faixa,
                "marcados": checklist.qtd_marcados if checklist else 0,
                "total": (
                    checklist.total_itens if checklist
                    else len(ChecklistConformidade.TODOS_ITENS)
                ),
            })

        total_contratos = len(contratos)
        context = {
            "linhas": linhas,
            "busca": busca,
            "status_filtro": status_filtro,
            "faixa_filtro": faixa_filtro,
            "status_opcoes": Contrato.STATUS,
            "total_contratos": total_contratos,
            "media_pct": round(soma_pct / total_contratos) if total_contratos else 0,
            "contagem_faixa": contagem_faixa,
            "pode_avaliar": _pode_avaliar(request.user),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ConformidadeDetalheView(View):
    template_name = "contratos/conformidade_detalhe.html"

    def get(self, request, pk):
        contrato = get_object_or_404(
            Contrato.objects.select_related("unidade_requisitante"), pk=pk
        )
        checklist = getattr(contrato, "checklist", None)

        context = {
            "contrato": contrato,
            "checklist": checklist,
            "fases": checklist.itens_por_fase() if checklist else [
                {
                    "chave": chave,
                    "rotulo": rotulo,
                    "linhas": [
                        {"chave": c, "rotulo": r, "registro": None, "marcado": False}
                        for c, r in itens
                    ],
                    "marcados": 0,
                    "total": len(itens),
                }
                for chave, rotulo, itens in ChecklistConformidade.FASES
            ],
            "percentual": checklist.percentual if checklist else 0,
            "faixa": checklist.faixa if checklist else "danger",
            "total_itens": len(ChecklistConformidade.TODOS_ITENS),
            "pode_avaliar": _pode_avaliar(request.user),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        contrato = get_object_or_404(Contrato, pk=pk)
        destino = redirect("contratos:conformidade_detalhe", pk=contrato.pk)

        if not _pode_avaliar(request.user):
            messages.error(
                request,
                "Você não tem permissão para avaliar a conformidade "
                "(requer perfil Auditor, APG ou Autoridade Competente).",
            )
            return destino

        marcadas = set(request.POST.getlist("itens"))
        # Ignora qualquer chave que não exista no catálogo (POST forjado).
        marcadas &= ChecklistConformidade.CHAVES_VALIDAS
        agora = timezone.now()

        with transaction.atomic():
            checklist, _ = ChecklistConformidade.objects.get_or_create(contrato=contrato)
            checklist.observacoes = (request.POST.get("observacoes") or "").strip()
            checklist.atualizado_por = request.user
            checklist.save()

            existentes = {i.chave: i for i in checklist.itens.all()}

            for chave, _rotulo in ChecklistConformidade.TODOS_ITENS:
                deve_marcar = chave in marcadas
                observacao = (request.POST.get(f"obs__{chave}") or "").strip()[:300]
                registro = existentes.get(chave)

                if registro is None:
                    # Só materializa o item se houver algo a guardar.
                    if deve_marcar or observacao:
                        ItemChecklist.objects.create(
                            checklist=checklist,
                            chave=chave,
                            marcado=deve_marcar,
                            observacao=observacao,
                            marcado_por=request.user if deve_marcar else None,
                            marcado_em=agora if deve_marcar else None,
                        )
                    continue

                mudou_marcacao = registro.marcado != deve_marcar
                registro.observacao = observacao
                registro.marcado = deve_marcar
                if mudou_marcacao:
                    # Preserva quem marcou; ao desmarcar, limpa a autoria.
                    registro.marcado_por = request.user if deve_marcar else None
                    registro.marcado_em = agora if deve_marcar else None
                registro.save()

        checklist.refresh_from_db()
        messages.success(
            request,
            f"Conformidade do contrato {contrato.numero_contrato} atualizada — "
            f"{checklist.percentual}% ({checklist.qtd_marcados} de {checklist.total_itens}).",
        )
        return destino
