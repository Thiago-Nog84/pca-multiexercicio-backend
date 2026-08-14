from django.contrib import admin

from .models import Notificacao, NotificacaoLida, Orgao, Perfil, UnidadeRequisitante


@admin.register(UnidadeRequisitante)
class UnidadeRequisitanteAdmin(admin.ModelAdmin):
    search_fields = ("sigla", "nome")
    list_display = ("sigla", "nome")
    ordering = ("sigla",)


@admin.register(Notificacao)
class NotificacaoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tipo", "unidade_destino", "ativa", "criada_em", "total_leituras")
    list_filter = ("tipo", "ativa", "unidade_destino")
    search_fields = ("titulo", "mensagem")
    readonly_fields = ("criada_em",)
    ordering = ("-criada_em",)
    actions = ("inativar_notificacoes",)

    @admin.display(description="Leituras")
    def total_leituras(self, obj):
        return obj.leituras.count()

    def save_model(self, request, obj, form, change):
        if not change and obj.autor_id is None:
            obj.autor = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Inativar notificações selecionadas")
    def inativar_notificacoes(self, request, queryset):
        atualizadas = queryset.update(ativa=False)
        self.message_user(request, f"{atualizadas} notificação(ões) inativada(s).")


@admin.register(NotificacaoLida)
class NotificacaoLidaAdmin(admin.ModelAdmin):
    list_display = ("notificacao", "usuario", "lida_em")
    list_filter = ("lida_em",)
    search_fields = ("notificacao__titulo", "usuario__username")


admin.site.register(Orgao)
admin.site.register(Perfil)
