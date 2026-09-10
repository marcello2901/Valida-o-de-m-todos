"""Testes da tela de resultado e do isolamento entre laboratórios.

O primeiro bloco guarda uma propriedade de segurança: um laboratório nunca pode
ver o estudo de outro. É o tipo de falha que não aparece no uso normal — só
quando alguém troca o número na barra de endereço — e por isso precisa de teste.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalogo.models import (
    Controle,
    Reagente,
    EspecificacaoQualidade,
    LimiteImprecisao,
    Mensurando,
    SistemaAnalitico,
)
from contas.models import Assinatura, Laboratorio, RegistroAuditoria, Usuario
from estudos import servicos
from estudos.models import (
    VERSAO_MOTOR,
    AmostraComparacao,
    AmostraQualitativa,
    Estudo,
    NivelEstudo,
    Replica,
    Veredito,
)
from motor import precisao


def montar_laboratorio(nome: str, cnpj: str) -> Laboratorio:
    laboratorio = Laboratorio.objects.create(razao_social=nome, cnpj=cnpj)
    Assinatura.objects.create(laboratorio=laboratorio, modulo=Assinatura.COMPLETO)
    return laboratorio


def montar_estudo(laboratorio: Laboratorio, usuario: Usuario) -> Estudo:
    mensurando = Mensurando.objects.create(
        laboratorio=laboratorio,
        nome="FT4",
        unidade_medida="ng/dL",
        material_biologico="soro",
    )
    teste = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.TESTE,
        equipamento="Atellica", numero_serie="IH00715", metodologia="Quimioluminescência",
    )
    comparacao = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.COMPARACAO,
        equipamento="Centaur", numero_serie="CE04412", metodologia="Quimioluminescência",
    )
    controle = Controle.objects.create(
        sistema=teste, nivel=1, nome="Controle 1", lote="L1",
        validade=date(2027, 1, 1), valor_alvo=Decimal("1.3"),
    )
    # O fixture precisa de reagente: sem ele, um estudo de teste não exercita o
    # caminho do intervalo analítico nem o do retrato congelado, e um objeto do
    # banco vazando para dentro do JSON passava despercebido.
    Reagente.objects.create(
        sistema=teste, mensurando=mensurando, nome="Kit FT4", lote="R1",
        validade=date(2027, 6, 30),
        intervalo_analitico_minimo=Decimal("0.1"), intervalo_analitico_maximo=Decimal("12.0"),
    )
    Reagente.objects.create(
        sistema=comparacao, mensurando=mensurando, nome="Kit FT4 comparador", lote="R2",
        validade=date(2027, 6, 30),
        intervalo_analitico_minimo=Decimal("0.15"), intervalo_analitico_maximo=Decimal("10.0"),
    )
    especificacao = EspecificacaoQualidade.objects.create(
        laboratorio=laboratorio, mensurando=mensurando, nome="FT4 — ControlLab",
        erro_total_maximo_pct=Decimal("12.00"), erro_total_referencia="ControlLab",
        bias_maximo_pct=Decimal("6.00"), bias_referencia="50% do ControlLab",
    )
    LimiteImprecisao.objects.create(
        especificacao=especificacao, nivel=1, maximo_pct=Decimal("4.00"), referencia="1/3 do ControlLab"
    )

    estudo = Estudo.objects.create(
        laboratorio=laboratorio,
        identificacao="Validação FT4",
        modulo=Assinatura.COMPLETO,
        desenho_precisao=precisao.DESENHO_MULTIPLAS_CORRIDAS,
        mensurando=mensurando,
        sistema_teste=teste,
        sistema_comparacao=comparacao,
        especificacao=especificacao,
        criado_por=usuario,
    )

    nivel = NivelEstudo.objects.create(estudo=estudo, numero=1, controle=controle)
    for corrida in range(1, 6):
        for sequencia, valor in enumerate(["1.28", "1.30", "1.32", "1.29", "1.31"], start=1):
            Replica.objects.create(
                nivel=nivel, corrida=corrida, sequencia=sequencia,
                valor=Decimal(valor) + Decimal("0.005") * corrida,
            )
    for indice in range(1, 11):
        base = Decimal("0.5") * indice
        AmostraComparacao.objects.create(
            estudo=estudo, identificacao=f"AM-{indice:03d}",
            valor_comparacao=base, valor_teste=base * Decimal("1.02"),
        )
    return estudo


class TestIsolamentoEntreLaboratorios(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_dono_do_estudo_ve_o_resultado(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Validação FT4")

    def test_outro_laboratorio_nao_ve_o_estudo(self):
        # Trocar o número na barra de endereço não pode revelar dado alheio.
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_usuario_sem_laboratorio_nao_ve_o_estudo(self):
        avulso = Usuario.objects.create_user(username="avulso", password="senha-longa-de-teste")
        self.client.force_login(avulso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_equipe_interna_ve_qualquer_estudo(self):
        # Suporte da plataforma precisa enxergar para atender o cliente.
        suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste", is_staff=True
        )
        self.client.force_login(suporte)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_visitante_nao_autenticado_e_mandado_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestConteudoDoResultado(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.client.force_login(self.dono)
        self.resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_traz_as_faixas_do_estudo(self):
        # A rastreabilidade deixou de ser uma seção única e virou três faixas
        # condensáveis, cada uma resumida numa linha quando resolvida.
        for faixa in [
            "Analito e limites",
            "Sistemas analíticos",
            "Insumos e controles",
            "Precisão e exatidão",
            "Comparabilidade",
        ]:
            self.assertContains(self.resposta, faixa)

    def test_nao_traz_mais_a_faixa_de_veredito_por_nivel(self):
        # Ela repetia, indicador por indicador, o que as faixas de precisão e
        # comparabilidade já mostram com o limite ao lado.
        self.assertNotContains(self.resposta, "Veredito por nível")

    def test_todas_as_faixas_nascem_fechadas(self):
        # A tela é o índice do estudo: quem chega nela quer ver o estado de
        # tudo antes de entrar numa parte. Antes a etapa corrente abria sozinha
        # e empurrava o resto para fora da primeira tela.
        corpo = self.resposta.content.decode()
        assert corpo.count('<details class="cartao faixa"') >= 4, "as faixas deveriam existir"
        assert '<details class="cartao faixa" open' not in corpo, "nenhuma faixa deveria nascer aberta"

    def test_traz_as_medidas_pedidas(self):
        for medida in [
            "Razão das médias",
            "Regressão de Deming",
            "Concordância de Lin",
            "Concordância analítica",
            "Concordância clínica",
        ]:
            self.assertContains(self.resposta, medida)

    def test_desenha_os_graficos(self):
        # Os gráficos são SVG embutido; sem biblioteca externa, sem JavaScript.
        self.assertContains(self.resposta, "<svg")
        self.assertContains(self.resposta, "Levey-Jennings")

    def test_mostra_a_referencia_cientifica_de_cada_limite(self):
        self.assertContains(self.resposta, "ControlLab")

    def test_distingue_previa_de_veredito_congelado(self):
        # O estudo do fixture não foi concluído: o cabeçalho tem de dizer que o
        # resultado é prévia, não decisão assinada.
        self.assertContains(self.resposta, "Prévia")
        self.assertNotContains(self.resposta, "Congelado em")

    def test_avisa_quando_faltam_amostras_para_o_ep09(self):
        # O estudo tem 10 amostras; o EP09 pede 40.
        self.assertContains(self.resposta, "CLSI EP09")

    def test_nao_vaza_o_estudo_no_titulo_de_erro(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertNotContains(resposta, "Validação FT4", status_code=404)


class TestQuadro(TestCase):
    """O quadro precisa colocar cada estudo na coluna certa e dizer o que falta."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("quadro")

    def test_o_estudo_aparece_no_quadro(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "FT4")

    def test_estudo_com_dados_parciais_fica_em_coletando(self):
        # 25 réplicas de 25 e 10 amostras de 40: começou, não terminou.
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_COLETANDO)

    def test_estudo_sem_dado_nenhum_fica_em_rascunho(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_RASCUNHO)

    def test_estudo_liberado_fica_na_ultima_coluna(self):
        self.estudo.situacao = Estudo.LIBERADO

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_LIBERADO)

    def test_a_proxima_acao_diz_quantas_amostras_faltam(self):
        # A precisão está completa; o que trava é a comparabilidade.
        self.assertEqual(self.estudo.proxima_acao(), "Faltam 30 amostras")

    def test_a_proxima_acao_aponta_a_replica_seguinte(self):
        Replica.objects.filter(nivel__estudo=self.estudo, corrida__gte=4).delete()

        self.assertEqual(self.estudo.proxima_acao(), "Nível 1, réplica 16")

    def test_estudo_de_outro_laboratorio_nao_aparece(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertNotContains(self.client.get(self.url), "FT4")

    def test_visitante_vai_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestCalcularELiberar(TestCase):
    """As duas ações que movem o estudo pelo quadro.

    São o ponto em que um cálculo vira registro de qualidade, então o que se
    testa aqui é sobretudo o que elas *recusam* fazer.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.responsavel = Usuario.objects.create_user(
            username="responsavel", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.analista = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.responsavel)
        self.calcular_url = reverse("concluir_estudo", args=[self.estudo.pk])
        self.liberar_url = reverse("liberar_estudo", args=[self.estudo.pk])

    def test_calcular_congela_o_retrato_e_move_o_estudo(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_CALCULADO)
        veredito = self.estudo.veredito
        self.assertEqual(veredito.versao_motor, VERSAO_MOTOR)
        self.assertIn("precisao", veredito.detalhamento)

    def test_o_retrato_guarda_os_limites_vigentes_no_momento(self):
        # É o que permite defender o número numa auditoria: a ficha pode mudar
        # depois, mas o relatório mostra contra o que se decidiu na época.
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        limites = self.estudo.veredito.detalhamento["especificacao"]
        self.assertEqual(limites["erro_total"]["valor_pct"], 12.0)
        self.assertEqual(limites["erro_total"]["referencia"], "ControlLab")

    def test_calcular_registra_na_trilha_de_auditoria(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        registro = RegistroAuditoria.objects.get(acao="calculou o estudo")
        self.assertEqual(registro.usuario, self.analista)
        self.assertEqual(registro.laboratorio, self.laboratorio)

    def test_estudo_sem_dado_nenhum_nao_calcula(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)
        self.assertFalse(hasattr(self.estudo, "veredito"))

    def test_recalcular_substitui_o_retrato_anterior(self):
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.calcular_url)

        self.assertEqual(Veredito.objects.filter(estudo=self.estudo).count(), 1)
        self.assertTrue(RegistroAuditoria.objects.filter(acao="recalculou o estudo").exists())

    def test_get_nao_calcula(self):
        # Mudança de estado por GET seria disparada por um simples recarregar.
        self.client.force_login(self.analista)

        resposta = self.client.get(self.calcular_url)

        self.assertEqual(resposta.status_code, 405)
        self.assertFalse(Veredito.objects.exists())

    def test_laboratorio_alheio_nao_calcula(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.post(self.calcular_url).status_code, 404)
        self.assertFalse(Veredito.objects.exists())

    def test_analista_nao_libera(self):
        # Assinar relatório de validação é ato do responsável técnico.
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)

    def _decidir(self, escolha=Veredito.APROVADO):
        """Marca o veredito, que é o que destrava a liberação."""
        self.client.post(
            reverse("analise_estudo", args=[self.estudo.pk]),
            {"analise_critica": "", "veredito": escolha},
        )

    def test_responsavel_libera_e_assina(self):
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self._decidir()

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.liberado_por, self.responsavel)
        self.assertIsNotNone(self.estudo.veredito.liberado_em)

    def test_nao_libera_sem_calcular_antes(self):
        self.client.force_login(self.responsavel)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)

    def test_estudo_liberado_nao_recalcula(self):
        # Recalcular um relatório assinado descolaria o número do que se assinou.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self._decidir()
        self.client.post(self.liberar_url)
        self.estudo.refresh_from_db()
        congelado_em = self.estudo.veredito.calculado_em

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.calculado_em, congelado_em)

    def test_a_tela_avisa_quando_o_recalculo_diverge_do_assinado(self):
        # A ficha do analito apertou depois da assinatura: a tela recalcula ao
        # vivo, o relatório mantém o número assinado, e o usuário precisa ver
        # que os dois deixaram de bater.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.leitura_do_motor(), Veredito.APROVADO)

        ficha = self.estudo.especificacao
        ficha.erro_total_maximo_pct = Decimal("1.00")
        ficha.save()
        ficha.limites_imprecisao.update(maximo_pct=Decimal("0.25"))

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "não bate com o retrato congelado")


class TestGradeDeReplicas(TestCase):
    """A grade de lançamento: 30 linhas por nível, salvas de uma vez."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.url = reverse("replicas_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def test_a_grade_tem_trinta_linhas_por_nivel(self):
        colunas = servicos.montar_grade(self.estudo)

        self.assertEqual(len(colunas), 1)
        self.assertEqual(len(colunas[0]["linhas"]), 30)

    def test_as_linhas_se_agrupam_de_cinco_em_cinco_por_corrida(self):
        # O desenho de referência do EP15: cada bloco de 5 é uma corrida.
        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual((linhas[0]["corrida"], linhas[0]["sequencia"]), (1, 1))
        self.assertEqual((linhas[4]["corrida"], linhas[4]["sequencia"]), (1, 5))
        self.assertEqual((linhas[5]["corrida"], linhas[5]["sequencia"]), (2, 1))
        self.assertEqual((linhas[29]["corrida"], linhas[29]["sequencia"]), (6, 5))

    def test_em_corrida_unica_todas_as_linhas_sao_a_mesma_corrida(self):
        self.estudo.desenho_precisao = precisao.DESENHO_CORRIDA_UNICA
        self.estudo.save(update_fields=["desenho_precisao"])

        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual({linha["corrida"] for linha in linhas}, {1})
        self.assertEqual(linhas[29]["sequencia"], 30)

    def test_a_grade_traz_as_replicas_ja_lancadas(self):
        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual(linhas[0]["valor"], Decimal("1.2850"))
        self.assertIsNone(linhas[25]["valor"])

    def test_salvar_grava_o_que_foi_digitado(self):
        resposta = self.client.post(self.url, {f"nivel_{self.nivel.pk}_26": "1,33"})

        self.assertEqual(resposta.status_code, 302)
        gravada = Replica.objects.get(nivel=self.nivel, corrida=6, sequencia=1)
        self.assertEqual(gravada.valor, Decimal("1.3300"))

    def test_campo_em_branco_apaga_a_replica(self):
        antes = Replica.objects.filter(nivel=self.nivel).count()

        self.client.post(self.url, {f"nivel_{self.nivel.pk}_1": ""})

        self.assertEqual(Replica.objects.filter(nivel=self.nivel).count(), antes - 1)

    def test_valor_ilegivel_nao_derruba_os_valores_bons(self):
        # Descartar as 74 réplicas boas por causa da 75ª é perder o trabalho de
        # cinco dias por um dígito. A ruim volta nomeada; a boa fica gravada.
        antes = Replica.objects.filter(nivel=self.nivel).count()

        resposta = self.client.post(
            self.url,
            {f"nivel_{self.nivel.pk}_26": "1,40", f"nivel_{self.nivel.pk}_27": "abc"},
            follow=True,
        )

        self.assertEqual(Replica.objects.filter(nivel=self.nivel).count(), antes + 1)
        self.assertContains(resposta, "não é um número")
        self.assertContains(resposta, "não pôde")

    def test_replica_excluida_com_justificativa_nao_e_alterada(self):
        alvo = Replica.objects.get(nivel=self.nivel, corrida=1, sequencia=1)
        alvo.excluida = True
        alvo.justificativa_exclusao = "bolha na cubeta"
        alvo.save()

        self.client.post(self.url, {})

        alvo.refresh_from_db()
        self.assertTrue(alvo.excluida)
        self.assertEqual(alvo.justificativa_exclusao, "bolha na cubeta")

    def test_a_media_interlaboratorial_e_gravada_junto(self):
        self.client.post(
            self.url,
            {
                f"alvo_{self.nivel.pk}": "1,32",
                f"provedor_{self.nivel.pk}": "Controllab EQ — ciclo 3/2026",
            },
        )

        self.nivel.refresh_from_db()
        self.assertEqual(self.nivel.media_interlaboratorial, Decimal("1.3200"))
        self.assertEqual(
            self.nivel.provedor_interlaboratorial, "Controllab EQ — ciclo 3/2026"
        )

    def test_o_programa_interlaboratorial_e_texto_livre(self):
        # Era uma lista de quatro opções. Cada laboratório nomeia o seu programa
        # de um jeito, e é esse nome que identifica o boletim numa auditoria.
        resposta = self.client.get(self.url)

        self.assertContains(resposta, f'name="provedor_{self.nivel.pk}"')
        self.assertNotContains(resposta, f'<select name="provedor_{self.nivel.pk}"')

    def test_nome_de_programa_gigante_e_cortado_e_nao_estoura(self):
        self.client.post(
            self.url,
            {f"alvo_{self.nivel.pk}": "1,32", f"provedor_{self.nivel.pk}": "P" * 300},
        )

        self.nivel.refresh_from_db()
        self.assertEqual(len(self.nivel.provedor_interlaboratorial), 80)

    def test_acrescentar_nivel_cria_a_coluna(self):
        outro = Controle.objects.create(
            sistema=self.estudo.sistema_teste, mensurando=self.estudo.mensurando,
            nivel=2, nome="Controle 2", lote="L2",
            validade=date(2027, 1, 1), valor_alvo=Decimal("3.0"),
        )

        self.client.post(self.url, {"acao": "adicionar_nivel", "controle": outro.pk})

        self.assertEqual(self.estudo.niveis.count(), 2)
        self.assertEqual(self.estudo.niveis.get(numero=2).controle, outro)

    def test_nao_oferece_controle_de_outro_analito(self):
        # Mesmo equipamento, analito diferente: não pode virar coluna deste estudo.
        outro_analito = Mensurando.objects.create(
            laboratorio=self.laboratorio, nome="HbA1c",
            unidade_medida="%", material_biologico="sangue total",
        )
        alheio = Controle.objects.create(
            sistema=self.estudo.sistema_teste, mensurando=outro_analito,
            nivel=1, nome="Controle HbA1c", lote="LX",
            validade=date(2027, 1, 1), valor_alvo=Decimal("5.6"),
        )

        resposta = self.client.get(self.url)
        self.assertNotContains(resposta, "Controle HbA1c")

        self.client.post(self.url, {"acao": "adicionar_nivel", "controle": alheio.pk})
        self.assertEqual(self.estudo.niveis.count(), 1)

    def test_estudo_liberado_nao_aceita_lancamento(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 302)

    def test_laboratorio_alheio_nao_abre_a_grade(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)


class TestIntervalosDeReferenciaPorMetodo(TestCase):
    """Cada metodologia classifica contra o intervalo que ela imprime no laudo."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)

    def test_o_estudo_comeca_sem_intervalo_nenhum(self):
        # Não há mais reserva no analito: o intervalo é da metodologia, e quem o
        # declara é a validação. Em branco, a concordância clínica não é
        # avaliada — e o relatório diz isso, em vez de classificar os dois
        # métodos por uma faixa que não é de nenhum dos dois.
        self.assertEqual(self.estudo.intervalo_de_comparacao(), (None, None))
        self.assertEqual(self.estudo.intervalo_de_teste(), (None, None))

    def test_o_intervalo_declarado_no_estudo_e_o_que_vale(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.9")
        self.estudo.referencia_comparacao_superior = Decimal("1.7")
        self.estudo.save()

        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.9"), Decimal("1.7"))
        )

    def test_intervalos_diferentes_chegam_ao_calculo(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.8")
        self.estudo.referencia_comparacao_superior = Decimal("1.8")
        self.estudo.referencia_teste_inferior = Decimal("0.85")
        self.estudo.referencia_teste_superior = Decimal("1.86")
        self.estudo.save()

        clinica = servicos.calcular(self.estudo)["comparabilidade"]["clinica"]

        self.assertTrue(clinica["intervalos_diferentes"])
        self.assertEqual(clinica["intervalo_teste"], (0.85, 1.86))

    def test_a_tela_mostra_os_dois_intervalos_usados(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.8")
        self.estudo.referencia_comparacao_superior = Decimal("1.8")
        self.estudo.referencia_teste_inferior = Decimal("0.85")
        self.estudo.referencia_teste_superior = Decimal("1.86")
        self.estudo.save()
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "0,85")
        self.assertContains(resposta, "1,86")

    def test_a_tela_traz_pearson_e_a_regressao_simples(self):
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Correlação de Pearson")
        self.assertContains(resposta, "Regressão linear simples")
        self.assertContains(resposta, "regressão linear simples")
        self.assertContains(resposta, "identidade (y = x)")


class TestGradeDeAmostras(TestCase):
    """Grade de amostras pareadas: 40 linhas abertas, ampliáveis."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.url = reverse("amostras_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def test_abre_com_o_minimo_do_ep09(self):
        grade = servicos.montar_grade_amostras(self.estudo)

        self.assertEqual(grade["total"], 40)
        self.assertEqual(sum(len(pista) for pista in grade["pistas"]), 40)

    def test_as_linhas_se_repartem_em_pistas_de_vinte(self):
        grade = servicos.montar_grade_amostras(self.estudo)

        self.assertEqual([len(pista) for pista in grade["pistas"]], [20, 20])

    def test_as_amostras_ja_lancadas_ocupam_as_primeiras_linhas(self):
        # O fixture cadastra 10 amostras.
        linhas = servicos.montar_grade_amostras(self.estudo)["pistas"][0]

        self.assertEqual(linhas[0]["identificacao"], "AM-001")
        self.assertIsNotNone(linhas[0]["comparacao"])
        self.assertEqual(linhas[10]["identificacao"], "")

    def test_pedir_mais_linhas_amplia_a_grade(self):
        grade = servicos.montar_grade_amostras(self.estudo, linhas_pedidas=50)

        self.assertEqual(grade["total"], 50)
        self.assertEqual([len(pista) for pista in grade["pistas"]], [20, 20, 10])

    def test_a_grade_nunca_encolhe_abaixo_do_que_ja_foi_digitado(self):
        # Um número pequeno na barra de endereço não pode esconder amostra.
        for indice in range(11, 46):
            AmostraComparacao.objects.create(
                estudo=self.estudo, identificacao=f"AM-{indice:03d}",
                valor_comparacao=Decimal("1.0"), valor_teste=Decimal("1.0"),
            )

        grade = servicos.montar_grade_amostras(self.estudo, linhas_pedidas=5)

        self.assertEqual(grade["total"], 45)

    def test_o_botao_de_mais_linhas_leva_a_grade_maior(self):
        resposta = self.client.post(self.url, {"acao": "adicionar_linhas", "total": "40"})

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("linhas=50", resposta["Location"])

    def test_salvar_grava_a_amostra_nova(self):
        self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_id": "AM-011",
                "amostra_11_comparacao": "3,20",
                "amostra_11_teste": "3,26",
            },
        )

        gravada = AmostraComparacao.objects.get(estudo=self.estudo, identificacao="AM-011")
        self.assertEqual(gravada.valor_comparacao, Decimal("3.2000"))
        self.assertEqual(gravada.valor_teste, Decimal("3.2600"))

    def test_identificacao_em_branco_recebe_a_sugerida(self):
        # Ninguém deveria digitar quarenta identificadores sequenciais à mão.
        self.client.post(
            self.url,
            {"total": "40", "amostra_12_id": "", "amostra_12_comparacao": "1", "amostra_12_teste": "1"},
        )

        self.assertTrue(
            AmostraComparacao.objects.filter(estudo=self.estudo, identificacao="AM-012").exists()
        )

    def test_meia_amostra_nao_grava_nada(self):
        # Um par incompleto não entra em regressão nenhuma.
        antes = self.estudo.amostras_comparacao.count()

        resposta = self.client.post(
            self.url,
            {"total": "40", "amostra_11_comparacao": "3,20", "amostra_11_teste": ""},
            follow=True,
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes)
        self.assertContains(resposta, "nos dois sistemas")

    def test_codigo_de_barras_repetido_e_aceito(self):
        # Acontece na rotina: a mesma amostra corrida duas vezes, um código
        # reaproveitado entre dias. Recusar obrigaria a inventar um
        # identificador falso — pior para a rastreabilidade que o repetido.
        self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_id": "250443609701", "amostra_11_comparacao": "1", "amostra_11_teste": "1",
                "amostra_12_id": "250443609701", "amostra_12_comparacao": "2", "amostra_12_teste": "2",
            },
        )

        repetidas = AmostraComparacao.objects.filter(
            estudo=self.estudo, identificacao="250443609701"
        )
        self.assertEqual(repetidas.count(), 2)
        self.assertEqual(
            sorted(str(a.valor_comparacao) for a in repetidas), ["1.0000", "2.0000"]
        )

    def test_valor_ilegivel_deixa_as_linhas_boas_entrarem(self):
        antes = self.estudo.amostras_comparacao.count()

        resposta = self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_comparacao": "1", "amostra_11_teste": "1",
                "amostra_12_comparacao": "abc", "amostra_12_teste": "2",
            },
            follow=True,
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes + 1)
        self.assertContains(resposta, "Linha 12")
        self.assertContains(resposta, "não pôde")

    def test_campos_em_branco_apagam_a_amostra(self):
        antes = self.estudo.amostras_comparacao.count()

        self.client.post(
            self.url,
            {"total": "40", "amostra_1_id": "AM-001", "amostra_1_comparacao": "", "amostra_1_teste": ""},
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes - 1)

    def test_envio_parcial_nao_apaga_o_que_nao_veio(self):
        # A mesma armadilha da grade de réplicas: ausente não é vazio.
        antes = self.estudo.amostras_comparacao.count()

        self.client.post(self.url, {"total": "40"})

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes)

    def test_amostra_excluida_com_justificativa_nao_e_alterada(self):
        alvo = self.estudo.amostras_comparacao.first()
        alvo.excluida = True
        alvo.justificativa_exclusao = "hemólise"
        alvo.save()

        self.client.post(
            self.url,
            {"total": "40", "amostra_1_id": "OUTRA", "amostra_1_comparacao": "9", "amostra_1_teste": "9"},
        )

        alvo.refresh_from_db()
        self.assertTrue(alvo.excluida)
        self.assertEqual(alvo.justificativa_exclusao, "hemólise")

    def test_estudo_liberado_nao_aceita_lancamento(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])

        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_laboratorio_alheio_nao_abre_a_grade(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_um_numero_absurdo_de_linhas_nao_derruba_a_tela(self):
        resposta = self.client.get(self.url, {"linhas": "999999"})

        self.assertEqual(resposta.status_code, 200)

    def test_o_card_do_quadro_leva_a_grade_que_falta(self):
        # Precisão completa, comparabilidade não: o card promete amostras.
        self.assertEqual(self.estudo.proxima_acao(), "Faltam 30 amostras")
        self.assertEqual(self.estudo.tela_da_proxima_acao(), "amostras_estudo")

    def test_com_precisao_incompleta_o_card_leva_as_replicas(self):
        Replica.objects.filter(nivel__estudo=self.estudo, corrida__gte=4).delete()

        self.assertEqual(self.estudo.tela_da_proxima_acao(), "replicas_estudo")

    def test_o_cabecalho_nao_diz_quarenta_e_um_de_quarenta(self):
        # Passar do mínimo não é erro, e "41 de 40" lia como se fosse.
        AmostraComparacao.objects.create(
            estudo=self.estudo, identificacao="AM-041",
            valor_comparacao=Decimal("1.0"), valor_teste=Decimal("1.0"),
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "11 amostras lançadas")
        self.assertNotContains(resposta, "de 40 lançadas")

    def test_o_cabecalho_diz_quanto_falta_para_o_minimo(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Faltam 30 para o mínimo do EP09")


class TestLeituraDeNumeroBrasileiro(TestCase):
    """Como o programa lê um número copiado de planilha em português.

    O Excel em pt-BR copia 1234,56 como “1.234,56”. Trocar só a vírgula por
    ponto produzia “1.234.56”, recusado como não-numérico — ou seja, glicose,
    CK e ferritina, que passam de mil na rotina, não entravam.
    """

    def test_virgula_decimal(self):
        self.assertEqual(servicos.converter_numero("0,930"), Decimal("0.930"))

    def test_ponto_de_milhar_com_virgula_decimal(self):
        self.assertEqual(servicos.converter_numero("1.234,56"), Decimal("1234.56"))
        self.assertEqual(servicos.converter_numero("1.234.567,89"), Decimal("1234567.89"))

    def test_formato_americano_tambem_e_lido(self):
        self.assertEqual(servicos.converter_numero("1,234.56"), Decimal("1234.56"))

    def test_zero_a_esquerda_nao_e_milhar(self):
        # "0.930" só pode ser 0,930: nenhum separador de milhar segue um zero.
        self.assertEqual(servicos.converter_numero("0.930"), Decimal("0.930"))

    def test_quatro_digitos_antes_do_ponto_nao_sao_milhar(self):
        # O milhar sairia como "1.234.567"; então "1234.567" é decimal.
        self.assertEqual(servicos.converter_numero("1234.567"), Decimal("1234.567"))

    def test_o_caso_ambiguo_e_recusado_em_vez_de_adivinhado(self):
        # "1.500" tanto pode ser 1,5 quanto 1500. Adivinhar errado aqui não dá
        # um número estranho: dá um número mil vezes maior num laudo assinado.
        with self.assertRaises(servicos.NumeroAmbiguo):
            servicos.converter_numero("1.500")

    def test_a_recusa_explica_as_duas_leituras(self):
        try:
            servicos.converter_numero("12.345")
        except servicos.NumeroAmbiguo as ambiguo:
            self.assertIn("12,345", str(ambiguo))
            self.assertIn("12345", str(ambiguo))
        else:
            self.fail("deveria ter recusado")

    def test_a_grade_recusa_o_ambiguo_com_a_linha(self):
        laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=laboratorio
        )
        estudo = montar_estudo(laboratorio, usuario)
        self.client.force_login(usuario)

        resposta = self.client.post(
            reverse("amostras_estudo", args=[estudo.pk]),
            {"total": "40", "amostra_11_comparacao": "1.500", "amostra_11_teste": "1,6"},
            follow=True,
        )

        self.assertContains(resposta, "Linha 11")
        self.assertContains(resposta, "pode ser")

    def test_valores_acima_de_mil_entram_pela_grade(self):
        # Glicose de 1.234 mg/dL vinda da planilha: antes era recusada.
        laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=laboratorio
        )
        estudo = montar_estudo(laboratorio, usuario)
        self.client.force_login(usuario)

        self.client.post(
            reverse("amostras_estudo", args=[estudo.pk]),
            {"total": "40", "amostra_11_comparacao": "1.234,50", "amostra_11_teste": "1.240,00"},
        )

        gravada = AmostraComparacao.objects.get(estudo=estudo, identificacao="AM-011")
        self.assertEqual(gravada.valor_comparacao, Decimal("1234.5000"))


