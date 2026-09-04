/* Colar um bloco de células vindo do Excel nas grades de lançamento.
 *
 * É o único JavaScript do programa, e existe porque não há como fazer isto sem
 * ele: o navegador só entrega o conteúdo da área de transferência num evento de
 * colar. Tudo o mais continua funcionando com o JavaScript desligado — a grade
 * é um formulário comum, e este arquivo apenas preenche campos que já existem.
 *
 * O bloco é colado a partir da célula onde está o cursor, para baixo e para a
 * direita, como numa planilha. O que não couber na grade não é descartado em
 * silêncio: o aviso diz quantos valores sobraram.
 */
(function () {
  "use strict";

  var SEPARADOR_LINHA = /\r\n|\n|\r/;

  function ehNumero(texto) {
    return /^[+-]?[\d.,\s]+$/.test(texto.trim()) && /\d/.test(texto);
  }

  /** Converte o texto da área de transferência numa matriz de células. */
  function lerBloco(texto) {
    var linhas = texto.replace(/\s+$/, "").split(SEPARADOR_LINHA);
    return linhas
      .filter(function (linha) {
        return linha.trim() !== "";
      })
      .map(function (linha) {
        return linha.split("\t").map(function (celula) {
          return celula.trim();
        });
      });
  }

  /* Na grade de réplicas a planilha costuma ter uma coluna de rótulo à
   * esquerda ("Replicata 1"). Ela é descartada só quando NENHUMA das suas
   * células é número — assim uma coluna de valores nunca some por engano. */
  function descartarColunaDeRotulo(bloco) {
    if (!bloco.length || bloco[0].length < 2) return bloco;
    var primeiraTemNumero = bloco.some(function (linha) {
      return ehNumero(linha[0] || "");
    });
    if (primeiraTemNumero) return bloco;
    return bloco.map(function (linha) {
      return linha.slice(1);
    });
  }

  function campo(grade, linha, coluna) {
    return grade.querySelector(
      'input[data-linha="' + linha + '"][data-coluna="' + coluna + '"]'
    );
  }

  function avisar(grade, texto) {
    // A faixa de aviso fica acima do formulário, fora do container da grade —
    // procurar só dentro dele achava nada, e a colagem acontecia em silêncio.
    var caixa = document.querySelector("[data-aviso-colagem]");
    if (!caixa) return;
    caixa.textContent = texto;
    caixa.hidden = false;
  }

  function colar(evento) {
    var destino = evento.target;
    if (!destino.matches || !destino.matches("input[data-linha]")) return;

    var grade = destino.closest("[data-grade]");
    if (!grade) return;

    var texto = (evento.clipboardData || window.clipboardData).getData("text");
    if (!texto || texto.indexOf("\t") === -1 && !SEPARADOR_LINHA.test(texto)) {
      return; // Uma célula só: deixa o navegador colar do jeito normal.
    }

    var bloco = lerBloco(texto);
    if (!bloco.length) return;

    if (grade.dataset.grade === "replicas") {
      bloco = descartarColunaDeRotulo(bloco);
    }

    evento.preventDefault();

    var linhaInicial = parseInt(destino.dataset.linha, 10);
    var colunaInicial = parseInt(destino.dataset.coluna, 10);
    var preenchidos = 0;
    var sobraram = 0;

    bloco.forEach(function (celulas, deslocamentoLinha) {
      celulas.forEach(function (valor, deslocamentoColuna) {
        var alvo = campo(
          grade,
          linhaInicial + deslocamentoLinha,
          colunaInicial + deslocamentoColuna
        );
        if (!alvo || alvo.disabled) {
          if (valor !== "") sobraram += 1;
          return;
        }
        alvo.value = valor;
        preenchidos += 1;
      });
    });

    var recado = preenchidos + " valor(es) colado(s) a partir da linha " + linhaInicial + ".";
    if (sobraram) {
      recado +=
        " " + sobraram + " não couberam na grade — acrescente linhas e cole o resto.";
    }
    recado += " Confira antes de salvar.";
    avisar(grade, recado);
  }

  document.addEventListener("paste", colar, true);
})();
