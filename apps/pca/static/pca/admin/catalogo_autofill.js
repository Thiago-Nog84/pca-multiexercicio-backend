/**
 * catalogo_autofill.js
 * Quando o usuário seleciona um ItemCatalogo via autocomplete no Admin do
 * ItemPCA, busca os dados do item e pré-preenche os campos do formulário.
 */
(function () {
  'use strict';

  const CLASSIFICACAO_LABELS = {
    continuo_fornecimento: 'Fornecimento contínuo',
    continuo_servico:      'Serviço contínuo',
    continuo_servico_mdo:  'Serviço contínuo c/ dedicação exclusiva de MO',
    eventual:              'Eventual / pontual',
  };

  function getEndpointBase() {
    // Admin URL: /admin/pca/itempca/catalogo-detalhe/<pk>/
    return '/admin/pca/itempca/catalogo-detalhe/';
  }

  function setField(id, value) {
    const el = document.getElementById(id);
    if (!el || !value) return;
    // Só preenche se o campo estiver vazio
    if (el.tagName === 'TEXTAREA' || el.type === 'text') {
      if (!el.value.trim()) el.value = value;
    } else if (el.tagName === 'SELECT') {
      // Para select, sempre preenche (é uma sugestão, não sobrescreve dado obrigatório)
      for (const opt of el.options) {
        if (opt.value === value) { el.value = value; break; }
      }
    }
  }

  function showHint(normativa, classificacao) {
    let hint = document.getElementById('catalogo-hint-box');
    const anchor = document.querySelector('.field-item_catalogo .help');
    const parent = document.querySelector('.field-item_catalogo');
    if (!parent) return;

    if (!hint) {
      hint = document.createElement('div');
      hint.id = 'catalogo-hint-box';
      parent.appendChild(hint);
    }

    const label = CLASSIFICACAO_LABELS[classificacao] || classificacao;
    hint.innerHTML =
      '<span class="catalogo-hint-tag">' + label + '</span>' +
      (normativa
        ? ' &nbsp;<span class="catalogo-hint-norm">' + normativa + '</span>'
        : '');
  }

  function clearHint() {
    const hint = document.getElementById('catalogo-hint-box');
    if (hint) hint.innerHTML = '';
  }

  function onCatalogoChange(selectEl) {
    const pk = selectEl.value;
    if (!pk) { clearHint(); return; }

    fetch(getEndpointBase() + pk + '/', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.id) return;

        setField('id_descricao',                 data.descricao_padrao);
        setField('id_categoria',                 data.categoria);
        setField('id_classificacao_continuidade', data.classificacao);
        setField('id_codigo_catmat_catser',       data.codigo_catmat_catser);
        setField('id_unidade_fornecimento',       data.unidade_medida_padrao);
        if (data.modalidade_sugerida) {
          setField('id_modalidade', data.modalidade_sugerida);
        }

        showHint(data.base_normativa, data.classificacao);
      })
      .catch(function (err) { console.error('[catalogo_autofill]', err); });
  }

  function init() {
    // O autocomplete do Django Admin renderiza o campo como um <select>
    // com id="id_item_catalogo". A seleção do usuário dispara "change".
    const sel = document.getElementById('id_item_catalogo');
    if (!sel) return;

    sel.addEventListener('change', function () {
      onCatalogoChange(this);
    });

    // Se já há um valor (edição de item existente), mostra o hint
    if (sel.value) onCatalogoChange(sel);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