class TestLeituraDaRazaoDasMedias(TestCase):
    """A razão das médias e o limite com que ela se compara, lado a lado."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_a_leitura_cita_o_bias_maximo_da_ficha(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Razão das médias, valor a ser comparado com")
        self.assertContains(resposta, "[Bias máximo 6,00%]")

    def test_sem_bias_na_ficha_a_leitura_diz_o_que_falta(self):
        ficha = self.estudo.especificacao
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = None
        ficha.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "bias máximo não definido na ficha")

    def test_passing_bablok_saiu_da_tela_e_do_calculo(self):
        resposta = self.client.get(self.url)

        self.assertNotContains(resposta, "Passing")
        self.assertNotIn("passing_bablok", servicos.calcular(self.estudo)["comparabilidade"])


class TestNavegacaoEntreGradeEResultado(TestCase):
    """O caminho de ida e volta entre as grades e a tela de resultado.

    O card do quadro leva à grade que falta preencher, e de lá não havia como
    chegar ao resultado: só uma seta sem rótulo, que ninguém reconhecia como
    caminho de volta.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.client.force_login(self.usuario)

    def test_a_grade_de_replicas_oferece_o_resultado_com_rotulo(self):
        resposta = self.client.get(reverse("replicas_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Ver resultado")
        self.assertContains(resposta, reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_a_grade_de_amostras_oferece_o_resultado_com_rotulo(self):
        resposta = self.client.get(reverse("amostras_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Ver resultado")

    def test_salvar_replicas_leva_ao_resultado(self):
        resposta = self.client.post(
            reverse("replicas_estudo", args=[self.estudo.pk]),
            {f"nivel_{self.nivel.pk}_26": "1,33"},
        )

        self.assertRedirects(resposta, reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_salvar_amostras_leva_ao_resultado(self):
        resposta = self.client.post(
            reverse("amostras_estudo", args=[self.estudo.pk]),
            {"total": "40", "amostra_11_comparacao": "1", "amostra_11_teste": "1"},
        )

        self.assertRedirects(resposta, reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_com_erro_a_grade_nao_manda_para_o_resultado(self):
        # Quem tem o que corrigir precisa ficar onde estão os campos.
        resposta = self.client.post(
            reverse("replicas_estudo", args=[self.estudo.pk]),
            {f"nivel_{self.nivel.pk}_26": "abc"},
        )

        self.assertRedirects(resposta, reverse("replicas_estudo", args=[self.estudo.pk]))

    def test_acrescentar_linhas_nao_manda_para_o_resultado(self):
        resposta = self.client.post(
            reverse("amostras_estudo", args=[self.estudo.pk]),
            {"acao": "adicionar_linhas", "total": "40"},
        )

        self.assertIn("linhas=50", resposta["Location"])


class TestAnaliseCritica(TestCase):
    """A conclusão do responsável, que acompanha o relatório."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="responsavel", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.url = reverse("analise_estudo", args=[self.estudo.pk])

    def calcular(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.estudo.refresh_from_db()

    def test_a_caixa_so_aparece_depois_do_congelamento(self):
        # Antes do cálculo não há resultado para analisar criticamente.
        antes = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))
        self.assertNotContains(antes, "Conclusão e veredito")

        self.calcular()

        depois = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))
        self.assertContains(depois, "Conclusão e veredito")

    def test_grava_o_texto_no_veredito(self):
        self.calcular()

        self.client.post(self.url, {"analise_critica": "Lote no fim da validade."})

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.analise_critica, "Lote no fim da validade.")
        self.assertIsNotNone(self.estudo.veredito.analise_atualizada_em)

    def test_sem_calculo_a_analise_e_recusada(self):
        resposta = self.client.post(self.url, {"analise_critica": "algo"}, follow=True)

        self.assertContains(resposta, "Calcule o estudo primeiro")

    def test_continua_editavel_depois_do_congelamento(self):
        self.calcular()
        self.client.post(self.url, {"analise_critica": "Primeira leitura."})

        self.client.post(self.url, {"analise_critica": "Segunda leitura, mais completa."})

        self.estudo.refresh_from_db()
        self.assertEqual(
            self.estudo.veredito.analise_critica, "Segunda leitura, mais completa."
        )

    def test_editar_depois_da_liberacao_e_permitido_e_sinalizado(self):
        # A análise crítica amadurece; os números do veredito não mudam. Mas o
        # leitor precisa saber que o texto não é o do dia da assinatura.
        self.calcular()
        self.client.post(self.url, {"analise_critica": "", "veredito": "APROVADO"})
        self.client.post(reverse("liberar_estudo", args=[self.estudo.pk]))

        self.client.post(self.url, {"analise_critica": "Revisto após a auditoria interna."})

        self.estudo.refresh_from_db()
        self.assertTrue(self.estudo.veredito.analise_editada_apos_liberacao())
        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))
        self.assertContains(resposta, "depois da")

    def test_cada_edicao_vai_para_a_trilha(self):
        self.calcular()

        self.client.post(self.url, {"analise_critica": "Primeira."})
        self.client.post(self.url, {"analise_critica": "Segunda."})

        self.assertTrue(RegistroAuditoria.objects.filter(acao="escreveu a análise crítica").exists())
        self.assertTrue(RegistroAuditoria.objects.filter(acao="editou a análise crítica").exists())

    def test_texto_igual_nao_gera_registro(self):
        self.calcular()
        self.client.post(self.url, {"analise_critica": "Mesma coisa."})
        antes = RegistroAuditoria.objects.count()

        self.client.post(self.url, {"analise_critica": "Mesma coisa."})

        self.assertEqual(RegistroAuditoria.objects.count(), antes)

    def test_recalcular_nao_apaga_a_analise(self):
        # Recalcular substitui o retrato dos números. A leitura que o
        # responsável escreveu sobre o estudo não é um número.
        self.calcular()
        self.client.post(self.url, {"analise_critica": "Vale para este estudo."})

        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.analise_critica, "Vale para este estudo.")

    def test_laboratorio_alheio_nao_escreve(self):
        self.calcular()
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.post(self.url, {"analise_critica": "x"}).status_code, 404)


class TestRelatorio(TestCase):
    """O relatório impresso: sai de um cálculo congelado, ou não sai."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="responsavel", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.url = reverse("relatorio_estudo", args=[self.estudo.pk])

    def calcular(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.estudo.refresh_from_db()

    def test_sem_calculo_congelado_o_relatorio_nao_sai(self):
        # Imprimir rascunho com cara de documento é como um número errado entra
        # numa pasta de qualidade.
        resposta = self.client.get(self.url, follow=True)

        self.assertContains(resposta, "Calcular e congelar")
        self.assertContains(resposta, "sai de um cálculo congelado")

    def test_traz_rastreabilidade_resultados_e_veredito(self):
        self.calcular()

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        for parte in [
            "Relatório de validação de método analítico",
            "Especificação da qualidade analítica",
            "Rastreabilidade",
            "Precisão e exatidão",
            "Comparabilidade",
            "Conclusão / análise crítica",
            "Veredito",
        ]:
            self.assertContains(resposta, parte)

    def test_a_conclusao_escrita_aparece_no_relatorio(self):
        self.calcular()
        self.client.post(
            reverse("analise_estudo", args=[self.estudo.pk]),
            {"analise_critica": "Controle no fim da validade; repetido com lote novo."},
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Controle no fim da validade")

    def test_sem_conclusao_o_relatorio_diz_que_falta(self):
        self.calcular()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Nenhuma conclusão registrada")

    def test_nao_traz_o_veredito_por_nivel(self):
        self.calcular()

        resposta = self.client.get(self.url)

        self.assertNotContains(resposta, "Veredito por nível")

    def test_nao_traz_passing_bablok(self):
        self.calcular()

        self.assertNotContains(self.client.get(self.url), "Passing")

    def test_o_botao_do_relatorio_so_aparece_com_veredito(self):
        antes = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))
        self.assertNotContains(antes, reverse("relatorio_estudo", args=[self.estudo.pk]))

        self.calcular()

        depois = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))
        self.assertContains(depois, reverse("relatorio_estudo", args=[self.estudo.pk]))

    def test_laboratorio_alheio_nao_imprime(self):
        self.calcular()
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_o_retrato_guarda_o_lote_do_reagente_que_mediu(self):
        # O objeto do banco não cabe em JSON, e guardá-lo por referência não
        # serviria: o retrato precisa dizer qual lote mediu mesmo que o cadastro
        # mude depois. Foi por aqui que um Reagente vazou para dentro do
        # snapshot e derrubou a ação de calcular — o fixture de teste não tinha
        # reagente nenhum, então o caminho nunca era percorrido.
        self.calcular()

        reagentes = self.estudo.veredito.detalhamento["reagentes"]
        self.assertEqual(reagentes["teste"]["lote"], "R1")
        self.assertEqual(reagentes["teste"]["intervalo_analitico"], "0,1 a 12")

    def test_o_retrato_inteiro_e_serializavel(self):
        import json

        self.calcular()

        json.dumps(self.estudo.veredito.detalhamento)  # não pode levantar

    def test_o_relatorio_cita_o_intervalo_analitico_do_kit(self):
        # O rótulo perdeu o "(teste)": o intervalo mora dentro do cartão do
        # sistema a que pertence, e o cartão já diz qual é.
        self.calcular()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Intervalo analítico")
        self.assertContains(resposta, "lote R1")
        corpo = resposta.content.decode()
        cartao_teste = corpo.index("Sistema em teste")
        cartao_comparacao = corpo.index("Sistema de comparação")
        intervalo = corpo.index("Intervalo analítico")
        self.assertLess(cartao_teste, intervalo)
        self.assertLess(intervalo, cartao_comparacao)


def pytest_aprox(valor, casas=6):
    """Compara ponto flutuante sem arrastar o pytest para os testes do Django."""
    class Aproximado:
        def __eq__(self, outro):
            return round(outro - valor, casas) == 0

        def __repr__(self):
            return f"~{valor}"

    return Aproximado()


class TestRazaoDasMediasConclui(TestCase):
    """A comparação com o bias máximo precisa terminar numa palavra.

    Imprimir "6,68%" ao lado de "[Bias máximo 6,00%]" e deixar o leitor
    concluir sozinho é pior do que não mostrar — ainda mais quando o veredito
    final, que vem de outra medida, diz APROVADO logo abaixo.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)

    def apertar_o_bias(self, valor: str):
        ficha = self.estudo.especificacao
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = Decimal(valor)
        ficha.save()

    def test_a_razao_dentro_do_limite_e_marcada_como_aprovada(self):
        # O fixture tem o método novo lendo 2% acima, contra um limite de 6%.
        resultado = servicos.calcular(self.estudo)["comparabilidade"]

        self.assertEqual(resultado["razao_das_medias"]["desvio_pct"], pytest_aprox(2.0))
        self.assertEqual(resultado["razao_avaliacao"]["status"], "APROVADO")

    def test_a_razao_acima_do_limite_e_marcada_como_reprovada(self):
        self.apertar_o_bias("1.00")

        resultado = servicos.calcular(self.estudo)["comparabilidade"]

        self.assertGreater(abs(resultado["razao_das_medias"]["desvio_pct"]), resultado["bias_maximo_pct"])
        self.assertEqual(resultado["razao_avaliacao"]["status"], "REPROVADO")

    def test_sem_limite_na_ficha_a_comparacao_fica_indeterminada(self):
        ficha = self.estudo.especificacao
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = None
        ficha.save()

        resultado = servicos.calcular(self.estudo)["comparabilidade"]

        self.assertEqual(resultado["razao_avaliacao"]["status"], "INDETERMINADO")

    def test_a_conclusao_aparece_na_tela(self):
        self.apertar_o_bias("1.00")

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Razão das médias")
        self.assertContains(resposta, "estado--REPROVADO")


class TestVereditoDecididoPorPessoa(TestCase):
    """O programa mede; quem julga é o responsável.

    O motor compara cada indicador com o seu limite e diz o que ficou dentro e
    o que ficou fora. Transformar isso automaticamente num "método aprovado" é
    atribuir ao programa um julgamento que é do laboratório — e um relatório
    que afirma "aprovado" sem nome de quem aprovou não se sustenta numa
    auditoria. Este bloco guarda essa separação.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.analista = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.responsavel = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.analista)
        self.calcular_url = reverse("concluir_estudo", args=[self.estudo.pk])
        self.analise_url = reverse("analise_estudo", args=[self.estudo.pk])
        self.liberar_url = reverse("liberar_estudo", args=[self.estudo.pk])
        self.tela_url = reverse("resultado_estudo", args=[self.estudo.pk])

    def calcular(self, como=None):
        self.client.force_login(como or self.responsavel)
        self.client.post(self.calcular_url)
        self.estudo.refresh_from_db()

    def test_congelar_nao_aprova_nem_reprova_o_estudo(self):
        self.calcular()

        self.assertEqual(self.estudo.veredito.resultado, Veredito.PENDENTE)
        self.assertFalse(self.estudo.veredito.decidido())

    def test_o_calculo_continua_sendo_guardado_como_evidencia(self):
        # Tirar o veredito automático não é deixar de calcular: a leitura dos
        # limites continua no retrato, para o responsável decidir olhando para
        # ela — e para uma auditoria conferir o que ele viu.
        self.calcular()

        self.assertEqual(self.estudo.veredito.leitura_do_motor(), Veredito.APROVADO)

    def test_a_pessoa_marca_o_veredito_e_fica_registrado_quem_foi(self):
        self.calcular()

        self.client.post(self.analise_url, {"analise_critica": "", "veredito": "APROVADO"})

        self.estudo.refresh_from_db()
        veredito = self.estudo.veredito
        self.assertEqual(veredito.resultado, Veredito.APROVADO)
        self.assertEqual(veredito.decidido_por, self.responsavel)
        self.assertIsNotNone(veredito.decidido_em)

    def test_pode_reprovar_um_estudo_que_passou_em_todos_os_limites(self):
        # É o caso que justifica o veredito manual existir.
        self.calcular()

        self.client.post(
            self.analise_url,
            {"analise_critica": "Reagente com lote em recall.", "veredito": "REPROVADO"},
        )

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.resultado, Veredito.REPROVADO)
        self.assertEqual(self.estudo.veredito.leitura_do_motor(), Veredito.APROVADO)
        self.assertTrue(self.estudo.veredito.decisao_contraria_ao_calculo())

    def test_decidir_contra_os_limites_sem_justificar_gera_aviso(self):
        self.calcular()

        resposta = self.client.post(
            self.analise_url, {"analise_critica": "", "veredito": "REPROVADO"}, follow=True
        )

        self.assertContains(resposta, "oposto do que os limites apontaram")

    def test_veredito_invalido_e_recusado(self):
        self.calcular()

        resposta = self.client.post(
            self.analise_url, {"analise_critica": "", "veredito": "TALVEZ"}, follow=True
        )

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.resultado, Veredito.PENDENTE)
        self.assertContains(resposta, "Marque uma das duas caixas")

    def test_nao_libera_relatorio_sem_veredito_marcado(self):
        # Sem esta trava o documento assinado sairia dizendo "aguardando a
        # decisão do responsável" no lugar do veredito.
        self.calcular()

        resposta = self.client.post(self.liberar_url, follow=True)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)
        self.assertContains(resposta, "Marque o veredito antes de liberar")

    def test_recalcular_devolve_o_veredito_para_pendente(self):
        # A decisão foi tomada sobre os números antigos; recalcular troca os
        # números. Manter o "aprovado" seria assinar o que ninguém leu.
        self.calcular()
        self.client.post(
            self.analise_url, {"analise_critica": "Tudo certo.", "veredito": "APROVADO"}
        )

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.resultado, Veredito.PENDENTE)
        self.assertIsNone(self.estudo.veredito.decidido_por)
        # O texto, ao contrário da decisão, atravessa o recálculo.
        self.assertEqual(self.estudo.veredito.analise_critica, "Tudo certo.")

    def test_relatorio_liberado_nao_muda_de_veredito(self):
        self.calcular()
        self.client.post(self.analise_url, {"analise_critica": "", "veredito": "APROVADO"})
        self.client.post(self.liberar_url)

        resposta = self.client.post(
            self.analise_url, {"analise_critica": "", "veredito": "REPROVADO"}, follow=True
        )

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.veredito.resultado, Veredito.APROVADO)
        self.assertContains(resposta, "já foi assinado")

    def test_a_decisao_vai_para_a_trilha_de_auditoria(self):
        self.calcular()

        self.client.post(self.analise_url, {"analise_critica": "", "veredito": "REPROVADO"})

        registro = RegistroAuditoria.objects.filter(acao="decidiu o veredito").first()
        self.assertIsNotNone(registro)
        self.assertEqual(registro.usuario, self.responsavel)
        self.assertEqual(registro.detalhe["veredito"], "REPROVADO")
        self.assertEqual(registro.detalhe["leitura_do_motor"], "APROVADO")
        self.assertTrue(registro.detalhe["contraria_o_calculo"])

    def test_a_tela_mostra_as_duas_caixas_e_nao_um_veredito_automatico(self):
        self.calcular()

        resposta = self.client.get(self.tela_url)

        self.assertContains(resposta, "Estudo Aprovado")
        self.assertContains(resposta, "Estudo Reprovado")
        self.assertContains(resposta, "Aguardando a decisão do responsável")

    def test_o_quadro_diz_que_falta_decidir(self):
        self.calcular()

        resposta = self.client.get(reverse("quadro"))

        self.assertContains(resposta, "A DECIDIR")
        self.assertContains(resposta, "Decidir o veredito")


