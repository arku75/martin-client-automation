// app.js — interfaz del publicador. Sin frameworks: solo el navegador.
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
let ARTICLES = [];   // articulos en pantalla
let CONFIG = null;
let TAXO = null;
let I18N = {};       // textos del idioma activo
let I18N_ALL = {};   // los tres idiomas: el artículo puede ir en otro
let LANGS = {};

// Texto en el idioma del artículo, no en el de la pantalla: la vista previa
// enseña lo que publicará el sitio, y un artículo esloveno titula su FAQ
// «Pogosta vprašanja» aunque estés usando el programa en español.
function TA(key, lang, params) {
  let s = (I18N_ALL[lang] || I18N)[key] || I18N[key] || key;
  if (params) for (const k in params) s = s.split('{' + k + '}').join(params[k]);
  return s;
}
// Modo avanzado apagado por defecto: lo primero que ve alguien es lo simple.
let EXPERT = localStorage.getItem('expert') === '1';

// Traduce una clave. Si falta, devuelve la clave para que el fallo se vea.
function T(key, params) {
  let s = I18N[key] || key;
  if (params) for (const k in params) s = s.split('{' + k + '}').join(params[k]);
  return s;
}

// Aplica los textos a todo lo que lleva data-i18n en el HTML.
function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = T(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-title]').forEach((el) => {
    el.title = T(el.dataset.i18nTitle);
  });
  // Textos que llevan formato dentro (<strong>): se meten como HTML.
  document.querySelectorAll('[data-i18n-html]').forEach((el) => {
    el.innerHTML = T(el.dataset.i18nHtml);
  });
  // La zona de arrastre se pinta desde JS, así que no lleva data-i18n:
  // hay que rehacerla para que cambie de idioma con el resto.
  if (typeof drop !== 'undefined' && drop) resetDrop();
  document.documentElement.lang = CONFIG ? (CONFIG.ui.lang || 'es') : 'es';
}

// ── utilidades ──
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, bad = false, ms = 4000) {
  const t = document.createElement('div');
  t.className = 'toast' + (bad ? ' bad' : '');
  t.innerHTML = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

async function api(path, body, method) {
  const r = await fetch(path, {
    method: method || (body ? 'POST' : 'GET'),
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({ error: 'respuesta no válida' }));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

const readAsB64 = (file) => new Promise((res, rej) => {
  const fr = new FileReader();
  fr.onload = () => res(String(fr.result).split(',')[1]);
  fr.onerror = rej;
  fr.readAsDataURL(file);
});

// ── pestañas ──
$$('.tab').forEach((t) => t.onclick = () => {
  $$('.tab').forEach((x) => x.classList.toggle('on', x === t));
  $$('.panel').forEach((p) => p.classList.toggle('on', p.id === 'p-' + t.dataset.p));
  if (t.dataset.p === 'site') loadSite();
  if (t.dataset.p === 'doctor') runDoctor();
});

// ── tema ──
$('#theme').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : cur === 'light' ? '' : 'dark';
  if (next) document.documentElement.setAttribute('data-theme', next);
  else document.documentElement.removeAttribute('data-theme');
  localStorage.setItem('theme', next);
};
const savedTheme = localStorage.getItem('theme');
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);

// El editor de texto ensancha el diálogo; al cerrarlo (por el botón, Escape o
// como sea) se vuelve al ancho normal para la vista previa y el resto.
$('#dlg').addEventListener('close', () => $('#dlg').classList.remove('wide'));

// ── arrastrar y soltar ──
const drop = $('#drop');
drop.onclick = () => $('#file').click();
$('#file').onchange = (e) => handleFiles(Array.from(e.target.files));
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.add('hot');
}));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.remove('hot');
}));
drop.addEventListener('drop', (e) => handleFiles(Array.from(e.dataTransfer.files)));
// Soltar en cualquier punto de la ventana también vale.
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  if (!drop.contains(e.target) && e.dataTransfer.files.length) {
    handleFiles(Array.from(e.dataTransfer.files));
  }
});

async function handleFiles(files) {
  if (!files.length) return;
  const docs = files.filter((f) => f.name.toLowerCase().endsWith('.docx'));
  const imgs = files.filter((f) => /\.(jpe?g|png|webp|avif|gif|heic|tiff?)$/i.test(f.name));
  const other = files.filter((f) => !docs.includes(f) && !imgs.includes(f));
  if (other.length) toast(T('drop.ignored', { n: other.length }), true);
  if (!docs.length) { toast(T('drop.need_docx'), true); return; }

  drop.innerHTML = `<div class="ico"><span class="spin" style="border-color:hsl(var(--primary)/.3);border-top-color:hsl(var(--primary))"></span></div><h2>${T('drop.reading')}</h2><p>${T('drop.matching')}</p>`;

  const payload = { files: [] };
  for (const f of [...docs, ...imgs]) {
    payload.files.push({ name: f.name, b64: await readAsB64(f) });
  }

  try {
    const res = await api('/api/upload', payload);
    ARTICLES = ARTICLES.concat(res.articles);
    render();
    const n = res.articles.length;
    const paired = res.articles.filter((a) => a.image_file).length;
    toast(T('drop.loaded', { n, p: paired }));
  } catch (e) {
    toast(T('drop.read_error', { msg: esc(e.message) }), true);
  }
  resetDrop();
}

function resetDrop() {
  const mini = ARTICLES.length > 0;
  drop.innerHTML = `<div class="ico">📄🖼️</div>
    <h2>${mini ? T('drop.title_more') : T('drop.title')}</h2>
    <p>${T('drop.hint')}<br>${T('drop.hint2')}</p>`;
  drop.classList.toggle('mini', mini);
}

// ── pintar la lista ──
function matchBadge(a) {
  if (!a.image_file) return `<span class="badge bad">${T('card.no_image')}</span>`;
  const s = a.match_score || 0;
  const cls = s >= 0.6 ? 'ok' : s >= 0.3 ? 'warn' : 'bad';
  const txt = s >= 0.6 ? T('card.matched') : s >= 0.3 ? T('card.probable') : T('card.review');
  return `<span class="badge ${cls}" title="${esc(a.match_reason || '')}">🖼 ${txt}</span>`;
}

