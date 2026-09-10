/* Selecionar várias células da grade e limpá-las de uma vez.
 *
 * Corrigir um lançamento inteiro célula por célula é o trabalho que a grade
 * existe para evitar. Aqui a seleção funciona como numa planilha, que é de onde
 * o laboratório vem: arrastar sobre as células, Shift+clique para estender um
 * retângulo, Ctrl+clique (Cmd no Mac) para marcar avulsas.
 *
 * Limpar NÃO apaga do estudo. Ele esvazia os campos; quem apaga é o "Salvar",
 * porque a regra de gravação já é essa — campo em branco remove a medição
 * daquela posição. Misturar as duas coisas faria um clique apagar dado do banco
 * sem passar pelo botão que o usuário reconhece como o que grava.
 *
 * Três coisas que a seleção nunca toca:
 *   - Campo travado (réplica ou amostra excluída com justificativa). É registro
 *     do que foi descartado e por quê, e some do cálculo, não do banco.
 *   - A digitação normal: arrastar dentro de uma célula continua selecionando
 *     o texto dela. O retângulo só começa quando o ponteiro passa para OUTRA
 *     célula, que é o gesto que ninguém faz sem querer.
 *   - Os campos de fora da grade (média interlaboratorial, programa, nome do
 *     controle novo): a seleção vive dentro do [data-grade].
 */
