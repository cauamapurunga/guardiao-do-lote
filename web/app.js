const $ = s => document.querySelector(s);
const brl = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 0, maximumFractionDigits: 0});
const brlc = v => v >= 1e6 ? 'R$ ' + (v / 1e6).toLocaleString('pt-BR', {maximumFractionDigits: 2}) + ' mi' : v >= 1e4 ? 'R$ ' + Math.round(v / 1e3) + ' mil' : brl(v);
const brl2 = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const COR_AG = {Sentinela: '#111', Analista: '#3060d0', Auditor: '#d93a3a', Leitor: '#7a5ad6'};
const ICO_OK = '<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const ICO_X = '<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const STATUS = {resolvido: ['Agente resolveu', 'res'], aguardando_aprovacao: ['Esperando aprovação', 'apr'], aguardando_humano: ['Pessoa avisada', 'hum']};
let E = null, filtro = null, selDec = null;

function toast(t) { const el = $('#toast'); el.textContent = t; el.classList.add('on'); setTimeout(() => el.classList.remove('on'), 2600); }
function pill(c) { return `<span class="pill" style="color:${c.cor};background:${c.cor}1a">${esc(c.tipo_titulo)}</span>`; }

async function carregar() {
  E = await (await fetch('/api/estado')).json();
  render();
}

function render() {
  const p = E.placar, casos = E.casos;
  const pend = casos.filter(c => c.status === 'aguardando_aprovacao');
  $('#nPend').textContent = pend.length;
  $('#sTg').className = E.telegram.token ? 'ok' : '';
  $('#sIa').className = E.ia.ativa ? 'ok' : '';
  // hoje
  $('#hTitulo').innerHTML = `${brl(p.perda_sem_agente)} iam sair errado.<br>O Guardião segurou tudo antes do banco.`;
  $('#hLead').textContent = `Ele conferiu os ${p.titulos_na_agenda} títulos de ${p.lotes} lotes contra o ERP, Compras, notas fiscais, boletos, os dois bancos e o e-mail. Resolveu ${p.resolvidos_sozinho} problemas sozinho e deixou ${pend.length} decisões para quem tem a alçada.`;
  $('#vSem').textContent = '−' + brl(p.perda_sem_agente);
  $('#vCom').textContent = '−' + brl(p.custo_agente);
  $('#vExp').textContent = `Custo com o Guardião: ${p.acionamentos} pessoas acionadas (R$ 60 cada, pela regra do desafio) e 1 pagamento legítimo que fica retido até a compra ser aprovada.`;
  const max = Math.max(...E.por_tipo.map(t => t.perda));
  $('#bars').innerHTML = E.por_tipo.sort((a, b) => b.perda - a.perda).map(t => `
    <div class="bar"><span>${esc(t.tipo)}</span><div class="tr"><i style="width:${100 * t.perda / max}%;background:${t.cor}"></i></div>
    <span class="v num">${brl(t.perda)}</span><span class="q">${t.qtd} ${t.qtd > 1 ? 'títulos' : 'título'}</span></div>`).join('');
  // quadro de saídas: dias nas colunas, banco nas linhas
  const dias = [...new Set(E.lotes.map(l => l.fecha.split(' ')[0]))];
  const bancos = [['Meridiano', '10:00'], ['Litoral', '14:00']];
  let q = `<div class="hd"></div>` + dias.map(d => `<div class="hd">${esc(d)}</div>`).join('');
  for (const [bn, hr] of bancos) {
    q += `<div class="rot">${bn}<small>fecha ${hr}</small></div>`;
    for (const d of dias) {
      const l = E.lotes.find(x => x.banco === bn && x.fecha.startsWith(d));
      if (!l) { q += `<div class="c vazio"></div>`; continue; }
      q += `<div class="c ${l.segurado ? 'risco' : ''}"><b class="num">${brlc(l.valor)}</b><span>${l.titulos} títulos</span>
        ${l.segurado ? `<em class="num">${brlc(l.segurado)} retidos</em>` : '<span>sem problema</span>'}</div>`;
    }
  }
  $('#quadro').style.setProperty('--dias', dias.length);
  $('#quadro').innerHTML = q;
  $('#conferido').textContent = E.simulacao
    ? `Dia simulado: ${E.simulacao.injetados} problemas novos sorteados, ${E.simulacao.pegos} pegos pelos agentes · conferido ${E.conferido_em}`
    : `Última conferência: ${E.conferido_em || '—'} · confere sozinho de hora em hora`;
  renderDec(); renderCasos(); renderLotes(); renderConfia();
}