class TestCarimboDoMotorForaDaVista(TestCase):
    """A data de congelamento e a versão do motor saíram da tela e do relatório.

    Continuam gravadas — são o que permite rastrear um recálculo divergente
    depois de uma atualização do sistema — mas não são informação de leitura
    para o laboratório nem para o cliente que recebe o PDF.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.responsavel = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.responsavel)
        self.client.force_login(self.responsavel)
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.client.post(
            reverse("analise_estudo", args=[self.estudo.pk]),
            {"analise_critica": "Conferido.", "veredito": "APROVADO"},
        )
        self.estudo.refresh_from_db()

    def test_a_tela_de_resultado_nao_carimba_o_motor(self):
        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        corpo = resposta.content.decode()
        self.assertNotIn("Congelado em", corpo)
        self.assertNotIn("Motor de cálculo", corpo)
        self.assertNotIn(VERSAO_MOTOR, corpo)

    def test_o_relatorio_nao_carimba_o_motor(self):
        resposta = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        corpo = resposta.content.decode()
        self.assertNotIn("Congelado em", corpo)
        self.assertNotIn("Motor de cálculo", corpo)
        self.assertNotIn("Versão do motor", corpo)
        self.assertNotIn(VERSAO_MOTOR, corpo)

    def test_a_versao_continua_gravada_para_auditoria(self):
        self.assertEqual(self.estudo.veredito.versao_motor, VERSAO_MOTOR)

    def test_o_relatorio_traz_o_veredito_depois_da_conclusao(self):
        resposta = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        corpo = resposta.content.decode()
        conclusao = corpo.index("Conclusão / análise crítica")
        veredito = corpo.index('<div class="veredito-final">')
        self.assertLess(conclusao, veredito)

    def test_o_relatorio_diz_quem_decidiu(self):
        resposta = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Estudo aprovado")
        self.assertContains(resposta, "Decidido por")


class TestLinhaDaExatidao(TestCase):
    """A linha de exatidão precisa se explicar sozinha.

    Quatro perguntas, sem calculadora: quanto deu e para que lado, contra quais
    dois números, qual é o teto e se passou.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.client.force_login(self.usuario)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_bias_negativo_aparece_com_sinal_e_com_a_palavra(self):
        # Réplicas em torno de 1,30 contra um grupo de pares em 1,40.
        self.nivel.media_interlaboratorial = Decimal("1.4000")
        self.nivel.provedor_interlaboratorial = "Controllab EQ"
        self.nivel.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "bias negativo")
        self.assertNotContains(resposta, "bias positivo")
        # Sinal de menos tipográfico, o mesmo da conta escrita ao lado — e não
        # o hífen do teclado, que deixava dois traços diferentes na mesma linha.
        self.assertContains(resposta, "−6,07%")

    def test_bias_positivo_aparece_com_sinal_e_com_a_palavra(self):
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "bias positivo")
        self.assertNotContains(resposta, "bias negativo")
        self.assertContains(resposta, "+9,58%")

    def test_a_coluna_mostra_os_dois_valores_comparados(self):
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Comparação")
        self.assertNotContains(resposta, "Comparado com")
        self.assertContains(resposta, "média das réplicas")
        self.assertContains(resposta, "média interlaboratorial")
        self.assertContains(resposta, "1.2000")

    def test_mostra_o_limite_e_a_situacao_da_exatidao(self):
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "bias máximo")
        self.assertContains(resposta, "estado--REPROVADO")

    def test_o_relatorio_impresso_diz_o_mesmo_que_a_tela(self):
        # A tela e o relatório são o mesmo dado lido por gente diferente. Foi
        # exatamente aqui que a mudança anterior escapou: a linha entrou na tela
        # e o documento impresso — o que sai do laboratório — ficou para trás.
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.provedor_interlaboratorial = "Controllab EQ"
        self.nivel.save()
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        relatorio = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        corpo = relatorio.content.decode()
        self.assertNotIn("Comparado com", corpo)
        self.assertIn("Comparação", corpo)
        self.assertIn("+9,58%", corpo)
        self.assertIn("bias positivo", corpo)
        self.assertIn("média das réplicas vs.", corpo)
        self.assertIn("bias máximo", corpo)

    def test_sem_limite_de_bias_a_celula_diz_que_falta_e_nao_some(self):
        # Antes, quando o indicador não existia, a linha perdia duas colunas e
        # a tabela saía torta — o limite simplesmente sumia da tela.
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()
        ficha = self.estudo.especificacao
        # O bias é derivado do erro total: para não haver limite nenhum, os dois
        # precisam sair. Zerar só um deixa o outro sustentando a conta.
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = None
        ficha.erro_total_maximo_pct = None
        ficha.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "sem limite")
        self.assertContains(resposta, "estado--INDETERMINADO")


