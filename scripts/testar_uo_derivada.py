"""
Teste ponta a ponta da unidade orcamentaria DERIVADA dos itens do DOD.

Regra (Thiago, 2026-08-18): a UO nao e digitada no DOD - vem do que ja esta
cadastrado em cada demanda (ItemPCA.unidade_orcamentaria, do DFD de origem).
E um DOD so pode reunir itens de UMA fonte de recurso, porque o documento
declara uma unica UO na secao 3.

Rodar com:
  .venv\\Scripts\\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/testar_uo_derivada.py')"
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

from apps.pca.models import ItemPCA
from apps.planejamento.models import (
    UO_ITEM_PARA_DOD,
    DocumentoOficializacaoDemanda,
    unidade_orcamentaria_dos_itens,
)

# O Client de teste fora do test runner nao ganha "testserver" em ALLOWED_HOSTS.
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

Usuario = get_user_model()
ROTULOS = dict(DocumentoOficializacaoDemanda.UNIDADE_ORCAMENTARIA)


def elegiveis(unidade, pca):
    return list(
        ItemPCA.objects
        .filter(dfd__pca=pca, dfd__unidade=unidade,
                status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
        .exclude(documentos_oficializacao__status="aberto")
        .order_by("codigo_pca")
    )


# --- Acha uma unidade que tenha itens de DUAS UOs diferentes ---------------
alvo = None
for item in (ItemPCA.objects
             .filter(status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
             .select_related("dfd__unidade", "dfd__pca")):
    if not item.dfd_id or not item.dfd.unidade_id:
        continue
    itens = elegiveis(item.dfd.unidade, item.dfd.pca)
    por_uo = {}
    for i in itens:
        por_uo.setdefault(UO_ITEM_PARA_DOD.get(i.unidade_orcamentaria, ""), []).append(i)
    por_uo.pop("", None)
    if len(por_uo) >= 2:
        alvo = (item.dfd.unidade, item.dfd.pca, por_uo)
        break

assert alvo, "Nenhuma unidade com itens de UOs diferentes - teste nao aplicavel."
unidade, pca, por_uo = alvo
uo_a, uo_b = sorted(por_uo)[:2]
item_a1 = por_uo[uo_a][0]
item_a2 = por_uo[uo_a][1] if len(por_uo[uo_a]) > 1 else None
item_b1 = por_uo[uo_b][0]
print(f"unidade: {unidade.sigla} | {uo_a}: {item_a1.codigo_pca} | {uo_b}: {item_b1.codigo_pca}")

# --- Teste unitario do helper ---------------------------------------------
assert unidade_orcamentaria_dos_itens([]) == ("", [])
assert unidade_orcamentaria_dos_itens([item_a1])[0] == uo_a
codigo, encontrados = unidade_orcamentaria_dos_itens([item_a1, item_b1])
assert codigo == "" and sorted(encontrados) == sorted([uo_a, uo_b]), (codigo, encontrados)
print("OK: helper deriva UO unica e devolve vazio + lista quando ha mistura")

client = Client()
client.force_login(Usuario.objects.get(id=1))
criados = []

try:
    # --- 1) Tela de criacao mostra a UO de cada item -----------------------
    html = client.get(
        f"/planejamento/dods/novo/?pca_id={pca.pk}&unidade_id={unidade.pk}"
    ).content.decode()
    assert 'id="uoDerivada"' in html, "campo derivado de UO nao esta na tela"
    assert 'name="unidade_orcamentaria"' not in html, (
        "a UO nao pode mais ser um campo digitavel/postavel"
    )
    assert f'data-uo="{uo_a}"' in html and f'data-uo="{uo_b}"' in html, (
        "os itens precisam expor a propria UO pro JS agrupar"
    )
    print("OK: form nao tem campo de UO digitavel e expoe a UO de cada item")

    # --- 2) Criar com itens de UMA UO: grava sozinho -----------------------
    payload_ok = {
        "pca_id": pca.pk,
        "unidade_id": unidade.pk,
        "identificador": "TESTE UO derivada - apagar",
        "itens": [str(item_a1.pk)] + ([str(item_a2.pk)] if item_a2 else []),
    }
    r = client.post("/planejamento/dods/novo/", payload_ok, follow=False)
    assert r.status_code == 302 and "/editar/" not in r["Location"], r.status_code
    dod = DocumentoOficializacaoDemanda.objects.get(identificador=payload_ok["identificador"])
    criados.append(dod)
    assert dod.unidade_orcamentaria == uo_a, (
        f"UO deveria vir dos itens ({uo_a}), veio {dod.unidade_orcamentaria!r}"
    )
    print(f"OK: DOD #{dod.pk} gravou UO={dod.unidade_orcamentaria} derivada dos itens, sem digitacao")

    # --- 3) Criar misturando fontes: bloqueado ----------------------------
    antes = DocumentoOficializacaoDemanda.objects.count()
    r = client.post("/planejamento/dods/novo/", {
        "pca_id": pca.pk,
        "unidade_id": unidade.pk,
        "identificador": "TESTE UO misturada - NAO deve existir",
        "itens": [str(item_a1.pk), str(item_b1.pk)],
    }, follow=True)
    corpo = r.content.decode()
    assert DocumentoOficializacaoDemanda.objects.count() == antes, "DOD com UOs misturadas foi criado!"
    assert "uma mesma unidade orcamentaria" in corpo or "unidade or" in corpo, "faltou a mensagem de erro"
    assert item_a1.codigo_pca in corpo and item_b1.codigo_pca in corpo, (
        "a mensagem precisa dizer QUAIS itens estao em cada fonte"
    )
    print("OK: criacao com fontes misturadas e barrada e a msg lista os itens por fonte")

    # --- 4) Editar trocando a fonte: UO acompanha -------------------------
    r = client.post(f"/planejamento/dods/{dod.pk}/editar/", {
        "identificador": dod.identificador,
        "itens": [str(item_b1.pk)],
    }, follow=False)
    assert r.status_code == 302 and "/editar/" not in r["Location"], r["Location"]
    dod.refresh_from_db()
    assert dod.unidade_orcamentaria == uo_b, (
        f"trocar o item deveria trocar a UO para {uo_b}, ficou {dod.unidade_orcamentaria!r}"
    )
    print(f"OK: edicao trocou os itens e a UO acompanhou ({uo_a} -> {uo_b})")

    # --- 5) Editar misturando fontes: bloqueado, sem efeito colateral -----
    r = client.post(f"/planejamento/dods/{dod.pk}/editar/", {
        "identificador": "NAO DEVE SALVAR",
        "itens": [str(item_a1.pk), str(item_b1.pk)],
    }, follow=False)
    assert r.status_code == 302 and "/editar/" in r["Location"], r["Location"]
    dod.refresh_from_db()
    assert dod.identificador != "NAO DEVE SALVAR", "o identificador vazou numa edicao barrada"
    assert dod.unidade_orcamentaria == uo_b
    assert set(dod.itens.values_list("pk", flat=True)) == {item_b1.pk}
    print("OK: edicao com fontes misturadas e barrada antes de tocar em qualquer campo")

    # --- 6) Backlog do checklist ja vem separado por fonte ----------------
    html = client.get(f"/planejamento/checklist/?pca_id={pca.pk}").content.decode()
    linhas = [l for l in html.splitlines() if 'title="' in l and "Fundo" in l or "Procuradoria" in l]
    assert 'Iniciar DOD' in html
    # a mesma sigla deve aparecer mais de uma vez quando a unidade tem 2 fontes
    ocorrencias = html.count(f"unidade_id={unidade.pk}&itens=")
    assert ocorrencias >= 2, (
        f"backlog deveria oferecer um 'Iniciar DOD' por fonte da {unidade.sigla}; achei {ocorrencias}"
    )
    print(f"OK: checklist oferece {ocorrencias} atalhos 'Iniciar DOD' para a {unidade.sigla} (um por fonte)")

    print("\nTUDO OK: unidade orcamentaria vem das demandas e nao mistura fontes.")

finally:
    for d in criados:
        pk = d.pk
        d.delete()
        print(f"DOD #{pk} apagado.")
    print("DODs restantes:", DocumentoOficializacaoDemanda.objects.count())