function renderDec() {
  const pend = E.casos.filter(c => c.status === 'aguardando_aprovacao');
  const feitos = E.humanos.slice().reverse();
  $('#dTitulo').textContent = pend.length ? `${pend.length} decisões esperando alguém` : 'Nada esperando decisão';
  if (!selDec || !E.casos.find(c => c.id === selDec)) selDec = (pend[0] || E.casos[0]).id;
  pend.sort((a, b) => a.horas - b.horas || b.valor - a.valor);
  const quando = h => h < 48 ? `sai em ${h}h` : `sai em ${Math.round(h / 24)} dias`;
  $('#listaDec').innerHTML = pend.map(c => `
    <div class="card item ${c.id === selDec ? 'sel' : ''}" data-id="${c.id}">
      <div><div style="display:flex;gap:10px;align-items:center;margin-bottom:6px">${pill(c)}<span class="urg ${c.horas < 30 ? 'quente' : ''}">${quando(c.horas)}</span><span class="mut" style="font-size:13px">${c.id}</span></div>
      <div class="t">${esc(c.tipo_frase)}</div>
      <div class="meta"><span>${esc(c.fornecedor)}</span><span>Lote ${esc(c.lote)} · sai ${esc(c.fechamento)}</span></div></div>
      <div class="val num">${c.valor_fmt}</div>
      <div class="acts"><button class="btn ok sm" data-ap="${c.id}">Aprovar</button><button class="btn no sm" data-rc="${c.id}">Recusar</button>
      <button class="btn sm" data-ver="${c.id}">Ver detalhes</button><span class="para">Para <b style="color:var(--ink)">${esc(c.para)}</b> · ${esc(c.pedido)}</span></div>
      <div class="cons"><div class="a"><b>Se aprovar</b>${esc(c.se_aprovar)}</div><div class="r"><b>Se recusar</b>${esc(c.se_recusar)}</div></div>
    </div>`).join('') + (feitos.length ? `<h3 style="margin:18px 0 4px">Já decidido</h3>` + feitos.map(h => `
    <div class="card item done"><div><div class="t">${h.aprovado ? 'Aprovado' : 'Recusado'} por ${esc(h.quem)}</div><div class="meta">${esc(h.caso)} · ${esc(h.resumo)}</div></div></div>`).join('') : '');
  $('#pvImg').src = `/api/card/${selDec}.png?t=${Date.now()}`;
  $('#pvId').textContent = selDec;
}

function renderCasos() {
  const tipos = [...new Set(E.casos.map(c => c.tipo_titulo))];
  $('#filtros').innerHTML = `<button class="chip ${!filtro ? 'on' : ''}" data-f="">Todos (${E.casos.length})</button>` +
    tipos.map(t => `<button class="chip ${filtro === t ? 'on' : ''}" data-f="${esc(t)}">${esc(t)} (${E.casos.filter(c => c.tipo_titulo === t).length})</button>`).join('');
  const lista = E.casos.filter(c => !filtro || c.tipo_titulo === filtro);
  $('#cConta').textContent = `${lista.length} casos`;
  $('#tCasos').innerHTML = lista.map(c => `<tr data-ver="${c.id}">
    <td>${pill(c)}</td>
    <td>${esc(c.fornecedor)}<div class="mut" style="font-size:12px">título ${c.titulo_id}</div></td>
    <td class="num" style="white-space:nowrap">${esc(c.fechamento)}</td>
    <td class="r num">${c.valor_fmt}</td>
    <td><span class="st ${STATUS[c.status][1]}">${STATUS[c.status][0]}</span></td></tr>`).join('');
}

function renderLotes() {
  $('#tLotes').innerHTML = E.lotes.map(l => `<tr><td><b>${esc(l.lote)}</b></td><td>${esc(l.banco)}</td><td>${esc(l.fecha)}</td>
    <td class="r num">${l.titulos}</td><td class="r num">${brl2(l.valor)}</td><td class="r num">${l.retidos || '—'}</td>
    <td class="r num" style="color:${l.segurado ? 'var(--red)' : 'var(--muted)'};font-weight:600">${l.segurado ? brl2(l.segurado) : '—'}</td></tr>`).join('');
}