class TestOrientacaoParaSalvarEmPDF(TestCase):
    """A tela do relatório precisa dizer como o arquivo sai.

    O programa não gera PDF no servidor: o botão abre a caixa de impressão do
    navegador. Quem aceita o destino que já estava selecionado no Windows pode
    sair com um .xps, que o sistema não abre mais — e conclui que o relatório
    está quebrado. A instrução nomeia o destino certo em vez de só pedir para
    escolher um, e some na impressão, onde seria ruído dentro do documento.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.responsavel = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.responsavel)
        self.client.force_login(self.responsavel)
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.url = reverse("relatorio_estudo", args=[self.estudo.pk])

    def test_nomeia_o_destino_a_escolher(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Salvar como PDF")
        self.assertContains(resposta, "Microsoft Print to PDF")

    def test_avisa_sobre_o_destino_que_gera_arquivo_que_nao_abre(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "XPS")

    def test_o_botao_nao_promete_um_download(self):
        # "Gerar PDF" prometia arquivo e entregava um diálogo.
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Salvar em PDF")
        self.assertNotContains(resposta, "Gerar PDF")

    def test_a_orientacao_nao_entra_no_papel(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, ".comandos, .recados, .como-salvar { display: none !important; }")


class TestExatidaoNoModuloDePrecisao(TestCase):
    """A exatidão contra o grupo de pares pertence ao estudo de precisão.

    O laboratório lança as réplicas, digita a média do mesmo lote no boletim do
    programa interlaboratorial e o bias sai daí — sem amostra pareada nenhuma.
    O motor exigia o módulo de comparabilidade para avaliá-lo, então quem
    contratou só precisão via o percentual calculado na tela e, na coluna do
    limite, "sem limite definido": o número aparecia sem veredito, que é a pior
    forma de mostrá-lo num relatório de validação.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab P", "22.222.222/0001-22")
        self.laboratorio.assinaturas.all().delete()
        Assinatura.objects.create(
            laboratorio=self.laboratorio, modulo=Assinatura.PRECISAO
        )
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.estudo.modulo = Assinatura.PRECISAO
        self.estudo.save()

        self.nivel = self.estudo.niveis.get(numero=1)
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.provedor_interlaboratorial = "Controllab EQ"
        self.nivel.save()

        self.client.force_login(self.usuario)

    def test_o_bias_maximo_da_ficha_e_o_limite_da_exatidao(self):
        contexto = servicos.calcular(self.estudo)
        item = contexto["precisao"][0]

        self.assertEqual(item["origem_do_bias"], servicos.BIAS_INTERLABORATORIAL)
        self.assertIsNotNone(item["indicador_bias"])
        self.assertEqual(
            Decimal(str(item["indicador_bias"]["limite_pct"])),
            self.estudo.especificacao.bias_maximo_pct,
        )

    def test_a_tela_mostra_o_limite_e_a_situacao(self):
        resposta = self.client.get(
            reverse("resultado_estudo", args=[self.estudo.pk])
        )

        corpo = resposta.content.decode()
        self.assertNotIn("sem limite", corpo)
        self.assertIn("bias máximo", corpo)
        # Réplicas em torno de 1,315 contra pares em 1,200: passa dos 6%.
        self.assertIn("estado--REPROVADO", corpo)

    def test_o_relatorio_mostra_o_limite_e_a_situacao(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        resposta = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        )

        corpo = resposta.content.decode()
        self.assertNotIn("sem limite definido", corpo)
        self.assertIn("bias máximo", corpo)

    def test_o_erro_total_continua_sendo_do_pacote_completo(self):
        # A exatidão entrou; o erro total não. São coisas diferentes, e essa é
        # uma decisão comercial, não analítica.
        contexto = servicos.calcular(self.estudo)
        item = contexto["precisao"][0]

        indicadores = [i["indicador"] for i in item["avaliacao"]["indicadores"]]
        self.assertIn("bias", indicadores)
        self.assertNotIn("erro total", indicadores)


