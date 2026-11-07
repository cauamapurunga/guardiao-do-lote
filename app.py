"""Guardião do Lote — agentes que conferem cada pagamento antes do dinheiro sair."""
import json
from pathlib import Path
from dataclasses import asdict

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from guardiao import env  # noqa: F401  (carrega .env)

from guardiao import telegram as tg
from guardiao.agentes import Guardiao
from guardiao.dados import carregar
from guardiao import leitor_caixa, ia
from guardiao.timeline import construir
from guardiao.dados import brl2

SALA = (Path(__file__).parent / "guardiao" / "sala.html").read_text(encoding="utf-8")

st.set_page_config(page_title="Guardião do Lote", page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input {font-family: Inter, system-ui, sans-serif !important;}
.block-container {padding-top: 1.2rem; max-width: 1480px;}
header[data-testid="stHeader"] {background: transparent;}
.brand {display:flex; align-items:center; gap:14px; padding: 6px 0 14px; border-bottom: 1px solid #1d2840; margin-bottom: 14px;}
.logo {width:42px; height:42px; border-radius:12px; background:#d4e000; display:grid; place-items:center; font-weight:900; color:#0b0f00; font-size:20px;}
.brand h1 {font-size: 1.45rem; font-weight: 800; letter-spacing: -.03em; margin:0; padding:0; color:#fff;}
.brand p {color:#8391ab; font-size:.86rem; margin:2px 0 0;}
.brand .pill {margin-left:auto; border:1px solid #3a4510; background:#141a05; color:#d4e000; padding:6px 12px; border-radius:99px; font-size:.78rem; font-weight:600;}
.kpi {border-radius: 14px; padding: 14px 16px; background: #0d1424; border: 1px solid #1d2840;}
.kpi .l {font-size: .68rem; color:#8391ab; text-transform: uppercase; letter-spacing: .09em; font-weight:600;}
.kpi .v {font-size: 1.55rem; font-weight: 800; margin-top: 4px; letter-spacing:-.02em; font-variant-numeric: tabular-nums; color:#fff;}
.kpi .s {font-size: .76rem; color:#5b6782; margin-top:2px;}
.kpi.bad .v {color: #ff5d5d;} .kpi.good .v {color: #d4e000;}
.stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #1d2840;}
.stTabs [data-baseweb="tab"] {padding: 8px 14px; font-weight: 600;}
.ev {border-left: 2px solid #26334f; padding: 2px 0 10px 14px; position: relative;}
.ev:before {content:''; position:absolute; left:-6px; top:6px; width:10px; height:10px; border-radius:50%; background: var(--c, #8391ab);}
.ev .t {font-family: 'JetBrains Mono', monospace; font-size:.72rem; color:#5b6782;}
.ev .f {font-family: 'JetBrains Mono', monospace; font-weight:600; color: var(--c);}
.ev .d {color:#c3cbe0; font-size:.86rem;}
.evid {background:#0d1424; border:1px solid #1d2840; border-radius:10px; padding:9px 12px; margin-bottom:6px; font-size:.86rem; color:#c3cbe0;}
.badge {display:inline-block; padding:2px 8px; border-radius:6px; font-size:.7rem; font-weight:700; margin-left:6px;}
.b-auto {background:#13301f; color:#39d98a;} .b-hum {background:#33270b; color:#ffb547;}
.arch {display:grid; grid-template-columns: repeat(3,1fr); gap:12px;}
.arch .a {background:#0d1424; border:1px solid #1d2840; border-top: 3px solid var(--c); border-radius:12px; padding:14px;}
.arch h4 {margin:0 0 4px; font-size:1rem;} .arch p {color:#8391ab; font-size:.84rem; margin:0 0 8px;}
.arch code {font-size:.74rem;}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def bases():
    return carregar()


def novo_guardiao():
    g = Guardiao(bases()).executar()
    st.session_state.g = g
    st.session_state.caixa = leitor_caixa.ler(bases(), usar_ia=False)
    st.session_state.tg_offset = None
    st.session_state.tg_enviados = set()


if "g" not in st.session_state:
    novo_guardiao()
g: Guardiao = st.session_state.g
p = g.placar()
brl = lambda v: f"R$ {v:,.0f}".replace(",", ".")

# ------------------------------------------------------------------ cabeçalho
st.markdown("""<div class="brand"><div class="logo">G</div><div><h1>Guardião do Lote</h1>
<p>Time de agentes de contas a pagar · confere cada título contra ERP, Compras, NF-e, DDA, bancos e caixa de e-mail antes do lote fechar</p></div>
<div class="pill">● ambiente seg 02/11 08:00 · próximo lote 03/11 10:00</div></div>""", unsafe_allow_html=True)

k = st.columns(5)
kp = [("Agenda de remessa", f"{p['titulos_na_agenda']} títulos", f"{p['lotes']} lotes · R$ {p['valor_na_agenda']/1e6:.1f} mi".replace(".", ","), ""),
      ("Sairia indevidamente", brl(p["perda_sem_agente"]), "se o tesoureiro assinar sem conferir", "bad"),
      ("Custo com o Guardião", brl(p["custo_agente"]), "acionamentos + atraso legítimo", "good"),
      ("Resolvidos sozinho", f"{p['resolvidos_sozinho']}/{p['casos']}", f"{p['acoes_executadas']} ações nos sistemas", ""),
      ("Decisões humanas", f"{sum(1 for c in g.casos if c.status != 'resolvido')}", "aprovação ou acionamento", "")]
for col, (l, v, s_, cls) in zip(k, kp):
    col.markdown(f"<div class='kpi {cls}'><div class='l'>{l}</div><div class='v'>{v}</div><div class='s'>{s_}</div></div>",
                 unsafe_allow_html=True)
st.write("")

# ------------------------------------------------------------------ sidebar: canal humano
with st.sidebar:
    st.markdown("### 🖐️ Canal humano (Telegram)")
    tem_token = bool(tg.token())
    st.write("Bot:", "✅ configurado" if tem_token else "⚠️ sem TELEGRAM_TOKEN")
    chat = st.text_input("chat_id", value=st.session_state.get("chat_id") or tg.chat_id() or "")
    if tem_token and st.button("Descobrir meu chat_id", width="stretch"):
        try:
            cid = tg.descobrir_chat_id()
            st.session_state.chat_id = cid
            st.success(f"chat_id = {cid}" if cid else "Mande uma mensagem pro bot e tente de novo.")
        except Exception as e:
            st.error(e)
    chat = st.session_state.get("chat_id") or chat
    pend = [c for c in g.casos if c.status == "aguardando_aprovacao"]
    if tem_token and chat and st.button(f"📤 Enviar {len(pend)} pedidos de aprovação", width="stretch", type="primary"):
        n = 0
        for c in pend:
            if c.id in st.session_state.tg_enviados:
                continue
            try:
                exp = None
                if leitor_caixa._key():
                    try:
                        exp = leitor_caixa.explicar_caso(asdict(c))
                    except Exception:
                        exp = None
                tg.pedir_aprovacao(asdict(c), chat, exp)
                st.session_state.tg_enviados.add(c.id)
                n += 1
            except Exception as e:
                st.error(e)
                break
        for caso in g.casos:
            for x in caso.acoes:
                if x["ferramenta"] == "acionar_pessoa" and f"av{caso.id}" not in st.session_state.tg_enviados:
                    try:
                        tg.avisar(asdict(caso), x["para"], x["detalhe"], chat)
                        st.session_state.tg_enviados.add(f"av{caso.id}")
                    except Exception:
                        pass
        st.success(f"{n} pedidos enviados.")
    if tem_token and st.button("📥 Ler respostas do Telegram", width="stretch"):
        try:
            resps, st.session_state.tg_offset = tg.ler_respostas(st.session_state.tg_offset)
            for r in resps:
                c = g.decidir(r["caso"], r["decisao"] == "aprovado", r["quem"])
                if c:
                    tg.confirmar_clique(r, f"{'✅' if r['decisao']=='aprovado' else '❌'} {r['quem']} {r['decisao']} {c.id} — "
                                           f"{c.resumo}. Status: {c.status}")
            st.success(f"{len(resps)} respostas aplicadas.")
            st.rerun()
        except Exception as e:
            st.error(e)
    st.divider()
    if st.button("🔄 Reiniciar simulação", width="stretch"):
        novo_guardiao()
        st.rerun()
    st.caption("Sem Telegram? Aprove na aba **Aprovações** — mesmo fluxo.")
    st.markdown("### 🧠 IA (AI Proxy)")
    st.caption(f"{leitor_caixa.modo()} · {ia.resumo_uso()}")
    if ia.USO["linhas"]:
        st.code("\n".join(ia.USO["linhas"][-6:]), language=None)

tabs = st.tabs(["Sala dos agentes", "Casos", "Aprovações", "Placar em R$", "Causa raiz", "Caixa de e-mail", "Arquitetura"])

# ------------------------------------------------------------------ 1. sala dos agentes
with tabs[0]:
    html = SALA.replace("__DATA__", json.dumps(construir(g), default=str, ensure_ascii=False))
    components.html(html, height=960, scrolling=False)
    with st.expander("Log completo de ferramentas executadas"):
        df = g.tabela_log()
        st.dataframe(df[["ts", "agente", "ferramenta", "alvo", "detalhe", "modo", "para"]], width="stretch",
                     height=420, hide_index=True)



# ------------------------------------------------------------------ 2. casos
with tabs[1]:
    df = g.tabela_casos()
    nomes = {"GOLPE_TROCA_CONTA": "🚨 Golpe: conta trocada", "JA_PAGO_FORA_DO_LOTE": "💸 Já pago por fora",
             "DUPLICIDADE": "👯 Duplicidade", "VALOR_DIVERGENTE": "🔢 Valor errado", "FORNECEDOR_ERRADO": "🏷️ Fornecedor errado",
             "OC_INVALIDA": "📦 OC inválida", "BOLETO_SUSPEITO": "🧾 Boleto suspeito"}
    df["problema"] = df.tipo.map(nomes).fillna(df.tipo)
    df["status_txt"] = df.status.map({"resolvido": "✅ agente resolveu", "aguardando_aprovacao": "🖐️ aguardando aprovação",
                                       "aguardando_humano": "📣 humano acionado"})
    f1, f2 = st.columns(2)
    tipo = f1.multiselect("Problema", sorted(df.problema.unique()))
    lote = f2.multiselect("Lote", sorted(df.lote.unique()))
    v = df
    if tipo:
        v = v[v.problema.isin(tipo)]
    if lote:
        v = v[v.lote.isin(lote)]
    st.dataframe(v[["id", "problema", "lote", "fechamento", "titulo_id", "fornecedor", "valor", "perda_evitada", "agente",
                    "status_txt", "resumo"]], width="stretch", hide_index=True, height=300,
                 column_config={"valor": st.column_config.NumberColumn(format="R$ %.2f"),
                                "perda_evitada": st.column_config.NumberColumn(format="R$ %.2f")})
    sel = st.selectbox("Abrir caso", v.id.tolist(), format_func=lambda i: f"{i} — {df.set_index('id').loc[i, 'resumo']}")
    if sel:
        c = next(x for x in g.casos if x.id == sel)
        a, b2 = st.columns([1, 1])
        with a:
            st.markdown(f"#### {nomes.get(c.tipo, c.tipo)}")
            st.markdown(f"**{c.resumo}**  \n{c.fornecedor} · `{c.titulo_id}` · {brl2(c.valor)} · lote `{c.lote}` fecha {c.fechamento}")
            st.markdown("###### Evidências cruzadas entre sistemas")
            st.markdown("".join(f"<div class='evid'>{e}</div>" for e in c.evidencias), unsafe_allow_html=True)
        with b2:
            st.markdown("###### Linha do tempo dos agentes")
            cor = {"Sentinela": "#c9d2e3", "Analista": "#5b8cff", "Auditor": "#ff5d5d", "Leitor": "#a58bff"}
            html_ = ""
            for x in c.acoes:
                ccor = cor.get(x["agente"].split(" ")[0], "#ffb547")
                bdg = "<span class='badge b-auto'>agiu sozinho</span>" if x["modo"] == "auto" else "<span class='badge b-hum'>humano</span>"
                html_ += (f"<div class='ev' style='--c:{ccor}'><div class='t'>{x['ts']} · {x['agente']}{bdg}</div>"
                          f"<div class='f'>{x['ferramenta']}({x['alvo']})</div><div class='d'>{x['detalhe']}"
                          f"{(' → <b>' + x['para'] + '</b>') if x['para'] else ''}</div></div>")
            st.markdown(html_, unsafe_allow_html=True)
            st.markdown(f"**Status:** {df.set_index('id').loc[c.id, 'status_txt']}")
            if leitor_caixa._key() and st.button("🧠 Explicar para o aprovador (IA)", key=f"ia{c.id}"):
                with st.spinner("Escrevendo..."):
                    st.info(leitor_caixa.explicar_caso(asdict(c)))

# ------------------------------------------------------------------ 3. aprovações
with tabs[2]:
    pend = [c for c in g.casos if c.status == "aguardando_aprovacao"]
    st.markdown(f"**{len(pend)} decisões** que o agente **não deve tomar sozinho** (fora da alçada ou aprovação dupla). "
                "Ele já segurou o dinheiro; falta a pessoa certa decidir.")
    for c in pend:
        with st.container(border=True):
            l, r = st.columns([4, 1])
            l.markdown(f"**{c.id} · {c.resumo}**  \n{c.fornecedor} · {brl2(c.valor)} · lote {c.lote} ({c.fechamento})  \n"
                       f"Para: **{c.aprovacao['nome']}**{' + aprovador (dupla)' if c.aprovacao.get('dupla') else ''} · "
                       f"Ação: `{c.aprovacao['acao']}`  \n_{c.aprovacao['motivo']}_")
            if r.button("✅ Aprovar", key=f"a{c.id}", width="stretch"):
                g.decidir(c.id, True, "painel")
                st.rerun()
            if r.button("❌ Recusar", key=f"r{c.id}", width="stretch"):
                g.decidir(c.id, False, "painel")
                st.rerun()
    if not pend:
        st.success("Nenhuma decisão pendente.")

# ------------------------------------------------------------------ 4. placar
with tabs[3]:
    st.markdown("Fórmula oficial (`parametros.md`): **placar = −(dinheiro que saiu indevidamente + custo de atrasar pagamento "
                "legítimo + R$ 60 por acionamento humano desnecessário)**")
    a, b2 = st.columns(2)
    a.metric("Placar hoje (tesoureiro assina sem conferir)", brl(p["placar_sem_agente"]))
    b2.metric("Placar com o Guardião", brl(p["placar_com_agente"]),
              delta=brl(p["placar_com_agente"] - p["placar_sem_agente"]))
    t = pd.DataFrame([{"problema": nomes.get(k_, k_), "títulos": v_["qtd"], "sairia indevidamente": v_["perda"]}
                      for k_, v_ in p["por_tipo"].items()]).sort_values("sairia indevidamente", ascending=False)
    st.bar_chart(t.set_index("problema")["sairia indevidamente"], horizontal=True, color="#dc2626")
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={"sairia indevidamente": st.column_config.NumberColumn(format="R$ %.2f")})
    st.caption(f"Custo do agente (pior caso): {p['acionamentos']} acionamentos × R$ 60 = {brl(p['custo_acionamentos'])} "
               f"+ atraso de títulos legítimos retidos = {brl(p['custo_atraso'])}. "
               f"Ações executadas sozinho: {p['acoes_executadas']}.")

# ------------------------------------------------------------------ 5. causa raiz
with tabs[4]:
    st.markdown("O Auditor não para no sintoma: procura **o padrão** e propõe correção de processo.")
    for a in g.log:
        if a.ferramenta in ("propor_correcao_processo", "abrir_incidente"):
            st.markdown(f"- **{a.ferramenta}** · `{a.alvo}` — {a.detalhe}")

# ------------------------------------------------------------------ 6. caixa
with tabs[5]:
    cx = st.session_state.caixa
    l_, r_ = st.columns([3, 1])
    l_.markdown(f"**Leitor da Caixa** classificou {len(cx)} e-mails e WhatsApps ({leitor_caixa.modo() if st.session_state.get('caixa_ia') else 'regras'}). "
                "Texto de terceiros é **dado, nunca instrução**.")
    if leitor_caixa._key() and r_.button("🧠 Reclassificar com IA (Jev)", width="stretch"):
        with st.spinner("Classificando 246 mensagens com o Jev..."):
            st.session_state.caixa = leitor_caixa.ler(bases(), usar_ia=True)
            st.session_state.caixa_ia = True
        st.rerun()
    st.dataframe(cx, hide_index=True, width="stretch", height=460)

# ------------------------------------------------------------------ 7. como funciona
with tabs[6]:
    st.markdown("""
<div class="arch">
 <div class="a" style="--c:#c9d2e3"><h4>Sentinela · orquestrador</h4><p>Acompanha a agenda de remessa e abre cada lote antes do fechamento (Meridiano 10h, Litoral 14h). Despacha os títulos e libera o que passou.</p><code>listar_agenda_remessa</code> <code>liberar_lote</code></div>
 <div class="a" style="--c:#5b8cff"><h4>Analista CP · alçada R$ 5 mil</h4><p>Três vias OC × NF × duplicata × DDA, duplicidade por NF normalizada, pagamento fora do lote no extrato, vírgula deslocada, fornecedor errado.</p><code>retirar_do_lote</code> <code>cancelar_titulo</code> <code>corrigir_lancamento</code></div>
 <div class="a" style="--c:#ff5d5d"><h4>Auditor · fraude e causa raiz</h4><p>Troca de conta sem ligação ao telefone anterior, domínio que imita o oficial, boleto com beneficiário errado, padrão de erro por lançador.</p><code>bloquear_fornecedor</code> <code>abrir_incidente</code> <code>propor_correcao_processo</code></div>
 <div class="a" style="--c:#a58bff"><h4>Leitor da Caixa · IA</h4><p>Lê e-mails e WhatsApps, classifica com o Jev (AI Proxy) e cruza o remetente com o cadastro. Alimenta o Auditor.</p><code>listar_comunicacoes</code> <code>/v1/systemone</code></div>
 <div class="a" style="--c:#ffb547"><h4>Pessoas · Telegram</h4><p>Fora da alçada, em aprovação dupla ou em fraude, o agente chama a pessoa certa com a evidência pronta. Ela aprova ou recusa com um toque, e o agente executa o resto.</p><code>solicitar_aprovacao</code> <code>acionar_pessoa</code></div>
 <div class="a" style="--c:#39d98a"><h4>Regras de autonomia</h4><p>Vêm de <code>politicas.csv</code> e <code>ferramentas.csv</code>: retira do lote qualquer título suspeito, cancela e corrige até R$ 5 mil, nunca aprova a própria ação nem troca dado bancário sozinho.</p></div>
</div>""", unsafe_allow_html=True)
