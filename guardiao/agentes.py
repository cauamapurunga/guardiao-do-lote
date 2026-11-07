"""Orquestração dos agentes do Guardião do Lote.

Agentes (papéis e ferramentas tirados de ferramentas.csv / politicas.csv):
  - Sentinela (orquestrador): acompanha a agenda, abre cada lote antes do fechamento, despacha os casos
  - Analista CP: três vias, duplicidade, pagamento fora do lote, correções (alçada R$ 5 mil)
  - Auditor: fraude de cadastro e boleto, bloqueios, incidentes e causa raiz
  - Leitor da Caixa: lê e-mails e WhatsApps (LLM quando disponível) e alimenta o Auditor
Humanos entram por solicitar_aprovacao / acionar_pessoa (Telegram).
"""
from __future__ import annotations

import collections
import datetime as dt
from dataclasses import asdict, dataclass, field

import pandas as pd

from .dados import Bases
from .deteccao import Achado, varrer
from .dados import brl2

ALCADA_ANALISTA = 5000.0
ALCADA_APROVADOR = 50000.0

PESSOAS = {
    "PS01": "Renata Paiva (coord. contas a pagar)",
    "PS02": "Marcos Teles (tesoureiro)",
    "PS03": "Helena Duarte (diretora financeira)",
    "PS04": "Carla Menezes (compradora produto/embalagens)",
    "PS05": "Diego Prado (coord. compras insumos/serviços)",
    "PS07": "Fernanda Rocha (gerente de logística)",
    "PS08": "Lívia Campos (jurídico)",
    "PS09": "Rafael Nunes (controller)",
}
COMPRADOR_PESSOA = {"Carla Menezes": "PS04", "Diego Prado": "PS05"}

CUSTO_RELACIONAMENTO = {"produto": 3000, "frete": 1500, "embalagens": 800, "insumos_capa": 800, "aluguel": 500,
                        "ti_saas": 400, "utilidades": 400, "servicos": 300, "marketing_agencia": 300, "influenciador": 250}
CUSTO_ACIONAMENTO = 60.0


@dataclass
class Acao:
    agente: str
    ferramenta: str
    alvo: str
    detalhe: str
    modo: str          # auto | aprovacao | humano
    para: str = ""     # pessoa/papel acionado
    lote: str = ""
    ts: str = ""
    caso: str = ""


@dataclass
class Caso:
    id: str
    titulo_id: str
    fornecedor_id: str
    fornecedor: str
    valor: float
    lote: str
    fechamento: str
    tipo: str
    severidade: str
    resumo: str
    evidencias: list
    agente: str
    perda_evitada: float
    acoes: list = field(default_factory=list)
    status: str = "resolvido"         # resolvido | aguardando_aprovacao | aguardando_humano
    aprovacao: dict | None = None     # {pessoa, acao, valor}