class TestGradeQualitativa(TestCase):
    """A tela de lançamento qualitativo.

    Até agora o módulo EP12 só podia ser preenchido uma amostra por vez pelo
    painel administrativo, e o que era lançado nem entrava na contagem do
    estudo — o programa dizia "Sem dados lançados" com trinta amostras no banco
    e recusava calcular. Este bloco guarda a grade e a contagem.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab Q", "33.333.333/0001-33")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.estudo.tipo = Estudo.QUALITATIVO
        self.estudo.save()
        self.estudo.niveis.all().delete()
        self.estudo.amostras_comparacao.all().delete()
        self.url = reverse("qualitativas_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def _linhas(self, quantidade, referencia="Reagente", teste="Reagente"):
        dados = {"total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS}
        for posicao in range(1, quantidade + 1):
            dados[f"amostra_{posicao}_id"] = f"AM-{posicao:03d}"
            dados[f"amostra_{posicao}_referencia"] = referencia
            dados[f"amostra_{posicao}_teste"] = teste
        return dados

    def test_a_grade_abre_com_o_tamanho_usual(self):
        resposta = self.client.get(self.url)

        self.assertEqual(
            resposta.context["grade"]["total"], servicos.MINIMO_AMOSTRAS_QUALITATIVAS
        )

    def test_grava_as_amostras_lancadas(self):
        self.client.post(self.url, self._linhas(3))

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 3)
        amostra = self.estudo.amostras_qualitativas.get(identificacao="AM-001")
        self.assertTrue(amostra.resultado_referencia)
        self.assertTrue(amostra.resultado_teste)

    def test_aceita_as_grafias_que_o_laboratorio_usa(self):
        dados = {"total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS}
        escritas = [
            ("reagente", "POSITIVO"),
            ("P", "1"),
            ("não reagente", "NEGATIVO"),
            ("N", "0"),
        ]
        for posicao, (referencia, teste) in enumerate(escritas, start=1):
            dados[f"amostra_{posicao}_id"] = f"AM-{posicao:03d}"
            dados[f"amostra_{posicao}_referencia"] = referencia
            dados[f"amostra_{posicao}_teste"] = teste

        self.client.post(self.url, dados)

        gravadas = list(self.estudo.amostras_qualitativas.order_by("identificacao"))
        self.assertEqual(len(gravadas), 4)
        self.assertEqual(
            [(a.resultado_referencia, a.resultado_teste) for a in gravadas],
            [(True, True), (True, True), (False, False), (False, False)],
        )

    def test_indeterminado_e_recusado_e_nomeado(self):
        # Não é reagente nem não reagente. Empurrá-lo para um dos lados
        # falsificaria a tabela 2×2.
        dados = {
            "total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS,
            "amostra_1_id": "AM-001",
            "amostra_1_referencia": "indeterminado",
            "amostra_1_teste": "Reagente",
        }

        resposta = self.client.post(self.url, dados, follow=True)

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 0)
        self.assertContains(resposta, "não é reagente nem não reagente")

    def test_uma_linha_ruim_nao_derruba_as_outras(self):
        dados = self._linhas(5)
        dados["amostra_3_referencia"] = "talvez"

        self.client.post(self.url, dados)

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 4)

    def test_meia_amostra_e_erro_e_nao_meia_linha(self):
        dados = {
            "total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS,
            "amostra_1_id": "AM-001",
            "amostra_1_referencia": "Reagente",
            "amostra_1_teste": "",
        }

        resposta = self.client.post(self.url, dados, follow=True)

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 0)
        self.assertContains(resposta, "resultado nos dois métodos")

    def test_codigo_repetido_e_aceito(self):
        # Mesma regra da grade de amostras pareadas. Duas grades irmãs
        # recusando dados diferentes seria a pior das opções.
        dados = self._linhas(2)
        dados["amostra_2_id"] = "AM-001"

        self.client.post(self.url, dados)

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 2)

    def test_linha_em_branco_apaga_a_amostra(self):
        self.client.post(self.url, self._linhas(2))

        dados = self._linhas(2)
        dados["amostra_2_referencia"] = ""
        dados["amostra_2_teste"] = ""
        self.client.post(self.url, dados)

        self.assertEqual(self.estudo.amostras_qualitativas.count(), 1)

    def test_a_grade_recusa_estudo_quantitativo(self):
        self.estudo.tipo = Estudo.QUANTITATIVO
        self.estudo.save()

        resposta = self.client.get(self.url, follow=True)

        self.assertContains(resposta, "Este estudo é quantitativo")

    def test_estudo_liberado_nao_aceita_lancamento(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save()

        resposta = self.client.get(self.url, follow=True)

        self.assertContains(resposta, "não aceita alteração de dado bruto")


class TestEstudoQualitativoAndaNoProgramaTodo(TestCase):
    """O estudo qualitativo precisa chegar ao fim como os outros.

    Antes ele não chegava a lugar nenhum: as amostras não eram contadas, o card
    ficava parado no rascunho dizendo "Sem dados lançados" e o cálculo era
    recusado. O motor EP12 existia e não tinha como ser usado.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab Q", "33.333.333/0001-33")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.estudo.tipo = Estudo.QUALITATIVO
        self.estudo.save()
        self.estudo.niveis.all().delete()
        self.estudo.amostras_comparacao.all().delete()
        self.client.force_login(self.usuario)

        for indice in range(1, 41):
            positivo = indice % 2 == 0
            AmostraQualitativa.objects.create(
                estudo=self.estudo,
                identificacao=f"AM-{indice:03d}",
                resultado_referencia=positivo,
                resultado_teste=positivo,
            )

    def test_as_amostras_entram_na_contagem(self):
        andamento = self.estudo.progresso()

        self.assertEqual(andamento["qualitativo_feita"], 40)
        self.assertTrue(andamento["iniciado"])
        self.assertTrue(andamento["completo"])

    def test_o_card_manda_para_a_grade_qualitativa(self):
        self.assertEqual(self.estudo.tela_da_proxima_acao(), "qualitativas_estudo")
        self.assertEqual(self.estudo.proxima_acao(), "Calcular agora")
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_PRONTO)

    def test_o_estudo_pode_ser_calculado_e_liberado(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.client.post(
            reverse("analise_estudo", args=[self.estudo.pk]),
            {"analise_critica": "Concordância total na amostragem.", "veredito": "APROVADO"},
        )
        self.client.post(reverse("liberar_estudo", args=[self.estudo.pk]))

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.resultado, "APROVADO")

    def test_o_relatorio_sai(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        resposta = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Sensibilidade")

    def test_uma_categoria_escassa_vira_ressalva(self):
        # Sensibilidade e especificidade são duas proporções estimadas em
        # separado; o que importa é a contagem de cada lado, não o total.
        sobram = self.estudo.amostras_qualitativas.filter(resultado_referencia=True)[:5]
        self.estudo.amostras_qualitativas.filter(resultado_referencia=True).exclude(
            pk__in=[a.pk for a in sobram]
        ).delete()

        avisos = servicos.calcular(self.estudo)["avisos"]

        self.assertTrue(any("positivas na referência" in aviso for aviso in avisos))
        self.assertTrue(any("sensibilidade" in aviso for aviso in avisos))


class TestIntervaloDeReferenciaSoNaValidacao(TestCase):
    """O intervalo de referência é da metodologia, não do analito.

    Dois imunoensaios de FT4 imprimem faixas diferentes no laudo. Um valor único
    no analito servia de reserva para os dois lados do estudo — e classificar os
    resultados dos dois métodos pela mesma faixa esconde exatamente o desacordo
    que a concordância clínica existe para medir.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)

    def test_o_analito_nao_guarda_mais_intervalo(self):
        campos = {campo.name for campo in Mensurando._meta.get_fields()}

        self.assertNotIn("referencia_inferior", campos)
        self.assertNotIn("referencia_superior", campos)

    def test_sem_intervalo_no_estudo_a_concordancia_clinica_nao_e_avaliada(self):
        # E o relatório diz isso, em vez de usar uma faixa herdada que não é de
        # nenhum dos dois métodos.
        contexto = servicos.calcular(self.estudo)

        clinica = contexto["comparabilidade"]["clinica"]
        self.assertEqual(clinica["avaliadas"], 0)
        self.assertIsNone(clinica["concordancia_pct"])
        # E o relatório registra a ressalva, em vez de omitir a medida.
        self.assertTrue(
            any("clínica" in aviso for aviso in contexto["avisos"]),
            contexto["avisos"],
        )

    def test_o_intervalo_do_estudo_e_o_que_vale(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.9")
        self.estudo.referencia_comparacao_superior = Decimal("1.7")
        self.estudo.save()

        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.9"), Decimal("1.7"))
        )

    def test_a_tela_de_configuracoes_mostra_o_uso_do_analito(self):
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("configuracoes"))

        self.assertContains(resposta, "1 validação")
        self.assertNotContains(resposta, "Sem intervalo de referência")


class TestLimiteAbsolutoNaTela(TestCase):
    """A tela mostra o limite na escala em que ele foi escrito.

    Ficha de TSH com "6%, mas abaixo de 0,50 mU/L use ± 0,06 mU/L". No nível 1,
    de concentração 0,30, a tela imprimia "± 20,00% · bias máximo" — que é o
    limite absoluto convertido, sem dizer que era. Quem escreveu 6% na ficha lia
    20% na tela e concluía que o programa estava errado.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)

        ficha = self.estudo.especificacao
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = Decimal("6.00")
        ficha.bias_referencia = "50% do erro total do provedor"
        ficha.bias_limiar_absoluto = Decimal("2.0000")
        ficha.bias_maximo_absoluto = Decimal("0.0600")
        ficha.bias_referencia_absoluto = "para resultados ≤ 2,00, ± 0,06"
        ficha.save()

        # Alvo do grupo de pares abaixo do limiar: vale a regra absoluta.
        self.nivel = self.estudo.niveis.get(numero=1)
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()
        self.client.force_login(self.usuario)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_o_limite_aparece_na_unidade_de_medida(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "0,0600 ng/dL")
        self.assertContains(resposta, "regra absoluta")

    def test_a_conversao_aparece_nomeada_e_nao_sozinha(self):
        # 0,06 / 1,20 = 5,00%. O número pode aparecer, desde que dito o que é.
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "nesta concentração")
        self.assertContains(resposta, "para resultados ≤ 2,00")

    def test_a_regra_percentual_continua_em_porcentagem(self):
        self.nivel.media_interlaboratorial = Decimal("5.0000")
        self.nivel.save()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "&plusmn; 6,00%")
        self.assertNotContains(resposta, "regra absoluta")

    def test_o_relatorio_mostra_a_mesma_coisa(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        resposta = self.client.get(reverse("relatorio_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "0,0600 ng/dL")
        self.assertContains(resposta, "regra absoluta")


class TestConcentracaoQueResolveOLimite(TestCase):
    """O limite de aceitação não pode depender do resultado que ele julga.

    A regra do limite absoluto existe porque a concentração do MATERIAL é
    baixa. Com a média medida decidindo, o critério se mexia conforme a leitura:
    um controle de alvo 0,50 medido a 0,48 caía na regra absoluta e ganhava
    folga; medido a 0,51 caía na percentual. Um limite que depende do que se
    mediu não é critério de aceitação.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)

    def test_usa_a_media_do_grupo_de_pares_quando_informada(self):
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()

        item = servicos.calcular(self.estudo)["precisao"][0]

        self.assertAlmostEqual(item["concentracao"], 1.2, places=4)
        self.assertEqual(item["origem_da_concentracao"], "média interlaboratorial")

    def test_sem_alvo_do_grupo_volta_para_a_media_medida_e_diz_isso(self):
        item = servicos.calcular(self.estudo)["precisao"][0]

        self.assertAlmostEqual(item["concentracao"], item["estatistica"]["media"], places=4)
        self.assertEqual(item["origem_da_concentracao"], "média das réplicas")

    def test_a_leitura_do_metodo_nao_muda_mais_o_limite(self):
        # Mesmo material, mesma ficha: um método que lê alto e outro que lê
        # baixo têm de ser julgados pelo mesmo critério.
        ficha = self.estudo.especificacao
        ficha.bias_derivado = False
        ficha.bias_maximo_pct = Decimal("6.00")
        ficha.bias_limiar_absoluto = Decimal("1.5000")
        ficha.bias_maximo_absoluto = Decimal("0.0600")
        ficha.bias_referencia_absoluto = "abaixo de 1,50, ± 0,06"
        ficha.save()

        self.nivel.media_interlaboratorial = Decimal("1.4000")
        self.nivel.save()
        antes = servicos.calcular(self.estudo)["precisao"][0]["indicador_bias"]

        # As réplicas sobem 40%, atravessando o limiar. O limite não se mexe.
        for replica in Replica.objects.filter(nivel=self.nivel):
            replica.valor = replica.valor * Decimal("1.4")
            replica.save(update_fields=["valor"])

        depois = servicos.calcular(self.estudo)["precisao"][0]["indicador_bias"]

        self.assertEqual(antes["tipo_limite"], depois["tipo_limite"])
        self.assertEqual(antes["limite_absoluto"], depois["limite_absoluto"])
        self.assertEqual(antes["limite_pct"], depois["limite_pct"])

    def test_a_tela_diz_qual_concentracao_resolveu_o_limite(self):
        self.nivel.media_interlaboratorial = Decimal("1.2000")
        self.nivel.save()
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Limites resolvidos em")
        self.assertContains(resposta, "média interlaboratorial")


class TestTipografiaDoDocumentoImpresso(TestCase):
    """Garantias de paginação que ninguém nota até faltarem.

    Um relatório de validação é arquivado em papel e conferido linha a linha.
    Cabeçalho de tabela que não se repete na página seguinte, título sozinho no
    pé da folha e nível partido ao meio não são detalhes estéticos: são o que
    faz alguém conferir a coluna errada.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.corpo = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

    def test_toda_tabela_tem_cabecalho_que_se_repete(self):
        # Sem <thead>, a parte da tabela que cai na página seguinte chega sem
        # nome de coluna: números soltos numa folha de registro de qualidade.
        #
        # A folha de estilo cita "<thead>" num comentário, então a contagem
        # precisa olhar só o corpo do documento.
        import re

        corpo = re.sub(r"<style>.*?</style>", "", self.corpo, flags=re.S)
        self.assertGreater(corpo.count("<table"), 0)
        self.assertEqual(corpo.count("<table"), corpo.count("<thead>"))
        self.assertIn("display: table-header-group", self.corpo)

    def test_as_secoes_sao_numeradas_automaticamente(self):
        # Numa auditoria se aponta para "a seção 4", não para "aquela do meio".
        self.assertIn("counter-reset: secao", self.corpo)
        self.assertIn("counter-increment: secao", self.corpo)

    def test_titulo_nunca_fica_orfao_no_pe_da_pagina(self):
        self.assertIn("break-after: avoid", self.corpo)
        self.assertIn("orphans: 3", self.corpo)
        self.assertIn("widows: 3", self.corpo)

    def test_um_nivel_nao_parte_ao_meio(self):
        # A estatística das corridas e a avaliação que sai dela pertencem uma à
        # outra; metade numa página e metade na outra não se lê.
        self.assertIn('class="nivel-bloco"', self.corpo)
        self.assertIn(".nivel-bloco, .veredito-final, .assinatura { break-inside: avoid; }", self.corpo)

    def test_cada_sistema_analitico_leva_a_propria_metodologia(self):
        # Na grade corrida anterior, "Metodologia" aparecia duas vezes e podia
        # cair numa linha sozinha, longe do equipamento a que pertencia.
        self.assertIn("Sistema em teste", self.corpo)
        self.assertIn("Sistema de comparação", self.corpo)
        self.assertEqual(self.corpo.count('class="sistema"'), 2)

    def test_a_orientacao_de_impressao_nao_entra_no_papel(self):
        self.assertIn(
            ".comandos, .recados, .como-salvar { display: none !important; }", self.corpo
        )


class TestRelatorioQualitativoNaoImprimeCriterioQuantitativo(TestCase):
    """Um relatório de EP12 não é julgado por CV, bias e erro total.

    O documento imprimia "Desenho da precisão — 5 dias consecutivos, 5 réplicas
    por dia" num estudo sem réplica nenhuma, e a tabela de erro total, bias e
    imprecisão ao lado dos resultados — fazendo parecer que o método tinha sido
    avaliado contra limites que nunca entraram em conta nenhuma.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab Q", "33.333.333/0001-33")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.estudo.tipo = Estudo.QUALITATIVO
        self.estudo.save()
        self.estudo.niveis.all().delete()
        self.estudo.amostras_comparacao.all().delete()
        for indice in range(1, 41):
            positivo = indice % 2 == 0
            AmostraQualitativa.objects.create(
                estudo=self.estudo, identificacao=f"AM-{indice:03d}",
                resultado_referencia=positivo, resultado_teste=positivo,
            )
        self.client.force_login(self.usuario)
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.corpo = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

    def test_nao_descreve_um_desenho_de_precisao_que_nao_existiu(self):
        self.assertNotIn("Desenho da precisão", self.corpo)

    def test_nao_imprime_limites_de_metodo_quantitativo(self):
        self.assertNotIn("Erro total máximo", self.corpo)
        self.assertNotIn("Bias máximo", self.corpo)

    def test_diz_contra_o_que_o_metodo_foi_avaliado(self):
        self.assertIn("concordância com o método de referência", self.corpo)
        self.assertIn("Sensibilidade", self.corpo)

    def test_o_estudo_quantitativo_continua_trazendo_os_limites(self):
        # Noutro laboratório, com usuário próprio: o analito é único por
        # laboratório e este já tem um FT4 em soro, e um usuário só enxerga os
        # estudos do laboratório dele.
        outro = montar_laboratorio("Lab R", "44.444.444/0001-44")
        dono = Usuario.objects.create_user(
            username="rt.outro", password="senha-longa-de-teste",
            laboratorio=outro, funcao=Usuario.RESPONSAVEL,
        )
        quantitativo = montar_estudo(outro, dono)
        self.client.force_login(dono)
        self.client.post(reverse("concluir_estudo", args=[quantitativo.pk]))

        corpo = self.client.get(
            reverse("relatorio_estudo", args=[quantitativo.pk])
        ).content.decode()

        self.assertIn("Erro total máximo", corpo)
        self.assertIn("Desenho da precisão", corpo)


class TestAnexoDeDadosBrutos(TestCase):
    """O relatório carrega a prova, não só a conclusão.

    Um auditor consegue conferir se a conta bate; sem os dados brutos ele não
    tem como saber de onde vieram os números. E o que foi descartado precisa
    aparecer: uma medição excluída que some do documento é indistinguível de
    uma que nunca existiu.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

    def _relatorio(self):
        return self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

    def test_traz_as_replicas_de_cada_nivel_por_corrida(self):
        corpo = self._relatorio()

        self.assertIn("Anexo &mdash; dados brutos", corpo)
        self.assertIn("Corrida 1", corpo)
        primeira = self.estudo.niveis.get(numero=1).replicas.order_by("corrida", "sequencia").first()
        self.assertIn(f"{primeira.valor:.4f}".replace(".", ","), corpo)

    def test_traz_as_amostras_pareadas_com_os_dois_resultados(self):
        corpo = self._relatorio()

        amostra = self.estudo.amostras_comparacao.order_by("pk").first()
        self.assertIn(amostra.identificacao, corpo)
        self.assertIn(f"{amostra.valor_comparacao:.4f}".replace(".", ","), corpo)
        self.assertIn(f"{amostra.valor_teste:.4f}".replace(".", ","), corpo)

    def test_a_replica_descartada_aparece_com_a_justificativa(self):
        replica = self.estudo.niveis.get(numero=1).replicas.first()
        replica.excluida = True
        replica.justificativa_exclusao = "bolha na cubeta"
        replica.save()

        corpo = self._relatorio()

        self.assertIn("bolha na cubeta", corpo)
        self.assertIn("descartada", corpo)

    def test_a_amostra_descartada_aparece_com_a_justificativa(self):
        amostra = self.estudo.amostras_comparacao.first()
        amostra.excluida = True
        amostra.justificativa_exclusao = "amostra hemolisada"
        amostra.save()

        corpo = self._relatorio()

        self.assertIn("amostra hemolisada", corpo)

    def test_o_anexo_comeca_em_folha_propria(self):
        # É prova anexada ao documento assinado, não continuação dele.
        self.assertIn(".anexo { break-before: page;", self._relatorio())

    def test_o_descarte_nao_entra_no_calculo(self):
        # O anexo mostra a medição; a conta continua sem ela.
        antes = servicos.calcular(self.estudo)["comparabilidade"]["n"]
        amostra = self.estudo.amostras_comparacao.first()
        amostra.excluida = True
        amostra.justificativa_exclusao = "amostra hemolisada"
        amostra.save()

        depois = servicos.calcular(self.estudo)["comparabilidade"]["n"]

        self.assertEqual(depois, antes - 1)
        self.assertIn(amostra.identificacao, self._relatorio())


class TestRecorteDaRegressao(TestCase):
    """Examinar uma faixa de concentração em separado, com registro.

    O r da regressão depende da amplitude das amostras: uma amostra muito acima
    das outras aumenta a variância de X e empurra o r para 1 sozinha. A prática
    do laboratório era apagar os extremos e olhar de novo — o que funciona e não
    deixa rastro. O recorte é a mesma leitura, registrada.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.tela = reverse("resultado_estudo", args=[self.estudo.pk])
        self.url = reverse("recorte_estudo", args=[self.estudo.pk])

        valores = [float(a.valor_comparacao) for a in self.estudo.amostras_comparacao.all()]
        self.piso, self.teto = min(valores), max(valores)
        self.meio = (self.piso + self.teto) / 2

    # --- O cálculo -----------------------------------------------------------

    def test_a_faixa_passa_pelo_mesmo_motor_do_estudo_inteiro(self):
        # Sem aritmética própria: um recorte com regressão própria seria uma
        # segunda implementação, e a que acabaria no relatório seria a segunda.
        recorte = servicos.calcular_recorte(self.estudo, self.piso, self.teto)
        inteiro = servicos.calcular(self.estudo)["comparabilidade"]

        self.assertEqual(recorte["comparabilidade"]["n"], inteiro["n"])
        self.assertAlmostEqual(
            recorte["comparabilidade"]["deming"]["inclinacao"],
            inteiro["deming"]["inclinacao"],
            places=9,
        )

    def test_a_faixa_recorta_as_amostras(self):
        recorte = servicos.calcular_recorte(self.estudo, self.piso, self.meio)

        self.assertLess(recorte["comparabilidade"]["n"], recorte["n_total"])
        self.assertTrue(
            all(self.piso <= x <= self.meio for x in recorte["comparabilidade"]["valores_comparacao"])
        )

    def test_faixa_vazia_diz_que_esta_vazia_em_vez_de_quebrar(self):
        recorte = servicos.calcular_recorte(self.estudo, self.teto + 1000, self.teto + 2000)

        self.assertFalse(recorte["comparabilidade"]["tem_dados"])
        self.assertIn("faixa", recorte["comparabilidade"]["motivo"])

    def test_faixa_com_poucas_amostras_e_sinalizada(self):
        recorte = servicos.calcular_recorte(self.estudo, self.piso, self.piso + 0.01)

        self.assertTrue(recorte["poucas_amostras"])

    # --- O gráfico -----------------------------------------------------------

    def test_o_grafico_da_faixa_mostra_a_nuvem_inteira(self):
        # Mostrar só os pontos da faixa esconderia justamente o que motivou o
        # recorte.
        recorte = servicos.calcular_recorte(self.estudo, self.piso, self.meio)

        self.assertIn("fora da faixa examinada", recorte["grafico"])

    def test_o_grafico_da_tela_carrega_a_escala_para_o_arrasto(self):
        resposta = self.client.get(self.tela)

        self.assertContains(resposta, 'data-selecionavel="regressao"')
        self.assertContains(resposta, "data-x-minimo=")
        self.assertContains(resposta, "data-pixel-inicio=")

    # --- Salvar --------------------------------------------------------------

    def _salvar(self, **campos):
        dados = {
            "minimo": str(self.piso),
            "maximo": str(self.meio),
            "rotulo": "Faixa baixa",
            "justificativa": "A amostra do topo domina a reta do estudo inteiro.",
        }
        dados.update(campos)
        return self.client.post(self.url, dados, follow=True)

    def test_salva_com_nome_e_motivo(self):
        self._salvar()

        recorte = self.estudo.recortes.get()
        self.assertEqual(recorte.rotulo, "Faixa baixa")
        self.assertEqual(recorte.criado_por, self.usuario)
        self.assertIn("domina a reta", recorte.justificativa)

    def test_o_motivo_e_opcional(self):
        # O motivo continua sendo a coisa mais útil do recorte, mas exigi-lo
        # travava o uso corrente: o laboratório examina três ou quatro faixas
        # antes de saber qual vale a pena registrar.
        self._salvar(justificativa="")

        self.assertEqual(self.estudo.recortes.count(), 1)
        self.assertEqual(self.estudo.recortes.get().justificativa, "")

    def test_recorte_sem_motivo_nao_imprime_caixa_vazia(self):
        self._salvar(justificativa="")
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        corpo = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

        self.assertIn("Recorte &mdash; Faixa baixa", corpo)
        self.assertNotIn('class="motivo-recorte"', corpo)

    def test_recusa_recorte_sem_nome(self):
        resposta = self._salvar(rotulo="")

        self.assertEqual(self.estudo.recortes.count(), 0)
        self.assertContains(resposta, "Dê um nome ao recorte")

    def test_recusa_faixa_invertida(self):
        resposta = self._salvar(minimo=str(self.teto), maximo=str(self.piso))

        self.assertEqual(self.estudo.recortes.count(), 0)
        self.assertContains(resposta, "deve ser maior que o inferior")

    def test_recusa_faixa_sem_amostra(self):
        resposta = self._salvar(
            minimo=str(self.teto + 1000), maximo=str(self.teto + 2000)
        )

        self.assertEqual(self.estudo.recortes.count(), 0)
        self.assertContains(resposta, "Nenhuma amostra pareada cai nesta faixa")

    def test_relatorio_assinado_nao_recebe_recorte_novo(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))
        self.client.post(
            reverse("analise_estudo", args=[self.estudo.pk]),
            {"analise_critica": "", "veredito": "APROVADO"},
        )
        self.client.post(reverse("liberar_estudo", args=[self.estudo.pk]))

        resposta = self._salvar()

        self.assertEqual(self.estudo.recortes.count(), 0)
        self.assertContains(resposta, "já foi assinado")

    def test_salvar_e_remover_vao_para_a_trilha(self):
        self._salvar()
        recorte = self.estudo.recortes.get()

        self.client.post(self.url, {"acao": "remover", "recorte": recorte.pk})

        self.assertEqual(self.estudo.recortes.count(), 0)
        acoes = set(RegistroAuditoria.objects.values_list("acao", flat=True))
        self.assertIn("acrescentou um recorte da regressão", acoes)
        self.assertIn("removeu um recorte da regressão", acoes)

    # --- No relatório --------------------------------------------------------

    def test_o_recorte_acompanha_o_grafico_inteiro_e_nao_o_substitui(self):
        self._salvar()
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        corpo = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

        completo = corpo.index("Comparação de métodos — regressão linear simples")
        recorte = corpo.index("Recorte &mdash; Faixa baixa")
        self.assertLess(completo, recorte)
        self.assertIn("domina a reta", corpo)
        self.assertIn("Estudo inteiro", corpo)

    def test_sem_recorte_salvo_o_relatorio_nao_muda(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        corpo = self.client.get(
            reverse("relatorio_estudo", args=[self.estudo.pk])
        ).content.decode()

        self.assertNotIn("Recorte &mdash;", corpo)

    # --- A tela de exame -----------------------------------------------------

    def test_a_tela_examina_a_faixa_pedida_na_barra_de_endereco(self):
        resposta = self.client.get(
            f"{self.tela}?faixa_min={self.piso}&faixa_max={self.meio}"
        )

        self.assertIsNotNone(resposta.context["recorte_em_exame"])
        self.assertContains(resposta, "Voltar ao gráfico inteiro")

    def test_faixa_ilegivel_na_barra_de_endereco_e_ignorada(self):
        resposta = self.client.get(f"{self.tela}?faixa_min=abc&faixa_max=xyz")

        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.context.get("recorte_em_exame"))


class TestDesfazerUltimaGravacao(TestCase):
    """O passo atrás depois de um salvar que apagou ou trocou dado bruto.

    Um retrato do estado anterior fica na sessão de quem gravou e vale por uma
    desfeita só. Duas regras carregam o resto:

    - só gravação destrutiva guarda retrato — digitar réplica nova não precisa
      de desfazer, e oferecer o botão sempre viraria ruído;
    - toda gravação passa pelo guardador, que substitui o retrato ou o joga
      fora. Retrato velho restauraria um estado que já não é o anterior, e
      apagaria justamente o que foi digitado depois.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.replicas = self.estudo.niveis.get(numero=1).replicas.count()
        self.grade = reverse("replicas_estudo", args=[self.estudo.pk])
        self.pareadas = reverse("amostras_estudo", args=[self.estudo.pk])
        self.desfazer = reverse("desfazer_estudo", args=[self.estudo.pk])
        self.resultado = reverse("resultado_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    # --- Formulários que imitam a tela ---------------------------------------

    def _grade_vazia(self) -> dict:
        campos = {
            f"nivel_{self.nivel.pk}_{posicao}": ""
            for posicao in range(1, servicos.REPLICAS_POR_COLUNA + 1)
        }
        campos[f"alvo_{self.nivel.pk}"] = ""
        campos[f"provedor_{self.nivel.pk}"] = ""
        return campos

    def _amostras_vazias(self) -> dict:
        campos = {"total": servicos.MINIMO_AMOSTRAS_GRADE}
        for posicao in range(1, servicos.MINIMO_AMOSTRAS_GRADE + 1):
            campos[f"amostra_{posicao}_id"] = ""
            campos[f"amostra_{posicao}_comparacao"] = ""
            campos[f"amostra_{posicao}_teste"] = ""
        return campos

    # --- Réplicas -------------------------------------------------------------

    def test_apagar_a_grade_inteira_oferece_o_desfazer(self):
        resposta = self.client.post(self.grade, self._grade_vazia(), follow=True)

        self.assertEqual(self.nivel.replicas.count(), 0)
        self.assertIsNotNone(resposta.context["retrocesso"])
        self.assertContains(resposta, "Desfazer")
        self.assertContains(resposta, f"apagou {self.replicas} réplica")

    def test_desfazer_devolve_as_replicas_com_os_mesmos_valores(self):
        antes = list(
            self.nivel.replicas.order_by("corrida", "sequencia").values_list(
                "corrida", "sequencia", "valor"
            )
        )

        self.client.post(self.grade, self._grade_vazia())
        self.client.post(self.desfazer)

        depois = list(
            Replica.objects.filter(nivel__estudo=self.estudo)
            .order_by("corrida", "sequencia")
            .values_list("corrida", "sequencia", "valor")
        )
        self.assertEqual(depois, antes)

    def test_trocar_valor_ja_lancado_tambem_oferece_desfazer(self):
        campos = self._grade_vazia()
        original = self.nivel.replicas.order_by("corrida", "sequencia").first()
        campos[f"nivel_{self.nivel.pk}_1"] = "9,99"

        resposta = self.client.post(self.grade, campos, follow=True)

        self.assertContains(resposta, "trocou o valor de 1 réplica")

        self.client.post(self.desfazer)
        voltou = Replica.objects.get(nivel__estudo=self.estudo, corrida=1, sequencia=1)
        self.assertEqual(voltou.valor, original.valor)

    def test_gravacao_que_so_acrescenta_nao_oferece_desfazer(self):
        # Posição 26 está vazia no fixture: preenchê-la não destrói nada, e
        # quem digitou apaga o campo se errou.
        campos = {f"nivel_{self.nivel.pk}_26": "1,40"}

        resposta = self.client.post(self.grade, campos, follow=True)

        self.assertIsNone(resposta.context["retrocesso"])
        self.assertNotContains(resposta, "data-desfazer-gravado")

    def test_uma_gravacao_nova_joga_fora_o_retrato_anterior(self):
        # Sem isto o desfazer restauraria o estado de duas gravações atrás e
        # apagaria a réplica digitada depois — a perda que ele evita.
        self.client.post(self.grade, self._grade_vazia())
        self.client.post(self.grade, {f"nivel_{self.nivel.pk}_1": "1,40"})

        resposta = self.client.post(self.desfazer, follow=True)

        self.assertContains(resposta, "Não há nada para desfazer")
        self.assertEqual(Replica.objects.filter(nivel__estudo=self.estudo).count(), 1)

    def test_o_desfazer_vale_por_um_passo_so(self):
        self.client.post(self.grade, self._grade_vazia())
        self.client.post(self.desfazer)

        resposta = self.client.post(self.desfazer, follow=True)

        self.assertContains(resposta, "Não há nada para desfazer")
        self.assertEqual(
            Replica.objects.filter(nivel__estudo=self.estudo).count(), self.replicas
        )

    def test_trocar_a_media_interlaboratorial_preenchida_oferece_desfazer(self):
        self.nivel.media_interlaboratorial = Decimal("1.30")
        self.nivel.save(update_fields=["media_interlaboratorial"])
        campos = {f"alvo_{self.nivel.pk}": "1,80", f"provedor_{self.nivel.pk}": ""}

        resposta = self.client.post(self.grade, campos, follow=True)

        self.assertContains(resposta, "trocou a média interlaboratorial")

        self.client.post(self.desfazer)
        self.nivel.refresh_from_db()
        self.assertEqual(self.nivel.media_interlaboratorial, Decimal("1.30"))

    # --- Nível de controle ----------------------------------------------------

    def test_desfazer_devolve_o_nivel_removido_e_as_replicas(self):
        self.client.post(self.grade, {"remover_nivel": self.nivel.pk})
        self.assertEqual(self.estudo.niveis.count(), 0)

        self.client.post(self.desfazer)

        nivel = self.estudo.niveis.get(numero=1)
        self.assertEqual(nivel.controle, self.nivel.controle)
        self.assertEqual(nivel.replicas.count(), self.replicas)

    def test_acrescentar_nivel_joga_fora_o_retrato(self):
        # A restauração apaga o que não estava no retrato: sem descartá-lo, o
        # desfazer levaria junto a coluna criada depois.
        outro = Controle.objects.create(
            sistema=self.estudo.sistema_teste, mensurando=self.estudo.mensurando,
            nivel=2, nome="Controle 2", lote="L2", validade=date(2027, 1, 1),
        )
        self.client.post(self.grade, {"remover_nivel": self.nivel.pk})
        self.client.post(
            self.grade, {"acao": "adicionar_nivel", "controle": outro.pk}
        )

        resposta = self.client.post(self.desfazer, follow=True)

        self.assertContains(resposta, "Não há nada para desfazer")
        self.assertEqual(self.estudo.niveis.count(), 1)

    # --- Amostras pareadas ----------------------------------------------------

    def test_desfazer_devolve_as_amostras_pareadas(self):
        antes = list(
            self.estudo.amostras_comparacao.order_by("pk").values_list(
                "identificacao", "valor_comparacao", "valor_teste"
            )
        )

        self.client.post(self.pareadas, self._amostras_vazias())
        self.assertEqual(self.estudo.amostras_comparacao.count(), 0)

        self.client.post(self.desfazer)

        depois = list(
            self.estudo.amostras_comparacao.order_by("pk").values_list(
                "identificacao", "valor_comparacao", "valor_teste"
            )
        )
        self.assertEqual(depois, antes)

    # --- Amostras qualitativas ------------------------------------------------

    def test_desfazer_devolve_as_amostras_qualitativas(self):
        self.estudo.tipo = Estudo.QUALITATIVO
        self.estudo.save(update_fields=["tipo"])
        tela = reverse("qualitativas_estudo", args=[self.estudo.pk])

        lancamento = {"total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS}
        for posicao in range(1, 4):
            lancamento[f"amostra_{posicao}_id"] = f"AM-{posicao:03d}"
            lancamento[f"amostra_{posicao}_referencia"] = "Reagente"
            lancamento[f"amostra_{posicao}_teste"] = "Não reagente"
        self.client.post(tela, lancamento)
        self.assertEqual(self.estudo.amostras_qualitativas.count(), 3)

        vazio = {"total": servicos.MINIMO_AMOSTRAS_QUALITATIVAS}
        for posicao in range(1, 4):
            vazio[f"amostra_{posicao}_id"] = ""
            vazio[f"amostra_{posicao}_referencia"] = ""
            vazio[f"amostra_{posicao}_teste"] = ""
        self.client.post(tela, vazio)
        self.assertEqual(self.estudo.amostras_qualitativas.count(), 0)

        self.client.post(self.desfazer)

        voltaram = list(
            self.estudo.amostras_qualitativas.order_by("pk").values_list(
                "identificacao", "resultado_referencia", "resultado_teste"
            )
        )
        self.assertEqual(
            voltaram,
            [("AM-001", True, False), ("AM-002", True, False), ("AM-003", True, False)],
        )

    # --- Trilha, limites e isolamento -----------------------------------------

    def test_a_desfeita_vai_para_a_trilha_de_auditoria(self):
        self.client.post(self.grade, self._grade_vazia())

        self.client.post(self.desfazer)

        registro = RegistroAuditoria.objects.get(
            acao="desfez a última alteração de dado bruto"
        )
        self.assertEqual(registro.usuario, self.usuario)
        self.assertEqual(registro.objeto, self.estudo.identificacao)
        self.assertIn("réplica", registro.detalhe["desfeito"])

    def test_estudo_liberado_nao_desfaz(self):
        self.client.post(self.grade, self._grade_vazia())
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])

        resposta = self.client.post(self.desfazer, follow=True)

        self.assertContains(resposta, "não aceita alteração de dado bruto")
        self.assertEqual(Replica.objects.filter(nivel__estudo=self.estudo).count(), 0)

    def test_o_retrato_de_um_estudo_nao_aparece_em_outro(self):
        outro = Estudo.objects.create(
            laboratorio=self.laboratorio, identificacao="Outra validação",
            modulo=Assinatura.COMPLETO, mensurando=self.estudo.mensurando,
            sistema_teste=self.estudo.sistema_teste,
            sistema_comparacao=self.estudo.sistema_comparacao,
            especificacao=self.estudo.especificacao, criado_por=self.usuario,
        )
        self.client.post(self.grade, self._grade_vazia())

        resposta = self.client.get(reverse("resultado_estudo", args=[outro.pk]))

        self.assertIsNone(resposta.context["retrocesso"])

    def test_o_quadro_oferece_o_desfazer_e_diz_de_qual_estudo(self):
        # Quem apagou sem querer costuma perceber depois de sair da tela de
        # lançamento, e o quadro é para onde se volta.
        self.client.post(self.grade, self._grade_vazia())

        resposta = self.client.get(reverse("quadro"))

        self.assertIsNotNone(resposta.context["retrocesso"])
        self.assertContains(resposta, self.estudo.identificacao)
        self.assertContains(resposta, "data-desfazer-gravado")

    def test_o_quadro_de_outro_laboratorio_nao_ve_o_retrato(self):
        vizinho = montar_laboratorio("Lab B", "22.222.222/0001-22")
        dono = Usuario.objects.create_user(
            username="vizinho", password="senha-longa-de-teste", laboratorio=vizinho
        )
        self.client.post(self.grade, self._grade_vazia())

        # A sessão é outra, mas a checagem que vale é a do quadro: mesmo que o
        # retrato chegasse aqui, o estudo não está na lista deste usuário.
        self.client.force_login(dono)
        resposta = self.client.get(reverse("quadro"))

        self.assertIsNone(resposta.context["retrocesso"])

    def test_desfazer_estudo_de_outro_laboratorio_e_recusado(self):
        vizinho = montar_laboratorio("Lab B", "22.222.222/0001-22")
        dono = Usuario.objects.create_user(
            username="vizinho", password="senha-longa-de-teste", laboratorio=vizinho
        )
        alheio = montar_estudo(vizinho, dono)

        resposta = self.client.post(reverse("desfazer_estudo", args=[alheio.pk]))

        self.assertEqual(resposta.status_code, 404)

    def test_o_desfazer_nao_atende_get(self):
        # Escrita em link seria disparada por pré-carregamento do navegador.
        self.assertEqual(self.client.get(self.desfazer).status_code, 405)

    def test_endereco_de_volta_para_fora_do_programa_e_ignorado(self):
        self.client.post(self.grade, self._grade_vazia())

        resposta = self.client.post(
            self.desfazer, {"voltar": "https://exemplo-invasor.test/"}
        )

        self.assertEqual(resposta["Location"], self.resultado)


class TestRemoverNivelDeControle(TestCase):
    """Apagar uma coluna da grade de réplicas.

    É destrutivo — diferente de excluir uma réplica, que fica no banco com
    justificativa e sai riscada no anexo. O retrocesso da sessão desfaz o
    clique imediato, e só ele; por isso o que sumiu precisa ficar registrado, e
    a tela precisa dizer o número antes de perguntar.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.url = reverse("replicas_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def test_remove_o_nivel_e_as_replicas_dele(self):
        replicas = self.nivel.replicas.count()
        self.assertGreater(replicas, 0)

        self.client.post(self.url, {"remover_nivel": self.nivel.pk})

        self.assertEqual(self.estudo.niveis.count(), 0)
        self.assertEqual(Replica.objects.filter(nivel=self.nivel).count(), 0)

    def test_a_remocao_diz_quantas_medicoes_sumiram(self):
        replicas = self.nivel.replicas.count()

        resposta = self.client.post(
            self.url, {"remover_nivel": self.nivel.pk}, follow=True
        )

        self.assertContains(resposta, f"{replicas} réplica")

    def test_a_remocao_vai_para_a_trilha_com_o_lote(self):
        replicas = self.nivel.replicas.count()
        lote = self.nivel.controle.lote

        self.client.post(self.url, {"remover_nivel": self.nivel.pk})

        registro = RegistroAuditoria.objects.get(acao="removeu um nível de controle")
        self.assertEqual(registro.usuario, self.usuario)
        self.assertEqual(registro.detalhe["replicas_apagadas"], replicas)
        self.assertEqual(registro.detalhe["lote"], lote)

    def test_estudo_liberado_nao_perde_nivel(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save()

        self.client.post(self.url, {"remover_nivel": self.nivel.pk}, follow=True)

        self.assertEqual(self.estudo.niveis.count(), 1)

    def test_nivel_de_outro_estudo_e_recusado(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        dono = Usuario.objects.create_user(
            username="outro", password="senha-longa-de-teste", laboratorio=outro
        )
        alheio = montar_estudo(outro, dono).niveis.get(numero=1)

        resposta = self.client.post(
            self.url, {"remover_nivel": alheio.pk}, follow=True
        )

        self.assertTrue(NivelEstudo.objects.filter(pk=alheio.pk).exists())
        self.assertContains(resposta, "Nível não encontrado")

    def test_a_tela_avisa_quantas_replicas_somem_antes_do_clique(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Remover este nível")
        self.assertContains(resposta, f"{self.nivel.replicas.count()} réplica")
        self.assertContains(resposta, f'value="{self.nivel.pk}"')

    def test_salvar_a_grade_nao_remove_nada(self):
        # O botão de remover fica no mesmo formulário da grade: um envio comum
        # não pode apagar coluna nenhuma.
        self.client.post(self.url, {})

        self.assertEqual(self.estudo.niveis.count(), 1)


class TestFaixasRecolhidasNaTelaDeResultado(TestCase):
    """A tela abre como índice do estudo, com tudo recolhido.

    O preço de recolher é que um link para dentro de uma seção fechada não leva
    a lugar nenhum. Os dois links que o programa gera para dentro — o do
    veredito e o do retorno de um recorte — precisam continuar funcionando.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="rt", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_nenhuma_faixa_abre_sozinha(self):
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        corpo = self.client.get(self.url).content.decode()

        self.assertIn('class="cartao faixa"', corpo)
        self.assertNotIn('class="cartao faixa" open', corpo)

    def test_o_programa_carrega_o_que_abre_a_secao_apontada(self):
        corpo = self.client.get(self.url).content.decode()

        self.assertIn("js/faixas.js", corpo)

    def test_as_ancoras_que_o_programa_gera_existem_na_pagina(self):
        # Sem o id na página, o link do veredito e o retorno do recorte
        # apontariam para o nada.
        self.client.post(reverse("concluir_estudo", args=[self.estudo.pk]))

        corpo = self.client.get(self.url).content.decode()

        self.assertIn('id="analise"', corpo)
        self.assertIn('id="comparabilidade"', corpo)
        self.assertIn('href="#analise"', corpo)


class TestSelecaoMultiplaNasGrades(TestCase):
    """As três grades oferecem seleção múltipla para corrigir em bloco.

    Corrigir um lançamento célula por célula é o trabalho que a grade existe
    para evitar. O comportamento em si é do navegador; o que se pode travar
    aqui é a fiação: o script carregado, o botão do rodapé, a dica na tela e os
    atributos de coordenada de que a seleção depende.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.client.force_login(self.usuario)

    def _telas(self):
        qualitativo = montar_estudo(
            montar_laboratorio("Lab Q", "33.333.333/0001-33"), self.usuario
        )
        qualitativo.tipo = Estudo.QUALITATIVO
        qualitativo.laboratorio = self.laboratorio
        qualitativo.save()
        return [
            reverse("replicas_estudo", args=[self.estudo.pk]),
            reverse("amostras_estudo", args=[self.estudo.pk]),
            reverse("qualitativas_estudo", args=[qualitativo.pk]),
        ]

    def test_as_tres_grades_carregam_a_selecao(self):
        for url in self._telas():
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "js/grade.js")

    def test_as_tres_grades_tem_o_botao_de_limpar(self):
        for url in self._telas():
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "data-limpar-selecao")

    def test_as_tres_grades_explicam_os_gestos(self):
        for url in self._telas():
            with self.subTest(url=url):
                corpo = self.client.get(url).content.decode()
                self.assertIn("Shift+clique", corpo)
                self.assertIn("Ctrl+clique", corpo)

    def test_a_dica_diz_que_limpar_nao_apaga(self):
        # É a diferença que evita alguém achar que perdeu dado sem salvar — e,
        # pior, achar que apagou quando só limpou a tela.
        corpo = " ".join(
            self.client.get(
                reverse("replicas_estudo", args=[self.estudo.pk])
            ).content.decode().split()
        )

        self.assertIn("Limpar não apaga do estudo", corpo)
        self.assertIn("quem apaga é o salvar", corpo)

    def test_toda_celula_tem_as_coordenadas_da_selecao(self):
        # O retângulo do Shift+clique é calculado por linha e coluna: sem os
        # dois atributos em todas as células, a marcação sai furada.
        corpo = self.client.get(
            reverse("amostras_estudo", args=[self.estudo.pk])
        ).content.decode()

        import re

        entradas = re.findall(r"<input[^>]*data-linha[^>]*>", corpo)
        self.assertGreater(len(entradas), 30)
        for entrada in entradas:
            self.assertIn("data-coluna=", entrada)

    def test_a_celula_travada_nao_recebe_coordenada(self):
        # Réplica excluída é registro do que foi descartado: some do cálculo,
        # não do banco, e a seleção não pode alcançá-la.
        replica = self.estudo.niveis.get(numero=1).replicas.first()
        replica.excluida = True
        replica.justificativa_exclusao = "bolha na cubeta"
        replica.save()

        corpo = self.client.get(
            reverse("replicas_estudo", args=[self.estudo.pk])
        ).content.decode()

        self.assertIn("disabled", corpo)
        self.assertIn("excluída", corpo)

    def test_o_recado_da_grade_e_um_so(self):
        # Colagem e seleção falam pela mesma linha: uma grade, um lugar onde
        # ela conversa com quem está digitando.
        corpo = self.client.get(
            reverse("replicas_estudo", args=[self.estudo.pk])
        ).content.decode()

        self.assertEqual(corpo.count("data-recado-grade"), 1)
        self.assertNotIn("data-aviso-colagem", corpo)
