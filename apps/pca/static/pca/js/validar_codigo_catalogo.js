/*
 * Conferencia do codigo CATMAT/CATSER contra a base oficial do Governo Federal.
 *
 * Injeta um botao no admin do ItemCatalogo (ao lado do campo
 * codigo_catmat_catser) que consulta /pca/api/validar-codigo-catalogo.json
 * e mostra a descricao oficial do codigo.
 *
 * Contexto: para MATERIAIS o catalogo interno guarda o codigo PDM (padrao
 * descritivo, que agrupa varios itens CATMAT); para SERVICOS, o CATSER.
 * A API oficial nao busca por descricao livre — so por codigo.
 */
(function () {
  "use strict";

  function iniciar() {
    var alvo = document.getElementById("conferencia-catalogo-oficial");
    var campoCodigo = document.getElementById("id_codigo_catmat_catser");
    if (!alvo || !campoCodigo) return;

    var url = alvo.dataset.url;

    var botao = document.createElement("button");
    botao.type = "button";
    botao.className = "button";
    botao.textContent = "Conferir na base oficial";

    var saida = document.createElement("div");
    saida.style.marginTop = "8px";
    saida.style.fontSize = "12px";

    alvo.appendChild(botao);
    alvo.appendChild(saida);

    function pintar(cor, html) {
      saida.style.padding = "8px 10px";
      saida.style.borderLeft = "3px solid " + cor;
      saida.style.background = "#fafafa";
      saida.innerHTML = html;
    }

    botao.addEventListener("click", function () {
      var codigo = (campoCodigo.value || "").trim();
      if (!codigo) {
        pintar("#999", "Informe um código para conferir.");
        return;
      }

      // Categoria de servico -> valida como CATSER
      var campoCategoria = document.getElementById("id_categoria");
      // "software" fica de fora: licença de software costuma ter código CATMAT
      // (ex: PDM 16431 "SOFTWARE APLICATIVO"), então deixamos tentar os dois.
      var categoriasServico = [
        "servico", "servico_engenharia", "servico_terceirizado",
        "treinamento", "publicidade",
      ];
      var tipo = "";
      if (campoCategoria && categoriasServico.indexOf(campoCategoria.value) !== -1) {
        tipo = "CATSER";
      }

      botao.disabled = true;
      botao.textContent = "Consultando...";
      saida.innerHTML = "";

      var q = url + "?codigo=" + encodeURIComponent(codigo);
      if (tipo) q += "&tipo=" + tipo;

      fetch(q, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.encontrado === null) {
            pintar("#e0a800", "⚠ " + (d.erro || "API oficial indisponível."));
            return;
          }
          if (!d.encontrado) {
            pintar("#dc3545",
              "✗ <strong>Não encontrado</strong> na base oficial. " +
              (d.erro || "") +
              "<br><span style='color:#666'>Confira se o código contém apenas " +
              "números e corresponde ao PDM (materiais) ou CATSER (serviços).</span>");
            return;
          }

          var linhas = [
            "✓ <strong>" + (d.descricao || "(sem descrição)") + "</strong>",
            "<span style='color:#666'>Nível: " + d.nivel +
              " · Tipo: " + (d.tipo || "") + "</span>",
          ];
          if (d.classe) linhas.push("<span style='color:#666'>Classe: " + d.classe + "</span>");
          if (d.grupo) linhas.push("<span style='color:#666'>Grupo: " + d.grupo + "</span>");
          if (d.itens_no_pdm) {
            linhas.push("<span style='color:#666'>Este PDM agrupa " + d.itens_no_pdm +
                        " item(ns) CATMAT específico(s).</span>");
          }
          if (d.nivel === "item_catmat" && d.codigo_pdm) {
            linhas.push("<span style='color:#856404'>Atenção: este é um item " +
                        "específico. O PDM correspondente é <strong>" + d.codigo_pdm +
                        "</strong> (" + (d.nome_pdm || "") + ").</span>");
          }
          if (d.exemplos && d.exemplos.length) {
            var ex = d.exemplos.slice(0, 3).map(function (i) {
              return "<li style='margin:0'>" + i.codigo_item + " — " +
                     (i.descricao || "").slice(0, 70) + "</li>";
            }).join("");
            linhas.push("<span style='color:#666'>Exemplos:</span><ul style='margin:2px 0 0 16px'>" +
                        ex + "</ul>");
          }
          pintar("#198754", linhas.join("<br>"));
        })
        .catch(function (e) {
          pintar("#dc3545", "Erro ao consultar: " + e);
        })
        .finally(function () {
          botao.disabled = false;
          botao.textContent = "Conferir na base oficial";
        });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