(function () {
  "use strict";

  function campos(grade) {
    return Array.prototype.filter.call(
      grade.querySelectorAll("input[data-linha][data-coluna]"),
      function (campo) {
        return !campo.disabled;
      }
    );
  }

  function coordenada(campo, atributo) {
    return parseInt(campo.getAttribute(atributo), 10);
  }

  function preparar(grade) {
    if (grade.dataset.selecaoPronta === "sim") return;
    grade.dataset.selecaoPronta = "sim";

    var selecionados = [];
    var ancora = null; // Origem do retângulo do Shift+clique.
    var arrastando = false;
    var origem = null;
    var moveu = false;

    var painel = grade.closest("form") || document;
    var botao = painel.querySelector("[data-limpar-selecao]");
    var recado = document.querySelector("[data-recado-grade]");

    function avisar(texto) {
      if (!recado) return;
      recado.textContent = texto;
      recado.hidden = !texto;
    }

    function pintar() {
      campos(grade).forEach(function (campo) {
        campo.classList.toggle("selecionada", selecionados.indexOf(campo) !== -1);
      });
      if (botao) {
        botao.hidden = selecionados.length === 0;
        botao.textContent =
          "Limpar " +
          selecionados.length +
          (selecionados.length === 1 ? " campo" : " campos");
      }
    }

    function definir(lista) {
      selecionados = lista;
      // Tira o cursor de dentro de qualquer célula enquanto houver marcação.
      //
      // Sem isso ficava uma armadilha: marcar B e C com Ctrl+clique deixava o
      // cursor onde estava, em A, e o Backspace para corrigir um dígito em A
      // limpava B e C. Com a marcação viva o teclado é da seleção, e clicar
      // numa célula para digitar desfaz a marcação — as duas coisas nunca
      // valem ao mesmo tempo.
      if (lista.length && document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
      }
      pintar();
    }

    function limpar() {
      definir([]);
    }

    /** Todas as células dentro do retângulo formado por duas delas. */
    function retangulo(de, ate) {
      var linhaA = coordenada(de, "data-linha");
      var linhaB = coordenada(ate, "data-linha");
      var colunaA = coordenada(de, "data-coluna");
      var colunaB = coordenada(ate, "data-coluna");
      var linhaMin = Math.min(linhaA, linhaB);
      var linhaMax = Math.max(linhaA, linhaB);
      var colunaMin = Math.min(colunaA, colunaB);
      var colunaMax = Math.max(colunaA, colunaB);

      return campos(grade).filter(function (campo) {
        var linha = coordenada(campo, "data-linha");
        var coluna = coordenada(campo, "data-coluna");
        return (
          linha >= linhaMin &&
          linha <= linhaMax &&
          coluna >= colunaMin &&
          coluna <= colunaMax
        );
      });
    }

    /** Células cuja caixa cruza o retângulo desenhado pelo arrasto. */
    function dentroDoArrasto(a, b) {
      var esquerda = Math.min(a.x, b.x);
      var direita = Math.max(a.x, b.x);
      var topo = Math.min(a.y, b.y);
      var base = Math.max(a.y, b.y);

      return campos(grade).filter(function (campo) {
        var caixa = campo.getBoundingClientRect();
        return (
          caixa.right >= esquerda &&
          caixa.left <= direita &&
          caixa.bottom >= topo &&
          caixa.top <= base
        );
      });
    }

    function esvaziar() {
      if (!selecionados.length) return;
      var quantos = selecionados.length;
      selecionados.forEach(function (campo) {
        campo.value = "";
      });
      avisar(
        quantos +
          (quantos === 1 ? " campo limpo" : " campos limpos") +
          " — nada foi apagado do estudo ainda. Clique em salvar para valer."
      );
      limpar();
    }

    // --- Clique: âncora, retângulo com Shift, avulsa com Ctrl/Cmd ------------
    grade.addEventListener("mousedown", function (evento) {
      var campo = evento.target;
      if (!campo.matches || !campo.matches("input[data-linha]") || campo.disabled) {
        return;
      }

      if (evento.shiftKey && ancora) {
        evento.preventDefault(); // Sem isso o navegador seleciona texto entre os dois.
        definir(retangulo(ancora, campo));
        return;
      }

      if (evento.ctrlKey || evento.metaKey) {
        evento.preventDefault();
        var indice = selecionados.indexOf(campo);
        if (indice === -1) {
          definir(selecionados.concat([campo]));
        } else {
          definir(
            selecionados.filter(function (outro) {
              return outro !== campo;
            })
          );
        }
        ancora = campo;
        return;
      }

      // Clique simples: candidato a arrasto, sem atrapalhar o foco nem a
      // seleção de texto dentro da própria célula.
      ancora = campo;
      arrastando = true;
      moveu = false;
      origem = { x: evento.clientX, y: evento.clientY, campo: campo };
      if (selecionados.length) limpar();
    });

    document.addEventListener("mousemove", function (evento) {
      if (!arrastando || !origem) return;

      var sobre = document.elementFromPoint(evento.clientX, evento.clientY);
      var saiuDaCelula =
        sobre && sobre !== origem.campo && sobre.matches &&
        sobre.matches("input[data-linha]");

      // O retângulo só nasce quando o ponteiro chega a OUTRA célula: arrastar
      // dentro de uma célula continua sendo seleção de texto.
      if (!moveu && !saiuDaCelula) return;
      moveu = true;

      evento.preventDefault();
      if (window.getSelection) window.getSelection().removeAllRanges();
      origem.campo.blur();
      definir(
        dentroDoArrasto(origem, { x: evento.clientX, y: evento.clientY })
      );
    });

    document.addEventListener("mouseup", function () {
      arrastando = false;
      origem = null;
    });

    // --- Teclado -------------------------------------------------------------
    document.addEventListener("keydown", function (evento) {
      if (!selecionados.length) return;

      if (evento.key === "Escape") {
        limpar();
        avisar("");
        return;
      }

      if (evento.key === "Delete" || evento.key === "Backspace") {
        // Com várias células marcadas, apagar vale para todas — inclusive
        // quando o cursor está dentro de uma delas.
        evento.preventDefault();
        esvaziar();
      }
    });

    if (botao) {
      botao.addEventListener("click", function (evento) {
        evento.preventDefault();
        esvaziar();
      });
    }

    // Clicar fora da grade desfaz a marcação, como numa planilha.
    document.addEventListener("mousedown", function (evento) {
      if (grade.contains(evento.target)) return;
      if (botao && botao.contains(evento.target)) return;
      if (selecionados.length) limpar();
    });

    pintar();
  }

  function iniciar() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-grade]"),
      preparar
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
