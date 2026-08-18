"""
Teste ponta a ponta da edicao do DOD (read-only ao final: o DOD de teste eh
apagado). Cobre: form de edicao pre-preenchido, trocar identificador, tirar
um item e adicionar outro, definir equipe de planejamento, e a validacao de
equipe (3 papeis distintos) continuar valendo tambem na edicao.

Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/testar_dod_editar.py')"
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from apps.pca.models import ItemPCA, PlanoContratacaoAnual
from apps.planejamento.models import DocumentoOficializacaoDemanda

pca = PlanoContratacaoAnual.objects.get(exercicio=2026)
usuario = User.objects.get(id=1)

# precisa de uma unidade com pelo menos 3 itens elegiveis (2 pra criar, 1
# reserva pra entrar na edicao no lugar do que vai ser removido)
candidatos = {}
for item in (
    ItemPCA.objects.filter(dfd__pca=pca, status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
    .exclude(documentos_oficializacao__status="aberto")
    .select_related("dfd__unidade")
):
    candidatos.setdefault(item.dfd.unidade_id, []).append(item)
unidade_id, itens_disponiveis = max(candidatos.items(), key=lambda kv: len(kv[1]))
assert len(itens_disponiveis) >= 3, "nao achei unidade com 3+ itens elegiveis pro teste"
item_a, item_b, item_c = itens_disponiveis[:3]
unidade = item_a.dfd.unidade
print(f"unidade: {unidade.sigla} | itens: {item_a.codigo_pca}, {item_b.codigo_pca} (sai), {item_c.codigo_pca} (entra)")

client = Client()
client.force_login(usuario)

resp = client.post("/planejamento/dods/novo/", {
    "pca_id": pca.pk,
    "unidade_id": unidade.pk,
    "identificador": "TESTE editar DOD — apagar",
    "numero_sei": "19.21.0001.0000002/2026-22",
    "natureza_objeto": "fornecimento_nao_continuado",
    "itens": [str(item_a.pk), str(item_b.pk)],
})
assert resp.status_code == 302, (resp.status_code, resp.content[:500])
dod = DocumentoOficializacaoDemanda.objects.order_by("-pk").first()
print(f"DOD criado: #{dod.pk} com itens {[i.codigo_pca for i in dod.itens.all()]}")

try:
    # ---- GET do form de edicao: precisa vir pre-preenchido -----------
    form_html = client.get(f"/planejamento/dods/{dod.pk}/editar/").content.decode()
    assert "Editar DOD" in form_html
    assert 'value="TESTE editar DOD — apagar"' in form_html, "identificador nao veio pre-preenchido"
    assert 'value="19.21.0001.0000002/2026-22"' in form_html, "numero_sei nao veio pre-preenchido"
    # os 2 itens do DOD marcados + o 3o disponivel na lista, mas desmarcado
    assert f'value="{item_a.pk}"' in form_html and f'value="{item_b.pk}"' in form_html
    assert f'value="{item_c.pk}"' in form_html, "item elegivel de fora do DOD nao apareceu na lista"
    print("OK: form de edicao vem pre-preenchido (identificador, SEI, itens)")

    # ---- POST: troca identificador, tira item_b, poe item_c, define equipe
    resp = client.post(f"/planejamento/dods/{dod.pk}/editar/", {
        "identificador": "TESTE editar DOD (editado) — apagar",
        "numero_sei": "19.21.0001.0000002/2026-22",
        "natureza_objeto": "fornecimento_nao_continuado",
        "itens": [str(item_a.pk), str(item_c.pk)],
        "integrante_requisitante": str(usuario.pk),
        "lider": "requisitante",
    })
    assert resp.status_code == 302, (resp.status_code, resp.content[:800].decode(errors="replace"))
    assert resp.headers["Location"] == f"/planejamento/dods/{dod.pk}/", resp.headers["Location"]

    dod.refresh_from_db()
    itens_atuais = {i.pk for i in dod.itens.all()}
    assert dod.identificador == "TESTE editar DOD (editado) — apagar", dod.identificador
    assert itens_atuais == {item_a.pk, item_c.pk}, itens_atuais
    equipe = getattr(dod, "equipe_planejamento_ti", None)
    assert equipe is not None and equipe.integrante_requisitante_id == usuario.pk
    print(f"OK: edicao salvou identificador novo, trocou item_b por item_c, e criou a equipe")

    # item_b voltou pro backlog (nao esta mais em nenhum DOD aberto)
    item_b.refresh_from_db()
    assert not item_b.documentos_oficializacao.filter(status="aberto").exists()
    print("OK: item removido volta a ficar disponivel (nao preso a nenhum DOD aberto)")

    detalhe_html = client.get(f"/planejamento/dods/{dod.pk}/").content.decode()
    assert "TESTE editar DOD (editado)" in detalhe_html
    assert item_c.codigo_pca in detalhe_html
    assert item_b.codigo_pca not in detalhe_html
    print("OK: dod_detalhe reflete a edicao (identificador, item novo, item removido sumiu)")

    # ---- validacao de equipe continua valendo na edicao ---------------
    # muda pra natureza TI sem preencher os 3 papeis -> tem que barrar, sem
    # quebrar nada que ja estava salvo (transaction.atomic reverte tudo)
    resp_invalido = client.post(f"/planejamento/dods/{dod.pk}/editar/", {
        "identificador": "NAO DEVERIA SALVAR",
        "natureza_objeto": "solucao_ti",
        "itens": [str(item_a.pk), str(item_c.pk)],
        "integrante_requisitante": str(usuario.pk),
        "lider": "requisitante",
    })
    assert resp_invalido.status_code == 302
    assert resp_invalido.headers["Location"] == f"/planejamento/dods/{dod.pk}/editar/"
    dod.refresh_from_db()
    assert dod.identificador == "TESTE editar DOD (editado) — apagar", (
        f"a validacao de equipe falhou mas o resto foi salvo mesmo assim: {dod.identificador!r}"
    )
    print("OK: equipe incompleta em natureza TI barra a edicao inteira (atomic reverte tudo)")

    print("\nTUDO OK: edicao do DOD funciona ponta a ponta.")
finally:
    pk = dod.pk
    dod.delete()
    print(f"DOD #{pk} apagado. DODs restantes: {DocumentoOficializacaoDemanda.objects.count()}")