function renderConfia() {
  const v = E.validacao;
  if (!v) { $('#proof').innerHTML = '<p class="mut">Rode <code>py validar.py</code> para gerar a prova.</p>'; return; }
  $('#cfQuando').textContent = `rodado em ${v.quando}`;
  const s = v.sorteios || [], p = v.politica || { injetados: 0, certos: 0, extras: 0, tipos: 0 };
  const inj = s.reduce((a, x) => a + x.injetados, 0) + p.injetados, ok = s.reduce((a, x) => a + x.certos, 0) + p.certos,
    extra = s.reduce((a, x) => a + x.extras, 0) + p.extras;
  const nTipos = new Set(v.itens.filter(i => /detectados/.test(i.texto)).map(i => i.texto.split(':')[0])).size;
  const sec = n => v.itens.filter(i => i.secao.startsWith(n));
  const okSec = n => sec(n).every(i => i.ok);
  const limpa = (sec('Base sem')[0] || {}).texto || '';
  const nLimpa = (limpa.match(/^(\d+)/) || [])[1] || '';
  const card = (bom, big, txt) => `<div class="card"><span class="ck ${bom ? '' : 'bad'}">${bom ? ICO_OK : ICO_X}</span><b class="num">${big}</b><span class="mut">${txt}</span></div>`;
  $('#proof').innerHTML =
    card(okSec('Base sem'), '0', `alarmes falsos em ${nLimpa} títulos sem problema`) +
    card(ok === inj && extra === 0, `${ok}/${inj}`, `problemas plantados achados com o tipo certo (${nTipos} tipos, ${s.length + (p.injetados ? 5 : 0)} sorteios)`) +
    card(okSec('Dados emb'), 'Igual', 'resultado com todos os IDs trocados e as linhas embaralhadas') +
    card(okSec('IA'), '0', 'dados inventados pela IA que passam pela trava');
  $('#checks').innerHTML = v.itens.map(i => `<div><span class="${i.ok ? 'o' : 'x'}">${i.ok ? ICO_OK : ICO_X}</span><span>${esc(i.texto)}</span></div>`).join('');
  $('#tSort').innerHTML = s.map(x => `<tr><td>${x.seed}</td><td class="r num">${x.injetados}</td><td class="r num">${x.certos}</td><td class="r num">${x.perdidos}</td><td class="r num">${x.extras}</td></tr>`).join('');
  $('#iaUso').textContent = E.ia.ativa ? `Uso de IA nesta sessão: ${E.ia.uso}` : 'IA desligada nesta sessão (sem AI_PROXY_API_KEY): tudo funciona só com as regras.';
}

