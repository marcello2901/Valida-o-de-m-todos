/* Qual seção da tela de resultado abre.
 *
 * As faixas abrem recolhidas: a tela é um índice do estudo, e quem chega nela
 * quer ver o estado de tudo antes de entrar numa parte. O preço disso é que
 * um link para dentro de uma seção fechada não leva a lugar nenhum — o
 * navegador rola até um elemento que não está desenhado —, e é isso que este
 * arquivo resolve.
 *
 * Dois casos:
 *
 *   1. Âncora na barra de endereço (#analise, #comparabilidade). Vem do link
 *      "marque o veredito abaixo da análise crítica" e do retorno de salvar um
 *      recorte. Chrome já abre o <details> nesse caso; Firefox e Safari não, e
 *      o usuário caía numa tela aparentemente sem nada.
 *
 *   2. Faixa em exame na regressão (?faixa_min=…). O formulário é GET e não
 *      leva âncora, então sem isto o usuário arrastava no gráfico e voltava
 *      para o topo da tela, com a seção fechada.
 *
 * Sem persistência de propósito: recolhido é o estado inicial toda vez, não o
 * que ficou da visita anterior.
 */
(function () {
  "use strict";

  /** Abre a seção que contém o elemento, e as seções acima dela. */
  function abrirAteAqui(elemento) {
    var atual = elemento;
    while (atual && atual !== document.body) {
      if (atual.tagName === "DETAILS") atual.open = true;
      atual = atual.parentElement;
    }
  }

  function alvoDaAncora() {
    var hash = window.location.hash;
    if (!hash || hash.length < 2) return null;
    try {
      return document.querySelector(hash);
    } catch (erro) {
      return null; // Âncora malformada na barra de endereço.
    }
  }

  function iniciar() {
    var alvo = alvoDaAncora();

    if (!alvo && window.location.search.indexOf("faixa_min=") !== -1) {
      alvo = document.querySelector("[data-selecao]");
    }

    if (!alvo) return;

    abrirAteAqui(alvo);
    // O <details> só ganha altura depois de aberto: rolar no mesmo quadro
    // levaria à posição que o elemento tinha enquanto estava fechado.
    window.requestAnimationFrame(function () {
      alvo.scrollIntoView({ block: "center" });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  // Clicar num link para dentro da própria página não recarrega nada: o
  // navegador só troca a âncora e rola. Sem escutar isso, o link do veredito
  // — que é âncora interna, o caso mais comum — rolava até uma seção fechada
  // e o usuário via a tela parar num lugar sem nada.
  window.addEventListener("hashchange", iniciar);
})();
