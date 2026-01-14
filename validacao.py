import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# Configuração da Página
st.set_page_config(page_title="Validação de Métodos Laboratoriais", layout="wide")

# --- BARRA LATERAL: RASTREABILIDADE ---
st.sidebar.header("📝 Rastreabilidade")
analito = st.sidebar.text_input("Analito", "Glicose")
equipamento = st.sidebar.text_input("Equipamento", "Modelo X100")
lote_reagente = st.sidebar.text_input("Lote do Reagente")
operador = st.sidebar.text_input("Analista Responsável")
tea_alvo = st.sidebar.number_input("Erro Total Permitido (TEa %)", value=6.0)

# --- CORPO PRINCIPAL: TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Precisão (Repetibilidade)", "🎯 Exatidão / Comparativo", "📜 Relatório Final"])

with tab1:
    st.subheader("Estudo de Precisão")
    st.write("Altere os valores abaixo para ver o CV% e o Desvio Padrão em tempo real.")
    
    # Criando uma tabela editável para os dados brutos
    df_precisao = pd.DataFrame({
        "Corrida": range(1, 11),
        "Resultado (mg/dL)": [100.0, 102.0, 101.0, 99.0, 100.5, 101.2, 98.8, 100.1, 100.9, 101.5]
    })
    
    # Interface de edição em tempo real
    edited_df = st.data_editor(df_precisao, num_rows="dynamic")
    
    # Cálculos Automáticos
    media = edited_df["Resultado (mg/dL)"].mean()
    sd = edited_df["Resultado (mg/dL)"].std()
    cv = (sd / media) * 100 if media != 0 else 0
    
    # Exibição de Métricas
    col1, col2, col3 = st.columns(3)
    col1.metric("Média", f"{media:.2f}")
    col2.metric("Desvio Padrão (SD)", f"{sd:.2f}")
    col3.metric("CV (%)", f"{cv:.2f}%")

    # Gráfico de Levey-Jennings em tempo real
    fig = px.line(edited_df, x="Corrida", y="Resultado (mg/dL)", title=f"Monitoramento de Precisão - {analito}")
    fig.add_hline(y=media, line_dash="dash", line_color="green", annotation_text="Média")
    fig.add_hline(y=media + 2*sd, line_dash="dot", line_color="red", annotation_text="+2SD")
    fig.add_hline(y=media - 2*sd, line_dash="dot", line_color="red", annotation_text="-2SD")
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Visualização do Relatório de Validação")
    st.info(f"Relatório gerado para o analito: **{analito}**")
    # Aqui entrará a lógica de Haeckel/Westgard para o Erro Total
    bias_estimado = 1.5 # Exemplo vindo da Tab 2
    erro_total = abs(bias_estimado) + (1.65 * cv)
    
    st.write(f"**Erro Total Calculado:** {erro_total:.2f}%")
    if erro_total <= tea_alvo:
        st.success("✅ MÉTODO VALIDADO: O erro total está dentro do limite permitido.")
    else:
        st.error("❌ MÉTODO REJEITADO: O erro total excede o limite (TEa).")