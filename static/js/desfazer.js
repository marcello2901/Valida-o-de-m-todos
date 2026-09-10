/* Ctrl+Z em qualquer tela.
 *
 * O navegador já desfaz digitação dentro de um campo, e isso continua valendo:
 * enquanto o cursor está numa célula em que se digitou, o Ctrl+Z é dele. O
 * problema é o que o navegador NÃO desfaz — mudança feita por programa. Limpar
 * quarenta células de uma vez ou colar um bloco da planilha escreve nos campos
 * sem passar pelo teclado, e o desfazer nativo não só ignora essas mudanças
 * como perde o histórico que tinha. Daí esta pilha.
 *
 * São dois desfazeres, e a ordem entre eles é a regra inteira:
 *
 *   1. O do que ainda NÃO foi salvo — a pilha daqui. Devolve os valores aos
 *      campos, não toca no banco, e é o que responde primeiro.
 *   2. O da última gravação destrutiva — um formulário que o servidor põe na
 *      tela quando um salvar apagou ou sobrescreveu alguma coisa. Esse recarrega
 *      a página e mexe no estudo, então pergunta antes.
 *
 * Um nunca atropela o outro: só depois de esvaziar o que está na tela é que o
 * Ctrl+Z chega ao que está gravado.
 */
(function () {
  "use strict";

  var LIMITE = 60; // Passos guardados. Além disso é sessão de trabalho, não engano.

  var pilha = [];
  var refeitos = [];

  function avisar(texto) {
    var caixa = document.querySelector("[data-recado-grade]");
    if (!caixa) return;
    caixa.textContent = texto;
    caixa.hidden = !texto;
  }

  /** Guarda um passo: como estava antes, e o rótulo do que aconteceu. */
  function registrar(rotulo, antes) {
    if (!antes || !antes.length) return;
    pilha.push({ rotulo: rotulo, estado: antes });
    if (pilha.length > LIMITE) pilha.shift();
    refeitos = []; // Passo novo corta o ramo do refazer, como em qualquer editor.
  }

  /** Fotografa o valor atual de uma lista de campos. */
  function retrato(campos) {
    return Array.prototype.map.call(campos, function (campo) {
      return { campo: campo, valor: campo.value };
    });
  }

  function aplicar(estado) {
    var anterior = retrato(
      estado.map(function (item) {
        return item.campo;
      })
    );
    estado.forEach(function (item) {
      item.campo.value = item.valor;
    });
    if (estado.length && estado[0].campo.focus) {
      estado[0].campo.focus();
      estado[0].campo.select();
    }
    return anterior;
  }

  function desfazerLocal() {
    var passo = pilha.pop();
    if (!passo) return false;
    refeitos.push({ rotulo: passo.rotulo, estado: aplicar(passo.estado) });
    avisar(
      "Desfeito: " +
        passo.rotulo +
        ". Nada foi gravado — o estudo só muda quando você salva."
    );
    return true;
  }

  function refazerLocal() {
    var passo = refeitos.pop();
    if (!passo) return false;
    pilha.push({ rotulo: passo.rotulo, estado: aplicar(passo.estado) });
    avisar("Refeito: " + passo.rotulo + ".");
    return true;
  }

  /* O campo em que se digitou fica com o desfazer do navegador, que é melhor
   * que o nosso para digitação: ele conhece cada tecla. A marca nasce no
   * primeiro caractere e morre quando o campo perde e reganha o foco. */
  document.addEventListener("input", function (evento) {
    if (evento.target && evento.target.dataset) {
      evento.target.dataset.digitou = "sim";
    }
  });

  document.addEventListener("focusin", function (evento) {
    if (evento.target && evento.target.dataset) {
      delete evento.target.dataset.digitou;
    }
  });

  function digitando() {
    var ativo = document.activeElement;
    return !!(
      ativo &&
      ativo.dataset &&
      ativo.dataset.digitou === "sim" &&
      ativo.matches &&
      ativo.matches("input, textarea")
    );
  }

  function desfazerGravado() {
    var formulario = document.querySelector("[data-desfazer-gravado]");
    if (!formulario) return false;

    var descricao = formulario.getAttribute("data-descricao") || "mudou o lançamento";
    if (
      !window.confirm(
        "Desfazer a última gravação, que " +
          descricao +
          "?\n\nO estudo volta ao estado anterior a essa gravação. " +
          "O que estiver digitado nesta tela e ainda não salvo se perde, e a " +
          "desfeita fica registrada na trilha de auditoria."
      )
    ) {
      return true; // Perguntou e o usuário disse não: o atalho já fez o que devia.
    }
    formulario.submit();
    return true;
  }

  document.addEventListener("keydown", function (evento) {
    if (!(evento.ctrlKey || evento.metaKey) || evento.altKey) return;

    var tecla = (evento.key || "").toLowerCase();
    var refazer = tecla === "y" || (tecla === "z" && evento.shiftKey);

    if (refazer) {
      if (refazerLocal()) evento.preventDefault();
      return;
    }

    if (tecla !== "z") return;
    if (digitando()) return; // Desfazer da digitação é do navegador.

    if (desfazerLocal()) {
      evento.preventDefault();
      return;
    }
    if (desfazerGravado()) evento.preventDefault();
  });

  // Registro aberto para as telas de lançamento: quem muda campo por programa
  // fotografa antes e entrega aqui.
  window.Desfazer = {
    registrar: registrar,
    retrato: retrato,
    desfazer: desfazerLocal,
    refazer: refazerLocal,
    pendentes: function () {
      return pilha.length;
    },
  };
})();