class Guardiao:
    """Estado simulado do ERP + log de ações dos agentes."""

    def __init__(self, b: Bases):
        self.b = b
        self.titulo_status = {t: "agendado" for t in b.agenda.titulo_id}
        self.fornecedores_bloqueados: set[str] = set()
        self.log: list[Acao] = []
        self.casos: list[Caso] = []
        self.incidentes: list[dict] = []
        self.relogio = dt.datetime(2026, 11, 2, 8, 0)
        self.forn_nome = b.fornecedores.set_index("fornecedor_id").razao_social.to_dict()
        self.forn_cat = b.fornecedores.set_index("fornecedor_id").categoria.to_dict()

    # ------------------------------------------------------------ ferramentas
    def _tool(self, caso: Caso | None, agente, ferramenta, alvo, detalhe, modo="auto", para=""):
        self.relogio += dt.timedelta(seconds=7)
        a = Acao(agente, ferramenta, alvo, detalhe, modo, para, caso.lote if caso else "", self.relogio.strftime("%d/%m %H:%M:%S"),
                 caso.id if caso else "")
        self.log.append(a)
        if caso:
            caso.acoes.append(asdict(a))
        return a

    def retirar_do_lote(self, c, agente, motivo):
        self.titulo_status[c.titulo_id] = "retirado"
        self._tool(c, agente, "retirar_do_lote", c.titulo_id, motivo)

    def cancelar_titulo(self, c, agente, motivo):
        if c.valor <= ALCADA_ANALISTA:
            self.titulo_status[c.titulo_id] = "cancelado"
            self._tool(c, agente, "cancelar_titulo", c.titulo_id, motivo)
        else:
            self.solicitar_aprovacao(c, agente, "cancelar_titulo", motivo)

    def corrigir(self, c, agente, campo, novo, motivo, diferenca):
        if abs(diferenca) <= ALCADA_ANALISTA:
            self.titulo_status[c.titulo_id] = "corrigido"
            self._tool(c, agente, "corrigir_lancamento", c.titulo_id, f"{campo} → {novo}: {motivo}")
        else:
            self.retirar_do_lote(c, agente, "segura até aprovar a correção (diferença acima da alçada)")
            self.solicitar_aprovacao(c, agente, f"corrigir_lancamento {campo}={novo}", motivo)

    def solicitar_aprovacao(self, c, agente, acao, motivo, dupla=False):
        valor = c.valor
        if valor > ALCADA_APROVADOR:
            quem = "PS03"
        elif dupla:
            quem = "PS01"
        else:
            quem = "PS01"
        c.status = "aguardando_aprovacao"
        c.aprovacao = {"pessoa": quem, "nome": PESSOAS[quem], "acao": acao, "motivo": motivo, "dupla": dupla}
        self._tool(c, agente, "solicitar_aprovacao", c.titulo_id, f"{acao} — {motivo}", "aprovacao",
                   ("aprovador + " if dupla else "") + PESSOAS[quem])

    def acionar(self, c, agente, pessoa, motivo):
        if c and c.status == "resolvido":
            c.status = "aguardando_humano"
        self._tool(c, agente, "acionar_pessoa", pessoa, motivo, "humano", PESSOAS.get(pessoa, pessoa))

    # ------------------------------------------------------------ playbooks
    def _playbook(self, c: Caso, ach: Achado):
        t = c.tipo
        if t == "GOLPE_TROCA_CONTA":
            if c.fornecedor_id not in self.fornecedores_bloqueados:
                self.fornecedores_bloqueados.add(c.fornecedor_id)
                self.titulo_status[c.titulo_id] = "bloqueado"
                self._tool(c, "Auditor", "bloquear_fornecedor", c.fornecedor_id,
                           "conta bancária trocada sem confirmação válida; suspende pagamentos até confirmar")
                self._tool(c, "Auditor", "contatar_fornecedor", c.fornecedor_id,
                           "ligação para o telefone do cadastro ANTERIOR à alteração para confirmar a troca")
                self.solicitar_aprovacao(c, "Auditor", "reverter_alteracao_cadastro " + ",".join(ach.extra.get("alteracoes", [])),
                                         "voltar à conta anterior confirmada para pagar o fornecedor legítimo", dupla=True)
                self.acionar(c, "Auditor", "PS08", "tentativa de golpe: e-mail de domínio falso pediu troca de conta")
                self._tool(c, "Auditor", "abrir_incidente", c.fornecedor_id,
                           "fraude cadastral — causa: alteração aceita por e-mail sem ligação de confirmação", "auto")
                self.incidentes.append({"tipo": "fraude_cadastral", "fornecedor": c.fornecedor, "evidencias": c.evidencias})
                c.status = "aguardando_aprovacao"
            else:
                self.titulo_status[c.titulo_id] = "bloqueado"
                self._tool(c, "Auditor", "bloquear_titulo", c.titulo_id, "fornecedor bloqueado por suspeita de golpe")
        elif t == "JA_PAGO_FORA_DO_LOTE":
            self.retirar_do_lote(c, "Analista", "já pago por fora (extrato) — evita pagar 2x")
            self.cancelar_titulo(c, "Analista", f"pago manualmente em {ach.extra.get('data_pgto')} no {ach.extra.get('banco_pgto')}")
            self.acionar(c, "Analista", "PS02", "pagamento manual sem baixa no ERP — dar baixa e revisar processo")
        elif t == "DUPLICIDADE":
            self.retirar_do_lote(c, "Analista", f"duplicata do título {ach.extra.get('original')}")
            self.cancelar_titulo(c, "Analista", f"duplicidade de {ach.extra.get('original')} (mesma NF/parcela)")
        elif t == "VALOR_DIVERGENTE":
            vc = ach.extra.get("valor_correto")
            if vc is None:  # aluguel x contrato
                self.retirar_do_lote(c, "Analista", "valor diferente do contrato")
                self.acionar(c, "Analista", "PS01", "aluguel com valor diferente do contrato")
            else:
                self.corrigir(c, "Analista", "valor", f"{brl2(vc)}", "valor da duplicata na NF-e", c.valor - vc)
        elif t == "FORNECEDOR_ERRADO":
            certo = ach.extra.get("fornecedor_correto")
            self.retirar_do_lote(c, "Analista", "pagamento iria para outra empresa (nome parecido)")
            self.corrigir(c, "Analista", "fornecedor", certo, "CNPJ do emitente da NF", c.valor)
        elif t == "OC_INVALIDA":
            self.retirar_do_lote(c, "Analista", f"OC {ach.extra.get('oc_status')}")
            pessoa = COMPRADOR_PESSOA.get(ach.extra.get("comprador"), "PS05")
            self.acionar(c, "Analista", pessoa, f"título com OC {ach.extra.get('oc_status')} — confirmar se a compra vale")
        elif t == "BOLETO_SUSPEITO":
            self.titulo_status[c.titulo_id] = "bloqueado"
            self._tool(c, "Auditor", "bloquear_titulo", c.titulo_id, "beneficiário do boleto não é o fornecedor")
            self._tool(c, "Auditor", "contatar_fornecedor", c.fornecedor_id, "confirmar boleto pelo canal do cadastro")
            c.status = "aguardando_humano"
        elif t in ("SEM_NF", "SEM_OC", "NF_ACIMA_DA_OC", "NF_NAO_ENCONTRADA"):
            self.retirar_do_lote(c, "Analista", c.resumo)
            self.solicitar_aprovacao(c, "Analista", "liberar com exceção", c.resumo, dupla=True)

    # ------------------------------------------------------------ execução
    def executar(self, lotes: list[str] | None = None):
        achados = varrer(self.b, lotes)
        # um caso por título: o achado mais grave manda
        prio = ["GOLPE_TROCA_CONTA", "BOLETO_SUSPEITO", "JA_PAGO_FORA_DO_LOTE", "DUPLICIDADE", "FORNECEDOR_ERRADO",
                "OC_INVALIDA", "VALOR_DIVERGENTE", "NF_NAO_ENCONTRADA", "SEM_NF", "SEM_OC", "NF_ACIMA_DA_OC"]
        por_titulo: dict[str, list[Achado]] = collections.defaultdict(list)
        for a in achados:
            por_titulo[a.titulo_id].append(a)
        ordem_lote = self.b.agenda.drop_duplicates("lote_remessa").set_index("lote_remessa")
        chaves = sorted(por_titulo, key=lambda t: (por_titulo[t][0].lote, prio.index(min(por_titulo[t], key=lambda a: prio.index(a.tipo)).tipo)))
        lote_atual = None
        for i, tid in enumerate(chaves, 1):
            lista = sorted(por_titulo[tid], key=lambda a: prio.index(a.tipo))
            ach = lista[0]
            if ach.lote != lote_atual:
                lote_atual = ach.lote
                n = int((self.b.agenda.lote_remessa == lote_atual).sum())
                self._tool(None, "Sentinela", "listar_agenda_remessa", lote_atual,
                           f"abre o lote ({n} títulos, fecha {ach.fechamento}) e despacha a conferência", "auto")
            ev = list(ach.evidencias) + [e for o in lista[1:] for e in o.evidencias]
            c = Caso(f"C{i:03d}", tid, ach.fornecedor_id, self.forn_nome.get(ach.fornecedor_id, ""), ach.valor, ach.lote,
                     ach.fechamento, ach.tipo, ach.severidade, ach.resumo, ev, ach.agente, ach.perda_evitavel)
            self.casos.append(c)
            self._playbook(c, ach)
        self._causa_raiz()
        return self

    def _causa_raiz(self):
        """Auditor procura padrão nos erros: mesmo lançador, mesmo processo."""
        tit = self.b.titulos.set_index("titulo_id")
        erros = [c for c in self.casos if c.tipo in ("VALOR_DIVERGENTE", "FORNECEDOR_ERRADO", "DUPLICIDADE", "GOLPE_TROCA_CONTA")]
        lanc = collections.Counter(tit.loc[c.titulo_id, "lancado_por"] for c in erros if c.tipo == "VALOR_DIVERGENTE" and "vírgula" in c.resumo)
        usu = self.b.usuarios.set_index("login")
        for login, n in lanc.items():
            if n >= 3:
                u = usu.loc[login]
                self._tool(None, "Auditor", "propor_correcao_processo", login,
                           f"{n} títulos com vírgula deslocada lançados por {u.nome} ({u.cargo}, admitido em {u.data_admissao}). "
                           "Proposta: trava no ERP quando valor ≠ duplicata do XML e treinamento/revisão dos lançamentos do júnior.")
                self.incidentes.append({"tipo": "erro_de_lancamento", "lancador": f"{u.nome} ({login})", "qtd": n})
        dups = [c for c in self.casos if c.tipo == "DUPLICIDADE"]
        if dups:
            self._tool(None, "Auditor", "propor_correcao_processo", "lancamento boleto_email",
                       f"{len(dups)} NFs lançadas 2x (XML do portal + boleto do e-mail). Proposta: ERP bloquear título com mesma "
                       "raiz de CNPJ + NF normalizada + parcela.")
        pagos = [c for c in self.casos if c.tipo == "JA_PAGO_FORA_DO_LOTE"]
        if pagos:
            self._tool(None, "Auditor", "propor_correcao_processo", "pagamento manual",
                       f"{len(pagos)} pagamentos manuais sem baixa. Proposta: conciliação diária automática extrato × agenda.")

    # ------------------------------------------------------------ decisão humana
    def decidir(self, caso_id: str, aprovado: bool, quem: str = "humano") -> Caso | None:
        c = next((x for x in self.casos if x.id == caso_id), None)
        if not c or c.status != "aguardando_aprovacao":
            return c
        acao = c.aprovacao["acao"]
        if aprovado:
            self._tool(c, f"Humano ({quem})", "aprovar_acao", c.titulo_id, acao, "humano", c.aprovacao["nome"])
            if acao.startswith("reverter_alteracao_cadastro"):
                self._tool(c, "Auditor", "reverter_alteracao_cadastro", c.fornecedor_id,
                           "cadastro volta para a conta anterior confirmada")
                self.fornecedores_bloqueados.discard(c.fornecedor_id)
                for x in self.casos:
                    if x.fornecedor_id == c.fornecedor_id:
                        self.titulo_status[x.titulo_id] = "agendado"
                        x.status = "resolvido"
                self._tool(c, "Analista", "agendar_titulo", c.fornecedor_id,
                           "títulos do fornecedor voltam aos lotes, agora para a conta legítima")
            elif acao.startswith("cancelar_titulo"):
                self.titulo_status[c.titulo_id] = "cancelado"
                self._tool(c, "Analista", "cancelar_titulo", c.titulo_id, c.aprovacao["motivo"])
            elif acao.startswith("corrigir_lancamento"):
                self.titulo_status[c.titulo_id] = "corrigido"
                self._tool(c, "Analista", "corrigir_lancamento", c.titulo_id, acao.split(" ", 1)[1])
                self._tool(c, "Analista", "agendar_titulo", c.titulo_id, f"volta ao lote {c.lote} com o valor/fornecedor certo")
            else:
                self.titulo_status[c.titulo_id] = "agendado"
                self._tool(c, "Analista", "agendar_titulo", c.titulo_id, "liberado com exceção aprovada")
            c.status = "resolvido"
        else:
            self._tool(c, f"Humano ({quem})", "recusar_acao", c.titulo_id, acao, "humano", c.aprovacao["nome"])
            self.titulo_status[c.titulo_id] = "bloqueado"
            c.status = "aguardando_humano"
        return c

    # ------------------------------------------------------------ placar
    def placar(self) -> dict:
        ag = self.b.agenda
        casos_por_titulo = {c.titulo_id: c for c in self.casos}
        perda_sem_agente = sum(c.perda_evitada for c in self.casos)
        # custo do agente: acionamentos humanos (pior caso: todos contados) + atraso de títulos legítimos seguros
        acion = [a for a in self.log if a.ferramenta == "acionar_pessoa"]
        aprov = [a for a in self.log if a.ferramenta == "solicitar_aprovacao"]
        atraso = 0.0
        for c in self.casos:
            legitimo = c.tipo in ("OC_INVALIDA",) and c.perda_evitada == 0
            if legitimo:
                atraso += c.valor * (0.02 + 0.01 * 7 / 30) + CUSTO_RELACIONAMENTO.get(self.forn_cat.get(c.fornecedor_id), 300)
        custo_acion = CUSTO_ACIONAMENTO * len(acion)
        tipos = collections.Counter(c.tipo for c in self.casos)
        perdas_tipo = collections.defaultdict(float)
        for c in self.casos:
            perdas_tipo[c.tipo] += c.perda_evitada
        auto = sum(1 for c in self.casos if c.status == "resolvido")
        return {
            "titulos_na_agenda": int(len(ag)),
            "valor_na_agenda": float(ag.valor.sum()),
            "lotes": int(ag.lote_remessa.nunique()),
            "titulos_conferidos": int(len(ag)),
            "casos": len(self.casos),
            "resolvidos_sozinho": auto,
            "aguardando_aprovacao": sum(1 for c in self.casos if c.status == "aguardando_aprovacao"),
            "aguardando_humano": sum(1 for c in self.casos if c.status == "aguardando_humano"),
            "acoes_executadas": sum(1 for a in self.log if a.modo == "auto"),
            "acionamentos": len(acion),
            "aprovacoes_pedidas": len(aprov),
            "perda_sem_agente": perda_sem_agente,
            "custo_agente": custo_acion + atraso,
            "custo_acionamentos": custo_acion,
            "custo_atraso": atraso,
            "placar_sem_agente": -perda_sem_agente,
            "placar_com_agente": -(custo_acion + atraso),
            "por_tipo": {k: {"qtd": tipos[k], "perda": perdas_tipo[k]} for k in tipos},
        }

    def tabela_casos(self) -> pd.DataFrame:
        return pd.DataFrame([{k: v for k, v in asdict(c).items() if k not in ("acoes", "evidencias", "aprovacao")} for c in self.casos])

    def tabela_log(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(a) for a in self.log])