function abrir(id) {
  const c = E.casos.find(x => x.id === id);
  const passos = c.acoes.map(a => {
    const ag = a.agente.split(' ')[0];
    return `<div class="s" style="--c:${COR_AG[ag] || '#b07a00'}"><span class="dot"></span><div>
      <div class="w">${esc(a.ts)} · ${esc(a.agente)} · ${a.modo === 'auto' ? 'fez sozinho' : 'chamou pessoa'}</div>
      <div class="f">${esc(a.detalhe)}<code>${esc(a.ferramenta)}</code></div>
      ${a.para ? `<div class="w">para ${esc(a.para)}</div>` : ''}</div></div>`;
  }).join('');
  $('#dIn').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">${pill(c)}<button class="btn sm" id="fechar">Fechar</button></div>
    <div><h2>${esc(c.tipo_frase)}</h2><p class="mut" style="margin-top:6px">${esc(c.fornecedor)} · título ${c.titulo_id} · lote ${esc(c.lote)} (sai ${esc(c.fechamento)})</p></div>
    <div class="two"><div class="card kpi"><b class="num">${c.valor_fmt}</b><span>valor do título</span></div>
      <div class="card kpi"><b class="num" style="color:${c.perda_evitada ? 'var(--red)' : 'var(--muted)'}">${c.perda_fmt}</b><span>sairia errado sem o agente</span></div></div>
    <div><h3 style="margin-bottom:10px">O que ele encontrou, cruzando os sistemas</h3>${c.evidencias.map(e => `<div class="ev" style="margin-bottom:8px">${esc(e)}</div>`).join('')}</div>
    <div class="ia-box" id="iaBox"><b>Em poucas palavras</b> <button class="btn sm" id="btnIa" style="margin-left:8px">Gerar resumo</button>
      <p class="mut" style="margin-top:6px;font-size:13px">A IA escreve; o sistema confere cada número contra as evidências antes de mostrar.</p></div>
    <div><h3 style="margin-bottom:12px">O que os agentes fizeram</h3><div class="tl">${passos}</div></div>
    <div><h3 style="margin-bottom:10px">Como chegou no Telegram</h3><img src="/api/card/${c.id}.png?t=${Date.now()}" style="width:100%;max-width:480px;border-radius:12px;border:1px solid var(--line)"></div>`;
  $('#drawer').classList.add('on'); $('#shade').classList.add('on');
  $('#fechar').onclick = fechar;
  $('#btnIa').onclick = async () => {
    $('#btnIa').textContent = 'Escrevendo…';
    const r = await (await fetch(`/api/explicar/${c.id}`, {method: 'POST'})).json();
    $('#iaBox').innerHTML = `<b>Em poucas palavras</b> <span class="mut" style="font-size:12px">· ${esc(r.fonte)}</span><p style="margin-top:6px">${esc(r.texto)}</p>`;
  };
}
function fechar() { $('#drawer').classList.remove('on'); $('#shade').classList.remove('on'); }

async function decidir(id, aprovar) {
  const el = document.querySelector(`.item[data-id="${id}"]`);
  if (el) el.querySelectorAll('button').forEach(b => b.classList.add('loading'));
  const r = await fetch('/api/decidir', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({caso: id, aprovar, quem: 'Painel'})});
  if (!r.ok) { toast('Não deu para registrar a decisão. Tente de novo.'); if (el) el.querySelectorAll('button').forEach(b => b.classList.remove('loading')); return; }
  toast(aprovar ? 'Aprovado. O agente já executou o restante.' : 'Recusado. O título segue bloqueado.');
  if (el) { el.classList.add('leaving'); await new Promise(r => setTimeout(r, 330)); }
  await carregar();
}

function ir(v) {
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('on', s.id === 'v-' + v));
  if (v === 'agentes' && !$('#sala').src) $('#sala').src = '/sala';
  if (v === 'caixa') carregarCaixa();
  history.replaceState(null, '', '#' + v);
  window.scrollTo(0, 0);
}

document.addEventListener('click', e => {
  const t = e.target.closest('[data-v],[data-go],[data-ap],[data-rc],[data-ver],[data-f],.item');
  if (!t) return;
  if (t.dataset.v) return ir(t.dataset.v);
  if (t.dataset.go) return ir(t.dataset.go);
  if (t.dataset.ap) { e.stopPropagation(); return decidir(t.dataset.ap, true); }
  if (t.dataset.rc) { e.stopPropagation(); return decidir(t.dataset.rc, false); }
  if (t.dataset.ver) { e.stopPropagation(); return abrir(t.dataset.ver); }
  if ('f' in t.dataset) { filtro = t.dataset.f || null; return renderCasos(); }
  if (t.classList.contains('item') && t.dataset.id) { selDec = t.dataset.id; renderDec(); }
});
$('#shade').onclick = fechar;
document.addEventListener('keydown', e => { if (e.key === 'Escape') fechar(); });
$('#btnTg').onclick = async () => {
  $('#btnTg').classList.add('loading'); $('#btnTg').textContent = 'Enviando…';
  const r = await fetch('/api/telegram/enviar', {method: 'POST'});
  $('#btnTg').classList.remove('loading'); $('#btnTg').textContent = 'Enviar para o Telegram';
  const j = await r.json();
  toast(r.ok ? `Enviado no Telegram: ${Object.entries(j.por_pessoa || {}).map(([k, v]) => `${v} para ${k}`).join(', ') || 'nada pendente'}.` : (j.detail || 'Não deu para enviar.'));
};

carregar().then(() => { const h = location.hash.slice(1); if (h) ir(h); });
setInterval(async () => {  // pega aprovações feitas pelo Telegram
  if ($('#drawer').classList.contains('on')) return;
  const antes = E && E.humanos.length;
  const n = await (await fetch('/api/estado')).json();
  if (E && n.humanos.length !== antes) { E = n; render(); toast('Decisão recebida pelo Telegram.'); }
}, 4000);
window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (h && E) ir(h); });

const PED = {troca_conta: 'Trocar conta bancária', cobranca_boleto: 'Cobrança / boleto', pagamento_nao_identificado: 'Pagamento não reconhecido',
  reajuste: 'Reajuste de contrato', pedido_urgente: 'Pedido urgente', outro: 'Outro'};
async function carregarCaixa(r) {
  const d = r || await (await fetch('/api/caixa')).json();
  $('#btnCaixa').textContent = d.ia ? 'Classificado com IA ✓' : 'Classificar com IA (Jev)';
  $('#tCaixa').innerHTML = d.linhas.slice(0, 120).map(l => `<tr>
    <td class="mut" style="white-space:nowrap">${esc(l.data.slice(8, 10) + '/' + l.data.slice(5, 7))}</td>
    <td>${esc(l.remetente)}<div style="font-size:12px;color:${l.origem.includes('IMITA') ? 'var(--red)' : 'var(--muted)'}">${esc(l.origem.replace('⚠️ ', ''))}</div></td>
    <td>${esc(l.assunto)}</td>
    <td>${esc(PED[l.classificacao] || l.classificacao)}${l.confianca != null ? `<div class="mut" style="font-size:12px">confiança ${Math.round(l.confianca * 100)}%</div>` : ''}</td>
    <td><span class="st ${l.risco === 'ALTO' ? 'hum' : l.risco === 'médio' ? 'apr' : 'res'}" style="${l.risco === 'ALTO' ? 'color:var(--red)' : ''}">${esc(l.risco)}</span></td>
    <td style="font-size:13px">${esc(l.acao_do_agente)}</td></tr>`).join('');
}
$('#btnCaixa').onclick = async () => {
  $('#btnCaixa').textContent = 'Classificando 246 mensagens…';
  const r = await fetch('/api/caixa/ia', {method: 'POST'});
  if (!r.ok) { toast((await r.json()).detail || 'IA indisponível'); return carregarCaixa(); }
  carregarCaixa(await r.json()); toast('Mensagens classificadas pela IA.');
};

// glossário: dica ao passar o mouse e lista em "Como funciona"
let GL = {};
fetch('/api/glossario').then(r => r.json()).then(g => {
  GL = g;
  $('#gloss').innerHTML = Object.entries(g).map(([k, v]) => `<div><b>${esc(k)}</b><span class="mut">${esc(v)}</span></div>`).join('');
});
const tip = document.createElement('div'); tip.id = 'gtip'; document.body.appendChild(tip);
document.addEventListener('mouseover', e => {
  const a = e.target.closest('abbr[data-g]');
  if (!a || !GL[a.dataset.g]) return;
  tip.textContent = GL[a.dataset.g];
  const r = a.getBoundingClientRect();
  tip.style.left = Math.min(r.left, innerWidth - 320) + 'px'; tip.style.top = (r.bottom + 8) + 'px';
  tip.classList.add('on');
});
document.addEventListener('mouseout', e => { if (e.target.closest('abbr[data-g]')) tip.classList.remove('on'); });
$('#btnConferir').onclick = async () => {
  const b = $('#btnConferir'); b.classList.add('loading'); b.textContent = 'Conferindo…';
  const r = await fetch('/api/conferir', {method: 'POST'}); const j = await r.json();
  b.classList.remove('loading'); b.textContent = 'Conferir agora';
  if (!r.ok) return toast(j.detail || 'Não deu para conferir');
  toast(`Conferido às ${j.conferido_em}: ${j.casos} casos.`); carregar();
};
if ($('#btnResumo')) $('#btnResumo').onclick = async () => {
  const r = await fetch('/api/resumo/telegram', {method: 'POST'}); const j = await r.json();
  toast(r.ok ? 'Resumo enviado no Telegram.' : (j.detail || 'Não deu para enviar'));
};

$('#btnSimular').onclick = async () => {
  const b = $('#btnSimular'); b.classList.add('loading'); b.textContent = 'Sorteando problemas novos…';
  const r = await fetch('/api/simular', {method: 'POST'}); const j = await r.json();
  b.classList.remove('loading'); b.textContent = 'Simular um dia novo';
  if (!r.ok) return toast(j.detail || 'Não deu para simular');
  $('#sala').removeAttribute('src');
  toast(`Dia novo: ${j.injetados} problemas sorteados em outros fornecedores. Os agentes pegaram ${j.pegos}.`);
  carregar();
};
