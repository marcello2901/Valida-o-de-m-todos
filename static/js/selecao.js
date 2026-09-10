/* Selecionar uma faixa de concentração no gráfico de regressão.
 *
 * Este arquivo NÃO calcula estatística nenhuma. Ele arrasta uma faixa sobre o
 * gráfico, converte os dois limites de pixel para valor e recarrega a tela com
 * eles na barra de endereço. Quem refaz a regressão é o motor, no servidor,
 * pelas mesmas funções que calculam o estudo inteiro.
 *
 * A alternativa — recalcular a reta aqui — daria uma resposta instantânea e
 * uma segunda implementação de regressão dentro do programa. Num sistema que
 * emite documento assinado, a implementação que acabaria impressa seria a de
 * dentro do navegador, e ninguém saberia disso.
 *
 * Por que faixa e não retângulo: a seleção é só no eixo X, então todas as
 * amostras daquela concentração entram. Com um retângulo daria para contornar
 * um ponto discordante mantendo os vizinhos, que é descartar amostra sem
 * justificativa com outro nome.
 */
(function () {
  "use strict";

  var ARRASTO_MINIMO = 8; // px — abaixo disso é clique, não seleção.

  function numero(elemento, atributo) {
    return parseFloat(elemento.getAttribute(atributo));
  }

  /** Converte a posição do ponteiro em valor no eixo X do gráfico. */
  function valorEm(svg, clientX) {
    var caixa = svg.getBoundingClientRect();
    var largura = numero(svg, "data-largura");
    var xNoDesenho = ((clientX - caixa.left) / caixa.width) * largura;

    var inicio = numero(svg, "data-pixel-inicio");
    var fim = numero(svg, "data-pixel-fim");
    var minimo = numero(svg, "data-x-minimo");
    var maximo = numero(svg, "data-x-maximo");

    var proporcao = (xNoDesenho - inicio) / (fim - inicio);
    proporcao = Math.min(Math.max(proporcao, 0), 1);
    return minimo + proporcao * (maximo - minimo);
  }

  function pixelEm(svg, clientX) {
    var caixa = svg.getBoundingClientRect();
    return ((clientX - caixa.left) / caixa.width) * numero(svg, "data-largura");
  }

  function preparar(svg) {
    if (svg.dataset.preparado === "sim") return;
    svg.dataset.preparado = "sim";
    svg.style.cursor = "crosshair";
    svg.style.touchAction = "none";

    var faixa = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    faixa.setAttribute("fill", "#2a78d6");
    faixa.setAttribute("fill-opacity", "0.14");
    faixa.setAttribute("stroke", "#2a78d6");
    faixa.setAttribute("stroke-width", "1");
    faixa.setAttribute("y", svg.getAttribute("data-topo"));
    faixa.setAttribute(
      "height",
      numero(svg, "data-base") - numero(svg, "data-topo")
    );
    faixa.setAttribute("width", "0");
    faixa.style.display = "none";
    faixa.style.pointerEvents = "none";
    svg.appendChild(faixa);

    var painel = svg.closest("[data-selecao]");
    var saidaMin = painel && painel.querySelector("[data-faixa-min]");
    var saidaMax = painel && painel.querySelector("[data-faixa-max]");
    var recado = painel && painel.querySelector("[data-faixa-recado]");
    var botao = painel && painel.querySelector("[data-faixa-aplicar]");

    var arrastando = false;
    var pixelInicial = 0;
    var valorInicial = 0;

    function mostrar(a, b) {
      var menor = Math.min(a, b);
      var maior = Math.max(a, b);
      if (saidaMin) saidaMin.value = menor.toFixed(4).replace(".", ",");
      if (saidaMax) saidaMax.value = maior.toFixed(4).replace(".", ",");
      if (recado) {
        recado.textContent =
          "Faixa selecionada: " +
          menor.toFixed(2).replace(".", ",") +
          " a " +
          maior.toFixed(2).replace(".", ",") +
          ". Solte para recalcular.";
        recado.hidden = false;
      }
      if (botao) botao.disabled = false;
    }

    svg.addEventListener("pointerdown", function (evento) {
      if (evento.button !== 0) return;
      arrastando = true;
      pixelInicial = pixelEm(svg, evento.clientX);
      valorInicial = valorEm(svg, evento.clientX);
      faixa.style.display = "";
      faixa.setAttribute("x", pixelInicial);
      faixa.setAttribute("width", "0");
      svg.setPointerCapture(evento.pointerId);
      evento.preventDefault();
    });

    svg.addEventListener("pointermove", function (evento) {
      if (!arrastando) return;
      var atual = pixelEm(svg, evento.clientX);
      faixa.setAttribute("x", Math.min(pixelInicial, atual));
      faixa.setAttribute("width", Math.abs(atual - pixelInicial));
      mostrar(valorInicial, valorEm(svg, evento.clientX));
    });

    function terminar(evento) {
      if (!arrastando) return;
      arrastando = false;
      var atual = pixelEm(svg, evento.clientX);
      if (Math.abs(atual - pixelInicial) < ARRASTO_MINIMO) {
        // Clique sem arrasto: desfaz a marcação em vez de recalcular uma
        // faixa de largura zero.
        faixa.style.display = "none";
        if (recado) recado.hidden = true;
        if (botao) botao.disabled = true;
        return;
      }
      mostrar(valorInicial, valorEm(svg, evento.clientX));
      // Envia sozinho: o usuário já disse o que queria ao soltar o mouse, e
      // obrigá-lo a clicar num botão depois de arrastar é um passo a mais sem
      // função. O botão continua ali para quem digitar os limites à mão.
      var formulario = painel && painel.querySelector("[data-faixa-formulario]");
      if (formulario) formulario.submit();
    }

    svg.addEventListener("pointerup", terminar);
    svg.addEventListener("pointercancel", function () {
      arrastando = false;
      faixa.style.display = "none";
    });
  }

  function iniciar() {
    var graficos = document.querySelectorAll('svg[data-selecionavel="regressao"]');
    Array.prototype.forEach.call(graficos, preparar);
    // Abrir a faixa certa e rolar até ela é assunto do faixas.js, que é quem
    // sabe quais seções estão recolhidas.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