function render() {
  const box = $('#list');
  drop.classList.toggle('mini', ARTICLES.length > 0);
  const has = ARTICLES.length > 0;
  $('#bar').style.display = has ? 'flex' : 'none';
  $('#bigbar').style.display = has ? 'block' : 'none';
  $('#steps').style.display = has ? 'none' : 'flex';
  if (!has) { box.innerHTML = ''; return; }
  // Numerar solo los articulos que siguen sin foto: n1, n2, n3...
  // Asi el usuario sabe en que orden arrastrar las imagenes.
  let waitingN = 0;
  const labels = ARTICLES.map((a) => {
    if (a.image_file || a.coverImage) return 0;
    waitingN += 1;
    return waitingN;
  });
  box.innerHTML = EXPERT ? ARTICLES.map((a, i) => cardExpert(a, i, labels[i])).join('')
                         : ARTICLES.map((a, i) => cardSimple(a, i, labels[i])).join('');
  bindPhotoDrops();
  $('#info').textContent = T('bar.info', { n: ARTICLES.length, i: ARTICLES.filter((a) => a.image_file || a.coverImage).length });
  updateBigButton();
  $('#big-go').disabled = ARTICLES.some((a) => !a.publishable);
  $('#big-info').textContent = '';
}

// ── arrastrar foto directamente encima de un articulo concreto ──
function bindPhotoDrops() {
  document.querySelectorAll('.pdz').forEach((zone) => {
    const i = parseInt(zone.dataset.i, 10);
    zone.addEventListener('dragenter', (e) => { e.preventDefault(); zone.classList.add('hot'); });
    zone.addEventListener('dragover',  (e) => { e.preventDefault(); zone.classList.add('hot'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('hot'));
    zone.addEventListener('drop', async (e) => {
      e.preventDefault(); e.stopPropagation();
      zone.classList.remove('hot');
      const f = e.dataTransfer.files[0];
      if (f) await attachPhotoTo(i, f);
    });
  });
}

async function attachPhotoTo(i, file) {
  try {
    const r = await api('/api/attach', {
      index: i, name: file.name, b64: await readAsB64(file), article: ARTICLES[i]
    });
    ARTICLES[i] = r.article;
    render();
    toast(T('toast.image_set'));
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ── vista simple: estado en lenguaje llano, sin jerga ──
function stateOf(a) {
  if (!a.publishable) return { cls: 'bad', txt: T('simple.blocked') };
  // Con la foto ya subida (o traída de la web) no hay nada que emparejar.
  if (a.coverImage) return { cls: 'ok', txt: T('simple.ready') };
  const soft = !a.image_file || (a.match_score && a.match_score < 0.45);
  if (soft) return { cls: 'warn', txt: T('simple.check') };
  return { cls: 'ok', txt: T('simple.ready') };
}

function photoState(a) {
  if (a.coverImage) return { cls: '', txt: T('simple.photo_ok') };
  if (!a.image_file) return { cls: 'bad', txt: T('simple.photo_missing') };
  if (a.match_score < 0.45) return { cls: 'warn', txt: T('simple.photo_check') };
  return { cls: '', txt: T('simple.photo_ok') };
}

function cardSimple(a, i, n) {
  const st = stateOf(a);
  const ph = photoState(a);
  const img = a.image_url || a.thumb_url || '';
  const needsPhoto = !a.image_file && !a.coverImage;
  const prompt = needsPhoto && n
    ? `<div class="pdz" data-i="${i}"><span class="pdz-n">n${n}.</span> ${esc(a.title)} — ${T('simple.drop_here')}</div>`
    : '';
  return `<div class="scard" data-i="${i}">
    <div class="row1">
      ${img ? `<img class="sphoto ${ph.cls}" src="${esc(img)}" onclick="pickImage(${i})" title="${esc(ph.txt)}">`
            : `<div class="sphoto bad" onclick="pickImage(${i})">${T('simple.photo_missing')}</div>`}
      <div class="sinfo">
        <div class="state ${st.cls}"><span class="dot"></span>${st.txt}</div>
        <h3>${esc(a.title)}</h3>
        <div class="sub">${T('simple.words_time', { n: a.word_count, m: a.readingTimeMinutes || 1 })}</div>
        ${prompt}
      </div>
      <div class="sactions">
        <button class="btn ghost sm" onclick="preview(${i})">${T('simple.view')}</button>
        <button class="btn ghost sm" onclick="showBody(${i})">${T('simple.change')}</button>
      </div>
    </div>
    <div class="cbody" id="body-${i}"></div>
  </div>`;
}

function cardExpert(a, i, n) {
  const score = a.seo_score || 0;
  const img = a.image_url || a.thumb_url || '';
  const needsPhoto = !a.image_file && !a.coverImage;
  const prompt = needsPhoto && n
    ? `<div class="pdz" data-i="${i}"><span class="pdz-n">n${n}.</span> ${esc(a.title)} — ${T('simple.drop_here')}</div>`
    : '';
  return `<div class="card" data-i="${i}">
      <div class="chead">
        ${img ? `<img class="thumb" src="${esc(img)}" onclick="pickImage(${i})" title="${T('card.change_image')}">`
              : `<div class="thumb" onclick="pickImage(${i})">${T('card.no_image_click')}</div>`}
        <div class="cmain">
          <div class="ctitle">${esc(a.title)}</div>
          ${prompt}
          <div class="meta-line">
            ${matchBadge(a)}
            <span class="badge">${T('card.words', { n: a.word_count })}</span>
            <span class="badge">${esc(a.contentType || '—')}</span>
            <span class="badge">${esc(a.country || a.continent || T('card.no_destination'))}</span>
            ${a.faq && a.faq.length ? `<span class="badge ok">${T('card.faq_n', { n: a.faq.length })}</span>` : `<span class="badge warn">${T('card.no_faq')}</span>`}
          </div>
          <div class="meta-line mono" style="margin-top:.3rem">${esc(a.articlePath || '')}</div>
        </div>
        <div class="ring" style="--v:${score}"><span>${score}</span></div>
        <div style="display:flex;flex-direction:column;gap:.35rem">
          <button class="btn ghost sm" onclick="toggle(${i})">${T('card.edit')}</button>
          <button class="btn ghost sm" onclick="preview(${i})">${T('card.view')}</button>
        </div>
      </div>
      <div class="cbody" id="body-${i}"></div>
    </div>`;
}

function field(i, key, label, opts = {}) {
  const a = ARTICLES[i];
  const v = a[key] ?? '';
  const lim = opts.limit;
  const over = lim && String(v).length > lim;
  const counter = lim ? `<span class="count ${over ? 'over' : ''}" id="cnt-${i}-${key}">${String(v).length}/${lim}</span>` : '';
  let input;
  if (opts.options) {
    input = `<select onchange="setF(${i},'${key}',this.value)">
      ${opts.allowEmpty ? `<option value=""${!v ? ' selected' : ''}>—</option>` : ''}
      ${opts.options.map((o) => `<option value="${esc(o)}"${o === v ? ' selected' : ''}>${esc(o)}</option>`).join('')}
    </select>`;
  } else if (opts.area) {
    input = `<textarea rows="${opts.rows || 4}" oninput="setF(${i},'${key}',this.value,${lim || 0})">${esc(v)}</textarea>`;
  } else {
    input = `<input value="${esc(v)}" oninput="setF(${i},'${key}',this.value,${lim || 0})">`;
  }
  return `<div class="f ${opts.full ? 'full' : ''}">
    <label>${label}${counter}</label>${input}
    ${opts.hint ? `<div class="hint">${opts.hint}</div>` : ''}</div>`;
}

// ── listas: se editan como texto normal, una idea por línea ──
const listToText = (l) => (l || []).join('\n');
const textToList = (t) => t.split('\n').map((s) => s.trim()).filter(Boolean);
const factsToText = (l) => (l || []).map((f) => f.label || f.value || '').join('\n');
const textToFacts = (t) => textToList(t).map((s) => ({ label: s }));
// FAQ: un bloque por pregunta, la primera línea es la pregunta.
const faqToText = (l) => (l || []).map((f) => `${f.q}\n${f.a}`).join('\n\n');
const textToFaq = (t) => t.split(/\n\s*\n/).map((b) => {
  const [q, ...rest] = b.split('\n').map((s) => s.trim()).filter(Boolean);
  return q && rest.length ? { q, a: rest.join(' ') } : null;
}).filter(Boolean);

function setList(i, key, val, kind) {
  const conv = { list: textToList, facts: textToFacts, faq: textToFaq }[kind];
  ARTICLES[i][key] = conv(val);
  const af = ARTICLES[i].authored_fields || (ARTICLES[i].authored_fields = []);
  if (!af.includes(key)) af.push(key);
  const c = $(`#cnt-${i}-${key}`);
  if (c) c.textContent = T('f.items', { n: ARTICLES[i][key].length });
}

function listField(i, key, label, kind, hint, rows = 4) {
  const to = { list: listToText, facts: factsToText, faq: faqToText }[kind];
  const n = (ARTICLES[i][key] || []).length;
  return `<div class="f full">
    <label>${label}<span class="count" id="cnt-${i}-${key}">${T('f.items', { n })}</span></label>
    <textarea rows="${rows}" oninput="setList(${i},'${key}',this.value,'${kind}')">${esc(to(ARTICLES[i][key]))}</textarea>
    <div class="hint">${hint}</div></div>`;
}

function toggle(i) {
  const el = $('#body-' + i);
  if (el.classList.contains('on')) { el.classList.remove('on'); return; }
  if (!EXPERT) return toggleSimple(i, el);
  const a = ARTICLES[i];
  el.innerHTML = `
    <div class="grid">
      ${field(i, 'title', T('f.title'), { full: true })}
      ${field(i, 'metaTitle', T('f.metaTitle'), { limit: 60, full: true, hint: T('f.metaTitle_hint') })}
      ${field(i, 'metaDescription', T('f.metaDescription'), { limit: 160, area: true, rows: 2, full: true, hint: T('f.metaDescription_hint') })}
      ${field(i, 'slug', T('f.slug'))}
      ${field(i, 'primaryKeyword', T('f.primaryKeyword'))}
      ${field(i, 'category', T('f.category'), { options: TAXO.categories })}
      ${field(i, 'contentType', T('f.contentType'), { options: TAXO.content_types })}
      ${field(i, 'continent', T('f.continent'), { options: TAXO.continents, allowEmpty: true })}
      ${field(i, 'country', T('f.country'), { options: TAXO.countries, allowEmpty: true, hint: T('f.country_hint') })}
      ${field(i, 'region', T('f.region'))}
      ${field(i, 'city', T('f.city'))}
      ${field(i, 'searchIntent', T('f.searchIntent'), { options: TAXO.search_intents })}
      ${field(i, 'author', T('f.author'))}
      ${field(i, 'articlePath', T('f.articlePath'), { full: true })}
      ${field(i, 'excerpt', T('f.excerpt'), { limit: 200, area: true, rows: 2, full: true })}
      ${field(i, 'imageAlt', T('f.imageAlt'), { limit: 120, full: true, hint: T('f.imageAlt_hint') })}
      ${field(i, 'imageCaption', T('f.imageCaption'), { full: true })}
      ${field(i, 'coverImage', T('f.coverImage'), { full: true, hint: T('f.coverImage_hint') })}
    </div>

    <details class="det" ${a.faq && a.faq.length ? 'open' : ''}>
      <summary>${T('sec.blocks')}</summary>
      <div class="grid" style="margin-top:.7rem">
        ${listField(i, 'faq', T('f.faq'), 'faq', T('f.faq_hint'), 8)}
        ${listField(i, 'quickFacts', T('f.quickFacts'), 'facts', T('f.quickFacts_hint'))}
        ${listField(i, 'pros', T('f.pros'), 'list', T('f.pros_hint'), 3)}
        ${listField(i, 'cons', T('f.cons'), 'list', T('f.cons_hint'), 3)}
        ${listField(i, 'packingList', T('f.packingList'), 'list', T('f.packingList_hint'), 3)}
      </div>
    </details>

    <details class="det" ${a.affiliateEnabled ? 'open' : ''}>
      <summary>${T('sec.affiliate')}</summary>
      <label class="row" style="font-size:.82rem;gap:.35rem;margin:.7rem 0">
        <input type="checkbox" ${a.affiliateEnabled ? 'checked' : ''} onchange="setF(${i},'affiliateEnabled',this.checked)" style="width:auto">
        ${T('f.affiliateEnabled')}</label>
      <div class="grid">
        ${field(i, 'affiliateTitle', T('f.affiliateTitle'))}
        ${field(i, 'affiliatePartnerName', T('f.affiliatePartnerName'))}
        ${field(i, 'affiliateButtonText', T('f.affiliateButtonText'))}
        ${field(i, 'affiliateUrl', T('f.affiliateUrl'), { hint: T('f.affiliateUrl_hint') })}
        ${field(i, 'affiliateDescription', T('f.affiliateDescription'), { area: true, rows: 2, full: true })}
      </div>
      <label class="row" style="font-size:.82rem;gap:.35rem;margin-top:.6rem">
        <input type="checkbox" ${a.sponsoredToggle ? 'checked' : ''} onchange="setF(${i},'sponsoredToggle',this.checked)" style="width:auto">
        ${T('f.sponsoredToggle')}</label>
    </details>

    <div class="row" style="margin-top:.8rem">
      <label class="row" style="font-size:.82rem;gap:.35rem"><input type="checkbox" ${a.featured ? 'checked' : ''} onchange="setF(${i},'featured',this.checked)" style="width:auto"> ${T('f.featured')}</label>
      <div class="grow"></div>
      <button class="btn ghost sm" onclick="translateOne(${i},'sl')">${T('btn.translate_sl')}</button>
      <button class="btn ghost sm" onclick="translateOne(${i},'en')">${T('btn.translate_en')}</button>
      <button class="btn ghost sm" onclick="regen(${i})">${T('btn.regen')}</button>
      <button class="btn ghost sm" onclick="findStock(${i})">${T('btn.stock')}</button>
      <button class="btn ghost sm" onclick="showBody(${i})">${T('btn.edit_body')}</button>
      <button class="btn danger sm" onclick="removeArt(${i})">${T('btn.remove')}</button>
    </div>
    <div id="notes-${i}">${notesHtml(a)}</div>`;
  el.classList.add('on');
}

// Editor simple: solo lo que una persona quiere tocar. Lo demás lo pone el
// programa y se puede ver con «todos los ajustes».
function toggleSimple(i, el) {
  const a = ARTICLES[i];
  el.innerHTML = `
    <div class="grid">
      ${field(i, 'title', T('simple.title'), { full: true })}
      ${field(i, 'excerpt', T('simple.summary'), { area: true, rows: 2, full: true })}
    </div>
    <div class="sec" style="margin-top:.9rem;background:hsl(var(--muted)/.5)">
      <div class="sub" style="margin-bottom:.6rem">${T('simple.google_preview')}</div>
      <div style="font-family:Arial,sans-serif;max-width:600px">
        <div style="color:#1a0dab;font-size:1.05rem;line-height:1.3" id="gt-${i}">${esc(a.metaTitle || a.title)}</div>
        <div style="color:#006621;font-size:.8rem">${esc((CONFIG.sites[CONFIG.active_site].url || '') + (a.articlePath || ''))}</div>
        <div style="color:#545454;font-size:.85rem;line-height:1.4" id="gd-${i}">${esc(a.metaDescription || '')}</div>
      </div>
      <div class="grid" style="margin-top:.8rem">
        ${field(i, 'metaTitle', T('simple.google_title'), { limit: 60, full: true })}
        ${field(i, 'metaDescription', T('simple.google_desc'), { limit: 160, area: true, rows: 2, full: true })}
      </div>
    </div>
    <div class="row" style="margin-top:.8rem">
      <button class="btn ghost sm" onclick="showBody(${i})">${T('btn.edit_body')}</button>
      <button class="btn ghost sm" onclick="translateOne(${i},'sl')">${T('btn.translate_sl')}</button>
      <button class="btn ghost sm" onclick="translateOne(${i},'en')">${T('btn.translate_en')}</button>
      <div class="grow"></div>
      <button class="btn ghost sm" onclick="EXPERT=true;document.body.classList.add('expert');$('#expert').checked=true;render();toggle(${i})">${T('simple.all_settings')}</button>
      <button class="btn sm" onclick="toggle(${i})">${T('simple.done')}</button>
    </div>
    <div id="notes-${i}">${notesHtml(a)}</div>`;
  el.classList.add('on');
}

function notesHtml(a) {
  let h = '';
  if (a.errors && a.errors.length) {
    h += `<div class="notes bad"><strong>${T('notes.errors')}</strong><ul>${a.errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>`;
  }
  if (a.warnings && a.warnings.length) {
    h += `<div class="notes warn"><strong>${T('notes.warnings')}</strong><ul>${a.warnings.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>`;
  }
  return h;
}

function setF(i, key, val, limit) {
  ARTICLES[i][key] = val;
  if (key === 'metaTitle' && $(`#gt-${i}`)) $(`#gt-${i}`).textContent = val || ARTICLES[i].title;
  if (key === 'metaDescription' && $(`#gd-${i}`)) $(`#gd-${i}`).textContent = val;
  // Lo que tocas a mano queda marcado como escrito por una persona, para que
  // la IA no te lo reescriba al publicar.
  const af = ARTICLES[i].authored_fields || (ARTICLES[i].authored_fields = []);
  if (!af.includes(key)) af.push(key);
  if (limit) {
    const c = $(`#cnt-${i}-${key}`);
    if (c) { c.textContent = `${val.length}/${limit}`; c.classList.toggle('over', val.length > limit); }
  }
  if (key === 'slug' || key === 'country' || key === 'continent') {
    api('/api/revalidate', { article: ARTICLES[i] }).then((r) => {
      ARTICLES[i] = r.article;
      const ring = document.querySelector(`.card[data-i="${i}"] .ring`);
      if (ring) { ring.style.setProperty('--v', r.article.seo_score); ring.querySelector('span').textContent = r.article.seo_score; }
    }).catch(() => {});
  }
}

function removeArt(i) { ARTICLES.splice(i, 1); render(); }

// Editor del texto con la vista previa al lado: se ve el resultado mientras se
// escribe, con la foto y los datos puestos.
// Pantalla partida: a la izquierda el texto en limpio, a la derecha el anuncio
// tal como quedará, con su foto. Es lo que se usa para revisar antes de subir.
async function showBody(i) {
  const a = ARTICLES[i];
  const L = a.lang || 'sl';
  $('#dlg-title').textContent = T('simple.change') + ' — ' + a.title.slice(0, 42);
  // El editor necesita las dos columnas anchas.
  $('#dlg').classList.add('wide');
  $('#dlg-body').innerHTML = `
    <div class="grid" style="margin-bottom:.8rem">
      <div class="f full"><label>${T('simple.title')}</label>
        <input id="ed-title" value="${esc(a.title)}"></div>
      <div class="f"><label>${T('simple.google_title')} <span class="count" id="c-mt"></span></label>
        <input id="ed-mt" value="${esc(a.metaTitle || '')}"></div>
      <div class="f"><label>${T('simple.google_desc')} <span class="count" id="c-md"></span></label>
        <input id="ed-md" value="${esc(a.metaDescription || '')}"></div>
    </div>
    <div class="split">
      <div><textarea id="bodyedit" spellcheck="false">${esc(a.body)}</textarea></div>
      <div class="live prose" id="livepv"></div>
    </div>
    <div class="row" style="margin-top:.7rem">
      <button class="btn" onclick="saveBody(${i})">${T('btn.save')}</button>
      <button class="btn ghost sm" onclick="pickImage(${i})">${T('card.change_image')}</button>
      <button class="btn ghost sm" onclick="findStock(${i})">${T('btn.stock')}</button>
      <button class="btn ghost sm" onclick="translateOne(${i},'sl')">${T('btn.translate_sl')}</button>
      <button class="btn ghost sm" onclick="translateOne(${i},'en')">${T('btn.translate_en')}</button>
      <div class="grow"></div>
      <span class="hint" id="live-state"></span>
      <button class="btn ghost sm" onclick="$('#dlg').close();toggle(${i})">${T('simple.all_settings')}</button>
    </div>`;
  const ta = $('#bodyedit'), et = $('#ed-title'), emt = $('#ed-mt'), emd = $('#ed-md');
  let timer = null;
  const paint = async () => {
    const title = et.value, mt = emt.value, md = emd.value;
    const r = await api('/api/preview', { article: { ...a, body: ta.value } });
    const img = a.coverImage || a.thumb_url || '';
    $('#livepv').innerHTML =
      (img ? `<img src="${esc(img)}" alt="${esc(a.imageAlt || '')}">` : '') +
      `<h1 class="serif" style="font-size:1.35rem;margin:.7rem 0 .2rem">${esc(title)}</h1>` +
      `<div class="meta-line" style="margin-bottom:.9rem">${esc(a.author)} · ${esc(a.category)}` +
      `${a.country ? ' · ' + esc(a.country) : ''}</div>` +
      (a.quickFacts && a.quickFacts.length ? `<h2>${TA('preview.facts_title', L)}</h2><ul>${
        a.quickFacts.map((f) => `<li>${esc(f.label || '')}</li>`).join('')}</ul>` : '') +
      r.html +
      (a.faq && a.faq.length ? `<h2>${TA('preview.faq_title', L)}</h2>${
        a.faq.map((f) => `<p><strong>${esc(f.q)}</strong><br>${esc(f.a)}</p>`).join('')}` : '');
    const w = ta.value.split(/\s+/).filter(Boolean).length;
    $('#live-state').textContent = T('simple.words_time', { n: w, m: Math.max(1, Math.round(w / 200)) });
    $('#c-mt').textContent = `${mt.length}/60`; $('#c-mt').classList.toggle('over', mt.length > 60);
    $('#c-md').textContent = `${md.length}/160`; $('#c-md').classList.toggle('over', md.length > 160);
  };
  // Cualquier cambio (título, meta o cuerpo) repinta la vista al parar de escribir.
  const onEdit = () => { clearTimeout(timer); timer = setTimeout(paint, 300); };
  [ta, et, emt, emd].forEach((el) => el.oninput = onEdit);
  await paint();
  $('#dlg').showModal();
}

function saveBody(i) {
  const a = ARTICLES[i];
  a.body = $('#bodyedit').value;
  a.title = $('#ed-title').value;
  a.metaTitle = $('#ed-mt').value;
  a.metaDescription = $('#ed-md').value;
  // Lo tocado a mano queda marcado para que la IA no lo reescriba.
  const af = a.authored_fields || (a.authored_fields = []);
  ['body', 'title', 'metaTitle', 'metaDescription'].forEach((k) => {
    if (!af.includes(k)) af.push(k);
  });
  $('#dlg').classList.remove('wide');
  $('#dlg').close(); render(); toast(T('toast.body_saved'));
}

async function preview(i) {
  const a = ARTICLES[i];
  const r = await api('/api/preview', { article: a });
  const img = a.coverImage || a.thumb_url || '';
  const L = a.lang || 'sl';   // idioma del artículo
  $('#dlg-title').textContent = T('dlg.preview');
  const head = $('#dlg .dhead');
  if (head && !head.querySelector('#save-html')) {
    const b = document.createElement('button');
    b.id = 'save-html'; b.className = 'btn ghost sm';
    b.style.marginRight = '.4rem';
    head.insertBefore(b, head.querySelector('button'));
  }
  const sb = $('#save-html');
  sb.textContent = T('btn.save_html');
  sb.title = T('btn.save_html_hint');
  sb.onclick = () => saveHtml(i);
  // Se muestra el post entero como quedará publicado: portada, datos rápidos,
  // cuerpo, FAQ y bloque de patrocinio.
  $('#dlg-body').innerHTML = `<div class="prose">
    ${img ? `<img src="${esc(img)}" alt="${esc(a.imageAlt || '')}">` : ''}
    ${a.imageCaption ? `<div class="hint" style="margin-top:.3rem">${esc(a.imageCaption)}</div>` : ''}
    <h1 class="serif" style="font-size:1.7rem;margin:.9rem 0 .3rem">${esc(a.title)}</h1>
    <div class="meta-line" style="margin-bottom:1rem">
      ${esc(a.author || '')} · ${TA('preview.min', L, { n: a.readingTimeMinutes || 1 })}
      · ${esc(a.category || '')}${a.country ? ' · ' + esc(a.country) : ''}
    </div>
    ${a.quickFacts && a.quickFacts.length ? `<h2>${TA('preview.facts_title', L)}</h2><ul>${
      a.quickFacts.map((f) => `<li>${esc(f.label || f.value || '')}</li>`).join('')}</ul>` : ''}
    ${r.html}
    ${a.pros && a.pros.length ? `<h3>${TA('preview.pros', L)}</h3><ul>${a.pros.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${a.cons && a.cons.length ? `<h3>${TA('preview.cons', L)}</h3><ul>${a.cons.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${a.packingList && a.packingList.length ? `<h3>${TA('preview.packing', L)}</h3><ul>${a.packingList.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${a.faq && a.faq.length ? `<h2>${TA('preview.faq_title', L)}</h2>${
      a.faq.map((f) => `<p><strong>${esc(f.q)}</strong><br>${esc(f.a)}</p>`).join('')}` : ''}
    ${a.affiliateEnabled ? `<div class="sec" style="margin-top:1.2rem">
      <h3>${esc(a.affiliateTitle || '')}</h3>
      <p>${esc(a.affiliateDescription || '')}</p>
      <a class="btn" href="${esc(a.affiliateUrl || '#')}" target="_blank"
         rel="${a.sponsoredToggle ? 'sponsored nofollow' : 'nofollow'}">${esc(a.affiliateButtonText || '')}</a>
      ${a.affiliatePartnerName ? `<div class="hint" style="margin-top:.4rem">${esc(a.affiliatePartnerName)}</div>` : ''}
    </div>` : ''}
    ${a.relatedSlugs && a.relatedSlugs.length ? `<h3>${TA('preview.related', L)}</h3><ul>${
      a.relatedSlugs.map((sl) => `<li class="mono">${esc(sl)}</li>`).join('')}</ul>` : ''}
  </div>`;
  $('#dlg').showModal();
}

// Guarda el artículo como página suelta en el ordenador, con la foto dentro.
async function saveHtml(i) {
  try {
    const r = await api('/api/export', { article: ARTICLES[i] });
    toast('✅ ' + T('toast.saved_html', { file: esc(r.file) }), false, 9000);
  } catch (e) { toast(esc(e.message), true); }
}

async function regen(i) {
  toast(T('toast.ai_asking'));
  try {
    const r = await api('/api/process', { article: ARTICLES[i], use_ai: true, force: true });
    ARTICLES[i] = r.article;
    render(); toggle(i);
    toast(T('toast.seo_regen'));
  } catch (e) { toast(T('toast.ai_failed', { msg: esc(e.message) }), true); }
}

async function translateOne(i, target) {
  toast(T('btn.translating'));
  try {
    const r = await api('/api/translate', { article: ARTICLES[i], target });
    ARTICLES[i] = r.article;
    render();
    toast(esc(r.message));
  } catch (e) { toast(esc(e.message), true); }
}

async function pickImage(i) {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = 'image/*';
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    const r = await api('/api/attach', { index: i, name: f.name, b64: await readAsB64(f), article: ARTICLES[i] });
    ARTICLES[i] = r.article;
    render();
    toast(T('toast.image_set'));
  };
  inp.click();
}

async function findStock(i) {
  const a = ARTICLES[i];
  const q = prompt(T('prompt.stock'), a.primaryKeyword || a.country || a.title);
  if (!q) return;
  try {
    const r = await api('/api/stock', { query: q });
    if (!r.images.length) {
      toast(T('toast.no_stock'), true, 6000);
      return;
    }
    $('#dlg-title').textContent = T('dlg.pick_photo');
    $('#dlg-body').innerHTML = `<div class="imgpick">${r.images.map((im) =>
      `<img src="${esc(im.thumb)}" title="${esc(im.credit)} — ${esc(im.source)}"
        onclick="useStock(${i},'${esc(im.url)}','${esc(im.credit)} / ${esc(im.source)}')">`).join('')}</div>
      <div class="hint" style="margin-top:.6rem">${T('cfg.keys_hint')}</div>`;
    $('#dlg').showModal();
  } catch (e) { toast(esc(e.message), true); }
}

function useStock(i, url, credit) {
  ARTICLES[i].coverImage = url;
  ARTICLES[i].imageCaption = ARTICLES[i].imageCaption || ('Foto: ' + credit);
  ARTICLES[i].image_url = url;
  ARTICLES[i].image_file = '';
  $('#dlg').close(); render(); toast(T('toast.photo_set'));
}

// ── publicar ──
$('#go').onclick = async () => {
  await publishAll($('#status').value, $('#use-ai').checked, $('#go'), $('#info'));
};

// El botón dice lo que hará: si no, se pulsa esperando publicar y sale un
// borrador, que fue justo lo que pasó al probarlo.
function updateBigButton() {
  const n = ARTICLES.length;
  if (!n) return;
  const live = document.querySelector('input[name=pubmode]:checked')?.value === 'published';
  const k = live ? (n === 1 ? 'simple.btn_live_1' : 'simple.btn_live_n')
                 : (n === 1 ? 'simple.btn_draft_1' : 'simple.btn_draft_n');
  const b = $('#big-go');
  b.textContent = T(k, { n });
  b.style.background = live ? 'hsl(var(--destructive))' : 'hsl(var(--primary))';
}
document.querySelectorAll('input[name=pubmode]').forEach((r) => r.onchange = updateBigButton);

// ── botón grande de la vista simple ──
$('#big-go').onclick = async () => {
  const mode = document.querySelector('input[name=pubmode]:checked').value;
  await publishAll(mode, $('#use-ai').checked, $('#big-go'), $('#big-info'));
};

async function publishAll(status, useAI, btn, info) {
  const original = btn.textContent;
  btn.disabled = true;
  let ok = 0, fail = 0;
  for (let i = 0; i < ARTICLES.length; i++) {
    btn.innerHTML = `<span class="spin"></span> ` + T('simple.publishing', { i: i + 1, n: ARTICLES.length });
    if (info) info.textContent = ARTICLES[i].title.slice(0, 60);
    try {
      const r = await api('/api/publish', { article: ARTICLES[i], status, use_ai: useAI });
      if (ARTICLES[i].existing) r.message = T('toast.updated');
      ARTICLES[i] = r.article;
      if (r.ok) {
        ok++;
        toast(`✅ <strong>${esc(r.article.title.slice(0, 40))}</strong><br>${esc(r.message)}` +
              (r.url ? `<br><a href="${esc(r.url)}" target="_blank">${T('toast.open_site')}</a>` : ''), false, 7000);
      } else { fail++; toast(`❌ ${esc(r.article.title.slice(0, 40))}<br>${esc(r.message)}`, true, 8000); }
    } catch (e) { fail++; toast('❌ ' + esc(e.message), true, 8000); }
  }
  btn.disabled = false; btn.textContent = original;
  const msg = fail ? T('bar.done', { ok, fail }) : T('simple.published_ok', { n: ok });
  if (info) info.textContent = msg;
  $('#info').textContent = msg;
  render();
}

// ── modo avanzado ──
$('#expert').onchange = () => {
  EXPERT = $('#expert').checked;
  localStorage.setItem('expert', EXPERT ? '1' : '0');
  document.body.classList.toggle('expert', EXPERT);
  render();
};

// ── comprobar que todo funciona, en lenguaje llano ──
$('#check-all').onclick = async () => {
  const box = $('#check-out');
  box.innerHTML = `<div class="empty">${T('doc.checking')}</div>`;
  try {
    const r = await api('/api/doctor');
    // Ollama apagada no es un fallo: el programa no la necesita.
    const bad = r.checks.filter((c) => !c.ok && !/Ollama/i.test(c.check));
    const good = bad.length === 0;
    box.innerHTML = `<div class="notes ${good ? 'warn' : 'bad'}" style="${good ? 'background:hsl(var(--primary)/.08);border-color:hsl(var(--primary)/.3)' : ''}">
      <strong>${good ? '✓ ' + T('simple.all_ok') : '⚠ ' + T('simple.some_bad')}</strong>
      ${bad.length ? `<ul>${bad.map((c) => `<li>${esc(c.detail)}${c.fix ? '<br><em>' + esc(c.fix) + '</em>' : ''}</li>`).join('')}</ul>` : ''}
    </div>`;
  } catch (e) { box.innerHTML = `<div class="notes bad">${esc(e.message)}</div>`; }
};

// ── artículos del sitio ──
async function loadSite() {
  const box = $('#site-list');
  box.innerHTML = `<div class="empty">${T('site.loading')}</div>`;
  try {
    const r = await api('/api/articles');
    if (!r.articles.length) { box.innerHTML = `<div class="empty">${T('site.empty')}</div>`; return; }
    box.innerHTML = `<table><thead><tr><th>${T('site.col_title')}</th><th>${T('site.col_slug')}</th><th>${T('site.col_dest')}</th><th>${T('site.col_type')}</th><th>${T('site.col_status')}</th><th></th></tr></thead><tbody>
      ${r.articles.map((a) => `<tr>
        <td>${esc(a.title || '')}</td>
        <td class="mono">${esc(a.slug || '')}</td>
        <td>${esc([a.continent, a.country].filter(Boolean).join(' › ') || '—')}</td>
        <td>${esc(a.contentType || '—')}</td>
        <td><span class="badge ${a.status === 'published' ? 'ok' : ''}">${esc(a.status || '')}</span></td>
        <td style="white-space:nowrap">
          <a class="btn ghost sm" href="${esc(r.site_url + (a.articlePath || '/clanki/' + a.slug + '/'))}" target="_blank">${T('site.open')}</a>
          <button class="btn ghost sm" onclick="editLive('${esc(a.slug)}')">${T('site.edit')}</button>
          <button class="btn danger sm" onclick="delLive('${esc(a.slug)}','${esc((a.title||'').replace(/'/g,''))}')">${T('site.delete')}</button>
        </td>
      </tr>`).join('')}</tbody></table>`;
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
$('#reload-site').onclick = loadSite;

// Traer un artículo ya publicado, cambiarlo y volver a subirlo (se actualiza,
// no se duplica).
async function editLive(slug) {
  try {
    const r = await api('/api/fetch', { slug });
    ARTICLES.push(r.article);
    $$('.tab').forEach((x) => x.classList.toggle('on', x.dataset.p === 'publish'));
    $$('.panel').forEach((p) => p.classList.toggle('on', p.id === 'p-publish'));
    render();
    toggle(ARTICLES.length - 1);
    toast(T('site.loaded_edit'), false, 6000);
  } catch (e) { toast(esc(e.message), true); }
}

// Borrar de la web, con confirmación: no hay vuelta atrás.
async function delLive(slug, title) {
  if (!confirm(T('site.confirm_del', { t: title || slug }))) return;
  try {
    const r = await api('/api/delete', { slug });
    if (r.ok) { toast(T('site.deleted', { s: esc(slug) })); loadSite(); }
    else toast(esc(r.message), true);
  } catch (e) { toast(esc(e.message), true); }
}

// ── configuración ──
function fillConfig() {
  const c = CONFIG, s = c.sites[c.active_site];
  $('#c-url').value = s.url; $('#c-api').value = s.api_base;
  $('#c-user').value = s.username || ''; $('#c-pass').value = s.password || '';
  $('#c-author').value = s.default_author || '';
  const cl = c.images.cloudinary;
  $('#c-cloud').value = cl.cloud_name || ''; $('#c-ckey').value = cl.api_key || '';
  $('#c-csecret').value = cl.api_secret || ''; $('#c-cpreset').value = cl.upload_preset || '';
  $('#c-cfolder').value = cl.folder || ''; $('#c-ctransform').value = cl.transform || '';
  $('#c-backend').value = (c.images.backend_order || [])[0] || '';
  $('#c-ourl').value = c.ollama.url; $('#c-oenabled').checked = !!c.ollama.enabled;
  $('#c-tenabled').checked = !!c.translate.enabled;
  $('#c-tlang').value = c.translate.target || 'sl';
  $('#cfg-path').textContent = c.config_path || '';
  const models = c.ollama_models || [];
  const opts = (sel) => models.map((m) => `<option value="${esc(m)}"${m === sel ? ' selected' : ''}>${esc(m)}</option>`).join('')
    || `<option value="${esc(sel)}">${esc(sel)} (Ollama no responde)</option>`;
  $('#c-omodel').innerHTML = opts(c.ollama.model);
  $('#c-ovision').innerHTML = opts(c.ollama.vision_model);
  backendHint();
}

function backendHint() {
  const v = $('#c-backend').value;
  const h = { '': 'cfg.hint_disabled', cloudinary_signed: 'cfg.hint_signed', cloudinary_unsigned: 'cfg.hint_unsigned',
              catbox: 'cfg.hint_catbox' }[v];
  $('#backend-hint').textContent = h ? T(h) : '';
}
$('#c-backend').onchange = backendHint;

$('#save-cfg').onclick = async () => {
  const c = CONFIG, s = c.sites[c.active_site];
  s.url = $('#c-url').value.trim(); s.api_base = $('#c-api').value.trim();
  s.username = $('#c-user').value.trim(); s.password = $('#c-pass').value;
  s.default_author = $('#c-author').value.trim();
  Object.assign(c.images.cloudinary, {
    cloud_name: $('#c-cloud').value.trim(), api_key: $('#c-ckey').value.trim(),
    api_secret: $('#c-csecret').value.trim(), upload_preset: $('#c-cpreset').value.trim(),
    folder: $('#c-cfolder').value.trim(), transform: $('#c-ctransform').value.trim(),
  });
  const first = $('#c-backend').value;
  // Only the explicitly selected provider receives images; no public fallback.
  c.images.backend_order = first ? [first] : [];
  c.ollama.url = $('#c-ourl').value.trim();
  c.ollama.model = $('#c-omodel').value; c.ollama.vision_model = $('#c-ovision').value;
  c.ollama.enabled = $('#c-oenabled').checked;
  c.translate.enabled = $('#c-tenabled').checked;
  c.translate.target = $('#c-tlang').value;
  try { await api('/api/config', { config: c }); toast(T('cfg.saved')); boot(); }
  catch (e) { toast(esc(e.message), true); }
};

$('#test-img').onclick = async () => {
  toast(T('cfg.test_img') + '…');
  try {
    const r = await api('/api/test-image', {});
    toast('✅ ' + T('cfg.test_ok', { backend: esc(r.backend) }) + `<br><a href="${esc(r.url)}" target="_blank">${T('cfg.view_image')}</a>`, false, 9000);
  } catch (e) { toast('❌ ' + esc(e.message), true, 9000); }
};

// ── diagnóstico ──
async function runDoctor() {
  const box = $('#doc-out');
  box.innerHTML = `<div class="empty">${T('doc.checking')}</div>`;
  try {
    const r = await api('/api/doctor');
    box.innerHTML = r.checks.map((c) => `
      <div class="row" style="padding:.55rem 0;border-bottom:1px solid hsl(var(--border));align-items:flex-start">
        <span class="badge ${c.ok ? 'ok' : 'bad'}">${c.ok ? '✓' : '✗'}</span>
        <div style="flex:1;min-width:0">
          <strong style="font-size:.88rem">${esc(c.check)}</strong>
          <div class="hint">${esc(c.detail)}</div>
          ${c.fix ? `<div class="notes warn" style="margin-top:.35rem">${esc(c.fix)}</div>` : ''}
        </div>
      </div>`).join('');
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
$('#run-doctor').onclick = runDoctor;

// ── contraseña, en la primera pantalla ──
$('#quick-save').onclick = async () => {
  const pass = $('#quick-pass').value;
  if (!pass) return;
  CONFIG.sites[CONFIG.active_site].password = pass;
  $('#quick-state').textContent = '…';
  await api('/api/config', { config: CONFIG });
  try {
    const r = await api('/api/doctor');
    const sess = r.checks.find((c) => /Sesi|Session|Seja/i.test(c.check));
    if (sess && sess.ok) {
      $('#quick-state').textContent = '✓ ' + T('simple.password_ok');
      setTimeout(() => { $('#setup').style.display = 'none'; }, 1200);
    } else {
      $('#quick-state').textContent = '✗ ' + (sess ? sess.detail : '');
    }
  } catch (e) { $('#quick-state').textContent = esc(e.message); }
};

// ── idioma del programa ──
$('#lang').onchange = async () => {
  CONFIG.ui.lang = $('#lang').value;
  await api('/api/config', { config: CONFIG });
  await boot();
  render();   // las tarjetas ya pintadas también cambian de idioma
};

// ── arranque ──
async function boot() {
  const i = await api('/api/i18n');
  I18N = i.strings; LANGS = i.langs; I18N_ALL = i.all || {};
  const r = await api('/api/bootstrap');
  CONFIG = r.config; TAXO = r.taxonomy;
  $('#lang').innerHTML = Object.entries(LANGS).map(([k, v]) =>
    `<option value="${k}"${k === i.lang ? ' selected' : ''}>${esc(v)}</option>`).join('');
  // Modo simple o avanzado, tal como se dejó la última vez.
  $('#expert').checked = EXPERT;
  document.body.classList.toggle('expert', EXPERT);
  // Sin contraseña no se puede publicar: se pide en la propia pantalla,
  // en vez de dejar que lo descubra al fallar la publicación.
  const site = r.config.sites[r.config.active_site];
  $('#setup').style.display = site.api_base && site.username && !site.password ? 'block' : 'none';
  applyI18n();
  $('#site-badge').textContent = r.config.sites[r.config.active_site].name;
  // La casilla de la barra refleja el interruptor de Configuración: marcarla
  // cuando la IA está apagada prometería algo que luego no ocurre.
  const ai = $('#use-ai');
  ai.checked = !!r.config.ollama.enabled;
  ai.disabled = !r.config.ollama.enabled;
  ai.parentElement.title = r.config.ollama.enabled ? '' : T('bar.ai_off_hint');
  fillConfig();
}
// Señal de vida: el programa se apaga solo cuando cierras esta ventana.
setInterval(() => fetch('/api/ping').catch(() => {}), 5000);
fetch('/api/ping').catch(() => {});

boot().catch((e) => toast(T('toast.boot_error', { msg: esc(e.message) }), true));
