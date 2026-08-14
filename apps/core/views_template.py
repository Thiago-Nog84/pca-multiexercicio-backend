"""
Central de notificações in-app.

Lista os avisos visíveis ao usuário (gerais + dirigidos às unidades em que
ele tem Perfil ativo) e permite marcá-los como lidos. A "exclusão" de uma
notificação é feita pelo admin (ativa=False) — aqui o usuário só marca
leitura, preservando a trilha.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import Notificacao, NotificacaoLida


@method_decorator(login_required, name="dispatch")
class NotificacoesView(View):
    template_name = "core/notificacoes.html"

    def get(self, request):
        filtro = request.GET.get("filtro", "nao_lidas")

        lidas_ids = set(
            NotificacaoLida.objects.filter(usuario=request.user).values_list(
                "notificacao_id", flat=True
            )
        )
        visiveis = Notificacao.visiveis_para(request.user).select_related(
            "unidade_destino", "autor"
        )

        if filtro == "nao_lidas":
            visiveis = visiveis.exclude(id__in=lidas_ids)

        itens = [
            {"obj": n, "lida": n.id in lidas_ids}
            for n in visiveis
        ]

        return render(
            request,
            self.template_name,
            {
                "itens": itens,
                "filtro": filtro,
                "qtd_nao_lidas": len(
                    [i for i in itens if not i["lida"]]
                ) if filtro == "nao_lidas" else None,
            },
        )

    def post(self, request):
        acao = request.POST.get("acao")
        destino = f"{request.path}?filtro={request.POST.get('filtro', 'nao_lidas')}"

        if acao == "marcar_todas":
            lidas_ids = NotificacaoLida.objects.filter(usuario=request.user).values_list(
                "notificacao_id", flat=True
            )
            pendentes = Notificacao.visiveis_para(request.user).exclude(id__in=lidas_ids)
            NotificacaoLida.objects.bulk_create(
                [NotificacaoLida(notificacao=n, usuario=request.user) for n in pendentes],
                ignore_conflicts=True,
            )
            messages.success(request, "Todas as notificações foram marcadas como lidas.")
            return redirect(destino)

        if acao == "marcar_lida":
            notificacao_id = request.POST.get("notificacao_id")
            # Só marca o que o usuário realmente pode ver.
            alvo = Notificacao.visiveis_para(request.user).filter(pk=notificacao_id).first()
            if alvo is None:
                messages.error(request, "Notificação não encontrada.")
                return redirect(destino)
            NotificacaoLida.objects.get_or_create(notificacao=alvo, usuario=request.user)
            return redirect(destino)

        messages.error(request, "Ação inválida.")
        return redirect(destino)
