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
        referencia_inferior=Decimal("0.8"),
        referencia_superior=Decimal("1.8"),
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

    def test_as_faixas_resolvidas_nascem_fechadas(self):
        # Só a etapa corrente abre sozinha: é isso que faz a tela caber num olhar.
        corpo = self.resposta.content.decode()
        assert corpo.count("<details class=\"cartao faixa\">") >= 3, "faixas de rastreabilidade deveriam nascer condensadas"
        assert "<details class=\"cartao faixa\" open>" in corpo, "a etapa corrente deveria nascer aberta"

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

    def test_sem_intervalo_proprio_o_estudo_herda_o_do_mensurando(self):
        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.8"), Decimal("1.8"))
        )
        self.assertEqual(self.estudo.intervalo_de_teste(), (None, None))

    def test_o_intervalo_do_estudo_prevalece_sobre_o_do_mensurando(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.9")
        self.estudo.referencia_comparacao_superior = Decimal("1.7")
        self.estudo.save()

        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.9"), Decimal("1.7"))
        )

    def test_intervalos_diferentes_chegam_ao_calculo(self):
        self.estudo.referencia_teste_inferior = Decimal("0.85")
        self.estudo.referencia_teste_superior = Decimal("1.86")
        self.estudo.save()

        clinica = servicos.calcular(self.estudo)["comparabilidade"]["clinica"]

        self.assertTrue(clinica["intervalos_diferentes"])
        self.assertEqual(clinica["intervalo_teste"], (0.85, 1.86))

    def test_a_tela_mostra_os_dois_intervalos_usados(self):
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
        self.calcular()

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Intervalo analítico (teste)")
        self.assertContains(resposta, "lote R1")


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
