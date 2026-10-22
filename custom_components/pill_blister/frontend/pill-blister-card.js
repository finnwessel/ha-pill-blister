/* pill-blister-card – bundled with the Pill Blister integration.
 * Reads everything from the status sensor (sensor.<name>_pill_status) and calls the
 * pill_blister.* services. No rules are computed here; the integration owns them.
 *
 * type: custom:pill-blister-card
 * entity: sensor.<name>_pill_status
 * settings_hash: '#pille-einstellungen'   # optional, opens a popup via the gear
 * columns: [[6,5,4,3,2,1,0],[0,1,2,3,4,5,6],[6,5,4,3,2,1,0]]   # optional blister layout (0 = Monday)
 */

const WD = ['MO', 'DI', 'MI', 'DO', 'FR', 'SA', 'SO'];
const WD_LANG = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const DEFAULT_COLUMNS = [
  [6, 5, 4, 3, 2, 1, 0],
  [0, 1, 2, 3, 4, 5, 6],
  [6, 5, 4, 3, 2, 1, 0],
];
const UNDO_MS = 8000;
const DOMAIN = 'pill_blister';

const pad = (n) => String(n).padStart(2, '0');
const parseDay = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const wdIdx = (d) => (d.getDay() + 6) % 7;
const fmtDay = (d) => `${WD_LANG[wdIdx(d)]} ${d.getDate()}.${d.getMonth() + 1}.`;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dur = (min) => {
  const a = Math.abs(Math.round(min)); const h = Math.floor(a / 60); const m = a % 60;
  return h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`;
};
const devText = (min) => (min > 0 ? `${dur(min)} später` : `${dur(min)} früher`);
const fmtWhen = (iso) => {
  const d = new Date(iso); const today = new Date();
  const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
  if (dayKey(d) === dayKey(today)) return `heute ${hm(d)}`;
  if (dayKey(d) === dayKey(tomorrow)) return `morgen ${hm(d)}`;
  return `${fmtDay(d)} ${hm(d)}`;
};
const PUNCT = { on_time: 'pünktlich', late: 'später', early: 'früher', missed: 'zu spät', unknown: 'Uhrzeit unbekannt' };

class PillBlisterCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error('entity ist erforderlich (sensor.<name>_pill_status)');
    this._config = { columns: DEFAULT_COLUMNS, settings_hash: null, ...config };
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this._key = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const key = (st ? st.last_updated : 'x') + (this._undoActive() ? 'u' : '');
    if (key === this._key) return;
    this._key = key;
    this._render();
    if (this._openDayKey && this._sheet) this._openDay(this._openDayKey); // keep dialog fresh
  }

  disconnectedCallback() { clearTimeout(this._undoTimer); this._closeSheet(); }
  getCardSize() { return 8; }
  getGridOptions() { return { columns: 12, rows: 'auto' }; }

  get _a() { const st = this._hass && this._hass.states[this._config.entity]; return st ? st.attributes : null; }
  get _status() { const st = this._hass && this._hass.states[this._config.entity]; return st ? st.state : null; }
  _undoActive() { return this._undoUntil && Date.now() < this._undoUntil; }

  _call(service, data = {}, response = false) {
    const a = this._a;
    return this._hass.callWS({
      type: 'call_service', domain: DOMAIN, service,
      service_data: { config_entry_id: a.config_entry_id, ...data },
      return_response: response,
    });
  }

  _haptic(type) { this.dispatchEvent(new CustomEvent('haptic', { detail: type, bubbles: true, composed: true })); }

  _dayInfo(dateStr) { return (this._a.days || []).find((d) => d.date === dateStr) || null; }

  /* ---------------- header ---------------- */

  _header() {
    const a = this._a; const s = this._status;
    const pill = a.pill_number ? `Pille ${a.pill_number} von ${a.cycle_on}` : '';
    const next = parseDay(a.next_blister);
    switch (s) {
      case 'overdue': {
        const d = this._dayInfo(a.overdue_day);
        const until = a.overdue_deadline ? ` · vergessen ab ${hm(new Date(a.overdue_deadline))}` : '';
        return { color: 'orange', icon: 'mdi:alert-circle', title: 'Pille von gestern offen', sub: `${d ? `Pille ${d.pill}` : ''}${until}` };
      }
      case 'due': {
        const until = a.missed_deadline ? ` · vergessen ab ${fmtWhen(a.missed_deadline)}` : '';
        return { color: 'orange', icon: 'mdi:alert-circle', title: 'Pille fällig', sub: `Seit ${a.dose_time} Uhr · ${pill}${until}` };
      }
      case 'done': {
        const t = a.taken_at ? ` um ${hm(new Date(a.taken_at))}` : '';
        const p = a.punctuality && a.punctuality !== 'on_time' && a.punctuality !== 'unknown' ? ` (${PUNCT[a.punctuality]})` : '';
        const tomorrow = a.pill_number >= a.cycle_on ? 'ab morgen Pause' : `morgen ${WD_LANG[(wdIdx(parseDay(a.today)) + 1) % 7]}`;
        return { color: 'green', icon: 'mdi:check-circle', title: 'Erledigt für heute', sub: `${pill}${t}${p} · ${tomorrow}` };
      }
      case 'pause': {
        const left = Math.round((next - parseDay(a.today)) / 86400000);
        return { color: 'grey', icon: 'mdi:pause-circle-outline', title: 'Pillenpause', sub: `Noch ${left} ${left === 1 ? 'Tag' : 'Tage'} · neuer Blister ${fmtDay(next)}` };
      }
      case 'last_pause_day':
        return { color: 'pink', icon: 'mdi:package-variant', title: 'Morgen neuer Blister', sub: `Letzter Pausentag · Start mit der ${WD[wdIdx(next)]}-Pille` };
      default:
        return { color: 'pink', icon: 'mdi:clock-outline', title: 'Heute Abend', sub: `Um ${a.dose_time} Uhr · ${pill}` };
    }
  }

  /* ---------------- banners ---------------- */

  _noticeBanner() {
    const notices = this._a.notices || [];
    if (!notices.length) return '';
    const replacement = notices.filter((n) => n.kind === 'replacement');
    const reduce = notices.filter((n) => n.kind !== 'replacement');
    let html = '';
    if (replacement.length) {
      const n = replacement[0];
      html += `<div class="banner action"><ha-icon icon="mdi:pill-multiple"></ha-icon><div>
        <div class="b-title">Ersatzpille bis ${fmtWhen(n.end)} möglich</div>
        <div class="b-sub">${esc(n.reason)}</div>
        ${n.text ? `<div class="b-text">${esc(n.text)}</div>` : ''}
        <button class="b-btn" data-act="replacement">Ersatzpille genommen</button></div></div>`;
    }
    if (reduce.length) {
      const until = new Date(Math.max(...reduce.map((n) => new Date(n.end))));
      const texts = [...new Set(reduce.map((n) => n.text).filter(Boolean))];
      html += `<div class="banner warn"><ha-icon icon="mdi:shield-alert"></ha-icon><div>
        <div class="b-title">Zusätzlich verhüten bis ${fmtDay(until)} ${hm(until)}</div>
        <div class="b-sub">${reduce.map((n) => esc(n.reason)).join(' · ')}</div>
        ${texts.map((t) => `<div class="b-text">${esc(t)}</div>`).join('')}
        <div class="b-foot">Regeln laut Beipackzettel · im Zweifel Ärztin oder Apotheke fragen</div></div></div>`;
    }
    return html;
  }

  _pendingBanner() {
    const p = this._a.pending;
    if (!p) return '';
    const t = new Date(p.time);
    const opts = (p.options || []).map((ds) => {
      const d = parseDay(ds);
      const [h, m] = this._a.dose_time.split(':').map(Number);
      const dose = new Date(d); dose.setHours(h, m, 0, 0);
      const dev = (t - dose) / 60000;
      const info = this._dayInfo(ds);
      const label = `${dayKey(d) === this._a.today ? 'Heute' : fmtDay(d)}${info ? ` · Pille ${info.pill}` : ''}`;
      const replaces = info && info.state === 'taken' ? ' · ersetzt Eintrag' : '';
      return `<button class="b-btn" data-act="assign" data-day="${ds}">${label}<small>${Math.abs(dev) < 1 ? 'pünktlich' : devText(dev)}${replaces}</small></button>`;
    }).join('');
    return `<div class="banner ask"><ha-icon icon="mdi:help-circle"></ha-icon><div>
      <div class="b-title">Einnahme um ${hm(t)} · für welchen Tag?</div>
      <div class="b-sub">Liegt außerhalb des Einnahmefensters oder der Tag ist schon eingetragen.</div>
      <div class="b-row">${opts}<button class="b-btn ghost" data-act="discard">Verwerfen</button></div></div></div>`;
  }

  /* ---------------- blister ---------------- */

  _blister() {
    const a = this._a;
    const days = a.days || [];
    if (!days.length) return '';
    const cols = this._config.columns;
    const rows = cols[0].length;
    const startWd = days[0].weekday;
    const pause = a.status === 'pause' || a.status === 'last_pause_day';
    const len = days.length;
    let cells = '';
    cols.forEach((col, c) => {
      col.forEach((w, r) => {
        const k = (c * 7 + w - startWd + 3 * len) % len;
        const d = days[k];
        if (!d) return;
        const isToday = d.date === a.today;
        const isOverdue = d.date === a.overdue_day;
        let cls = 'pill'; let inner = '';
        switch (d.state) {
          case 'taken':
            cls = 'empty';
            if (isToday) { cls += ' done'; inner = '<ha-icon icon="mdi:check"></ha-icon>'; }
            if (d.punctuality === 'late' || d.punctuality === 'missed' || d.in_window === false) cls += ' late';
            break;
          case 'untracked': cls = 'empty untracked'; break;
          case 'missing': cls = 'pill missing'; break;
          case 'open': cls = `pill today${isOverdue ? ' overdue' : ''}`; break;
          default: cls = 'pill';
        }
        if (d.events && d.events.length) inner += '<span class="dot"></span>';
        const label = isToday || isOverdue;
        cells += `<span class="lbl${label ? ' lbl-today' : ''}" style="grid-column:${c * 2 + 1};grid-row:${r + 2}">${WD[w]}</span>`
          + `<button class="${cls}" style="grid-column:${c * 2 + 2};grid-row:${r + 2}" data-day="${d.date}" aria-label="${WD[w]}, Pille ${d.pill}">${inner}</button>`;
      });
    });
    let bends = '';
    for (let c = 0; c < cols.length - 1; c++) {
      const endsTop = cols[c][0] > cols[c][cols[c].length - 1];
      bends += `<span class="bend ${endsTop ? 'top' : 'bottom'}" style="grid-column:${c * 2 + 1} / ${c * 2 + 4};grid-row:${endsTop ? 1 : rows + 2}"></span>`;
    }
    return `<div class="foil${pause ? ' paused' : ''}" style="grid-template-columns:repeat(${cols.length}, 26px 40px);grid-template-rows:10px repeat(${rows}, 40px) 10px">${bends}${cells}</div>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const root = this.shadowRoot;
    const a = this._a;
    if (!a) { root.innerHTML = `<ha-card><div style="padding:16px">Entität ${esc(this._config.entity)} nicht gefunden</div></ha-card>`; return; }
    const h = this._header();
    const s = this._status;
    const missing = (a.missing || []).length;
    let cycle;
    if (s === 'pause' || s === 'last_pause_day') cycle = `Blister vom ${fmtDay(parseDay(a.blister_start))} · neuer Blister ${fmtDay(parseDay(a.next_blister))}`;
    else cycle = `Einnahme Tag ${a.cycle_day} von ${a.cycle_on} · Pause ab ${fmtDay(parseDay(a.pause_start))}`;
    if (missing) cycle = `<span class="warn">${missing === 1 ? '1 Tag' : `${missing} Tage`} ohne Eintrag · antippen zum Nachtragen</span>`;

    let action = '';
    if (this._undoActive()) {
      action = `<div class="toast"><ha-icon icon="mdi:check"></ha-icon><span>Eingetragen</span><button class="undo">Rückgängig</button></div>`;
    } else if (s === 'later' || s === 'due' || s === 'overdue') {
      const label = s === 'overdue' ? 'Pille von gestern genommen' : 'Pille genommen';
      action = `<button class="take ${s}"><ha-icon icon="mdi:pill"></ha-icon>${label}</button>`;
    }

    root.innerHTML = `
      <style>${PillBlisterCard.styles}</style>
      <ha-card style="--c: var(--${h.color}-color)">
        <div class="head">
          <div class="ico"><ha-icon icon="${h.icon}"></ha-icon></div>
          <div class="txt"><div class="title">${h.title}</div><div class="sub">${esc(h.sub)}</div></div>
          ${this._config.settings_hash ? '<button class="gear" aria-label="Einstellungen"><ha-icon icon="mdi:cog-outline"></ha-icon></button>' : ''}
        </div>
        ${this._pendingBanner()}
        ${this._noticeBanner()}
        ${this._blister()}
        <div class="cycle">${cycle}</div>
        ${action}
      </ha-card>`;

    root.querySelectorAll('.foil button').forEach((b) => b.addEventListener('click', () => this._openDay(b.dataset.day)));
    const take = root.querySelector('.take'); if (take) take.addEventListener('click', () => this._take());
    const undo = root.querySelector('.undo'); if (undo) undo.addEventListener('click', () => this._undo());
    const gear = root.querySelector('.gear'); if (gear) gear.addEventListener('click', () => this._openSettings());
    root.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => this._bannerAction(b.dataset.act, b.dataset.day)));
  }

  async _bannerAction(act, day) {
    try {
      if (act === 'assign') await this._call('assign_intake', { date: day });
      else if (act === 'discard') await this._call('assign_intake', { discard: true });
      else if (act === 'replacement') await this._call('mark_replacement');
      this._haptic('success');
    } catch (e) { this._toastError(e); }
  }

  _toastError(e) {
    this.dispatchEvent(new CustomEvent('hass-notification', { detail: { message: `Hat nicht geklappt: ${e && e.message ? e.message : e}` }, bubbles: true, composed: true }));
  }

  /* ---------------- take & undo ---------------- */

  async _take() {
    try {
      const res = await this._call('mark_taken', { source: 'dashboard' }, true);
      const r = res && res.response;
      this._haptic('success');
      if (r && !r.pending) {
        this._undoDay = r.day;
        this._undoUntil = Date.now() + UNDO_MS;
        clearTimeout(this._undoTimer);
        this._undoTimer = setTimeout(() => { this._undoUntil = 0; this._key = null; this._render(); }, UNDO_MS + 50);
        this._key = null; this._render();
      }
    } catch (e) { this._toastError(e); }
  }

  async _undo() {
    this._undoUntil = 0; clearTimeout(this._undoTimer);
    try { if (this._undoDay) await this._call('remove_entry', { date: this._undoDay }); this._haptic('light'); } catch (e) { this._toastError(e); }
    this._key = null; this._render();
  }

  _openSettings() {
    history.pushState(null, '', `${location.pathname}${location.search}${this._config.settings_hash}`);
    window.dispatchEvent(new Event('location-changed'));
    window.dispatchEvent(new Event('hashchange'));
  }

  /* ---------------- day dialog ---------------- */

  _openDay(dateStr) {
    const a = this._a; const d = this._dayInfo(dateStr);
    if (!d) return;
    if (this._openDayKey !== dateStr) this._haptic('light');
    this._openDayKey = dateStr;
    const date = parseDay(dateStr);
    const title = `${WD[wdIdx(date)]} · ${date.getDate()}.${date.getMonth() + 1}.`;
    const isToday = dateStr === a.today;
    const now = new Date();
    let status; let body = '';
    const timeRow = (value) => `<label class="row"><span>Uhrzeit</span><input type="time" value="${value}"></label>`;

    if (d.state === 'future') {
      status = { icon: 'mdi:calendar-clock', cls: 'neutral', text: `Kommt am ${fmtDay(date)} um ${a.dose_time} Uhr` };
    } else if (d.state === 'taken') {
      const t = d.time ? new Date(d.time) : null;
      let p = PUNCT[d.punctuality] || '';
      if (t && (d.punctuality === 'late' || d.punctuality === 'early')) p = devText(d.deviation_min);
      if (t && d.punctuality === 'missed') p = `${devText(d.deviation_min)} · gilt als vergessen`;
      const extra = [d.in_window === false ? 'außerhalb des Fensters' : '', d.late_entry ? 'nachgetragen' : ''].filter(Boolean).join(' · ');
      const cls = d.punctuality === 'on_time' ? 'ok' : d.punctuality === 'early' ? 'early' : d.punctuality === 'unknown' ? 'neutral' : 'late';
      status = { icon: 'mdi:check-circle', cls, text: `${t ? `Genommen um ${hm(t)}` : 'Genommen'} · ${p}${extra ? ` · ${extra}` : ''}` };
      if (d.replacement) status.text += ` · Ersatzpille ${hm(new Date(d.replacement))}`;
      body = `${timeRow(t ? hm(t) : a.dose_time)}
        <div class="btns"><button class="btn primary" data-act="set-time">Uhrzeit speichern</button>
        <button class="btn danger" data-act="remove">${isToday ? 'Zurücknehmen' : 'Eintrag entfernen'}</button></div>`;
      body += this._eventsSection(d);
    } else if (d.state === 'open') {
      const overdue = dateStr === a.overdue_day;
      status = { icon: 'mdi:clock-outline', cls: overdue || (isToday && a.status === 'due') ? 'late' : 'neutral',
        text: overdue ? `Noch nicht eingetragen · vergessen ab ${hm(new Date(a.overdue_deadline))}` : `Noch nicht eingetragen · fällig um ${a.dose_time} Uhr` };
      body = `<button class="btn primary wide" data-act="now"><ha-icon icon="mdi:pill"></ha-icon>Jetzt genommen</button>
        <div class="or">oder zu einer anderen Uhrzeit</div>${timeRow(hm(now))}
        <div class="btns"><button class="btn" data-act="set-time">Mit dieser Uhrzeit eintragen</button></div>`;
    } else if (d.state === 'missing') {
      status = { icon: 'mdi:help-circle', cls: 'late', text: 'Nicht in Home Assistant eingetragen' };
      body = `<div class="hint">Wurde sie genommen, aber nur nicht eingetragen? Dann hier nachtragen.</div>${timeRow(a.dose_time)}
        <div class="btns"><button class="btn primary" data-act="set-time">Nachtragen</button>
        <button class="btn" data-act="unknown">Uhrzeit unbekannt</button></div>`;
    } else {
      status = { icon: 'mdi:history', cls: 'neutral', text: 'Vor der Einrichtung · nicht erfasst' };
      body = `${timeRow(a.dose_time)}<div class="btns"><button class="btn" data-act="set-time">Nachtragen</button>
        <button class="btn" data-act="unknown">Uhrzeit unbekannt</button></div>`;
    }

    this._showSheet(`
      <div class="sh-head"><div><div class="sh-title">${title}</div><div class="sh-sub">Pille ${d.pill} von ${a.cycle_on}</div></div>
        <button class="x" aria-label="Schließen"><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="status ${status.cls}"><ha-icon icon="${status.icon}"></ha-icon><span>${esc(status.text)}</span></div>
      ${body}`, (act, sheet, btn) => this._dayAction(act, sheet, dateStr, btn));
  }

  _eventsSection(d) {
    const a = this._a;
    const types = a.event_types || [];
    const evs = (a.events || []).filter((e) => (d.events || []).includes(e.id));
    const name = (key) => (types.find((t) => t.key === key) || { name: key }).name;
    let html = '';
    if (evs.length) {
      html += `<div class="sec">Gemeldet</div>${evs.map((e) => `<div class="evrow"><span>${esc(name(e.type))} · ${hm(new Date(e.time))}</span>
        <button class="btn small danger" data-act="remove-event" data-id="${e.id}">Entfernen</button></div>`).join('')}`;
    }
    if (types.length && d.time) {
      html += `<div class="sec">Danach Erbrechen, Durchfall o. Ä.?</div>
        <label class="row"><span>Wann</span><input type="datetime-local" class="evtime" value="${dayKey(new Date())}T${hm(new Date())}"></label>
        <div class="btns wrap">${types.map((t) => `<button class="btn" data-act="report" data-type="${esc(t.key)}">${esc(t.name)}</button>`).join('')}</div>`;
    }
    return html;
  }

  async _dayAction(act, sheet, dateStr, btn) {
    const input = sheet.querySelector('input[type=time]');
    const time = input && input.value ? `${input.value}:00` : null;
    try {
      if (act === 'now') {
        await this._call('mark_taken', { date: dateStr, time: `${hm(new Date())}:00`, source: 'dashboard' });
      } else if (act === 'set-time') {
        await this._call('mark_taken', { date: dateStr, time, source: 'dashboard' });
      } else if (act === 'unknown') {
        await this._call('mark_taken', { date: dateStr, time_unknown: true, source: 'dashboard' });
      } else if (act === 'remove') {
        await this._call('remove_entry', { date: dateStr });
      } else if (act === 'report') {
        const v = sheet.querySelector('.evtime').value; // YYYY-MM-DDTHH:MM
        await this._call('report_event', { type: btn.dataset.type, datetime: `${v.replace('T', ' ')}:00` });
        this._haptic('success');
        return; // keep the dialog open, it refreshes with the notice
      } else if (act === 'remove-event') {
        await this._call('remove_event', { event_id: btn.dataset.id });
        return;
      }
      this._haptic('success');
      this._closeSheet();
    } catch (e) {
      let el = sheet.querySelector('.err');
      if (!el) { el = document.createElement('div'); el.className = 'err'; sheet.appendChild(el); }
      el.textContent = `Hat nicht geklappt: ${e && e.message ? e.message : e}`;
    }
  }

  _showSheet(html, onAction) {
    const existing = this._sheet;
    const host = existing || document.createElement('div');
    const sr = existing ? host.shadowRoot : host.attachShadow({ mode: 'open' });
    sr.innerHTML = `<style>${PillBlisterCard.sheetStyles}</style>
      <div class="bg"></div><div class="sheet${existing ? ' still' : ''}" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div>`;
    const sheet = sr.querySelector('.sheet');
    sr.querySelector('.bg').addEventListener('click', () => this._closeSheet());
    sr.querySelector('.x').addEventListener('click', () => this._closeSheet());
    sr.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => {
      sr.querySelectorAll('[data-act]').forEach((x) => { x.style.pointerEvents = 'none'; x.style.opacity = '.6'; });
      Promise.resolve(onAction(b.dataset.act, sheet, b)).finally(() => {
        sr.querySelectorAll('[data-act]').forEach((x) => { x.style.pointerEvents = ''; x.style.opacity = ''; });
      });
    }));
    if (!existing) {
      this._escHandler = (ev) => { if (ev.key === 'Escape') this._closeSheet(); };
      window.addEventListener('keydown', this._escHandler);
      document.body.appendChild(host);
      this._sheet = host;
    }
  }

  _closeSheet() {
    if (this._sheet) { this._sheet.remove(); this._sheet = null; }
    this._openDayKey = null;
    if (this._escHandler) { window.removeEventListener('keydown', this._escHandler); this._escHandler = null; }
  }
}

PillBlisterCard.styles = `
  :host { --pill: #f2a3ab; --foil: color-mix(in srgb, #c3c8d1 14%, var(--card-background-color)); }
  ha-card { padding: 16px; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 12px; }
  .ico { width: 42px; height: 42px; border-radius: 50%; flex: none; display: flex; align-items: center; justify-content: center;
    background: color-mix(in srgb, var(--c) 20%, transparent); color: var(--c); }
  .ico ha-icon { --mdc-icon-size: 24px; }
  .txt { flex: 1; min-width: 0; }
  .title { font-size: 16px; font-weight: 600; color: var(--primary-text-color); }
  .sub { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
  button { font: inherit; }
  .gear { all: unset; cursor: pointer; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
  .banner { display: flex; gap: 12px; margin-top: 14px; padding: 12px 14px; border-radius: 14px; --b: var(--orange-color, #ff9800);
    background: color-mix(in srgb, var(--b) 14%, var(--card-background-color)); }
  .banner > ha-icon { color: var(--b); flex: none; margin-top: 1px; }
  .banner.warn { --b: var(--red-color, #f44336); }
  .banner.ask { --b: var(--blue-color, #2196f3); }
  .b-title { font-size: 15px; font-weight: 600; }
  .b-sub { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
  .b-text { font-size: 13px; margin-top: 8px; white-space: pre-line; }
  .b-foot { font-size: 11px; color: var(--secondary-text-color); margin-top: 8px; }
  .b-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  .b-btn { all: unset; cursor: pointer; box-sizing: border-box; margin-top: 10px; padding: 8px 12px; border-radius: 10px; font-size: 14px; font-weight: 600;
    display: inline-flex; flex-direction: column; background: color-mix(in srgb, var(--b) 24%, var(--card-background-color)); }
  .b-row .b-btn { margin-top: 0; }
  .b-btn small { font-size: 11px; font-weight: 500; color: var(--secondary-text-color); }
  .b-btn.ghost { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); justify-content: center; }
  .foil { display: grid; justify-content: center; align-items: center; column-gap: 6px; margin: 16px auto 0; padding: 6px 18px; width: fit-content;
    border-radius: 20px; background: var(--foil); border: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .lbl { font-size: 10px; font-weight: 600; letter-spacing: .4px; color: var(--secondary-text-color); text-align: right; padding-right: 2px; }
  .lbl-today { color: var(--c); font-weight: 800; }
  .bend { align-self: stretch; margin: 0 2px 0 4px; border-color: color-mix(in srgb, var(--primary-text-color) 22%, transparent); border-style: solid; border-width: 0; }
  .bend.top { border-width: 1.5px 1.5px 0 1.5px; border-radius: 6px 6px 0 0; margin-top: 2px; }
  .bend.bottom { border-width: 0 1.5px 1.5px 1.5px; border-radius: 0 0 6px 6px; margin-bottom: 2px; }
  :where(.foil) button { all: unset; box-sizing: border-box; position: relative; width: 32px; height: 32px; margin: 4px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; cursor: pointer; }
  .foil .pill { background: var(--pill); box-shadow: inset 0 -2px 0 color-mix(in srgb, #000 12%, transparent); }
  .foil .empty { background: color-mix(in srgb, #000 22%, var(--foil)); border: 1.5px dashed color-mix(in srgb, var(--primary-text-color) 30%, transparent); }
  .foil .untracked { opacity: .55; }
  .foil .late { border-color: var(--orange-color, #ff9800); }
  .foil .missing { box-shadow: 0 0 0 2.5px var(--foil), 0 0 0 4.5px var(--orange-color, #ff9800); }
  .foil .done { border: 1.5px solid var(--green-color, #4caf50); background: color-mix(in srgb, var(--green-color, #4caf50) 18%, var(--foil)); }
  .foil .done ha-icon { --mdc-icon-size: 18px; color: var(--green-color, #4caf50); }
  .foil .today { box-shadow: 0 0 0 3px var(--foil), 0 0 0 5.5px var(--c); }
  .foil .dot { position: absolute; top: -2px; right: -2px; width: 9px; height: 9px; border-radius: 50%; background: var(--red-color, #f44336); border: 2px solid var(--foil); }
  .foil.paused .pill { opacity: .5; }
  .cycle { margin-top: 10px; text-align: center; font-size: 12px; color: var(--secondary-text-color); }
  .warn { color: var(--orange-color, #ff9800); font-weight: 600; }
  .take { all: unset; box-sizing: border-box; cursor: pointer; margin-top: 14px; width: 100%; height: 52px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 15px; font-weight: 600;
    background: color-mix(in srgb, var(--c) 18%, var(--card-background-color)); color: var(--primary-text-color); }
  .take ha-icon { color: var(--c); --mdc-icon-size: 22px; }
  .take.due, .take.overdue { background: color-mix(in srgb, var(--c) 28%, var(--card-background-color)); }
  .toast { margin-top: 14px; height: 52px; border-radius: 14px; display: flex; align-items: center; gap: 10px; padding: 0 8px 0 16px;
    background: color-mix(in srgb, var(--green-color, #4caf50) 16%, var(--card-background-color)); font-size: 15px; font-weight: 600; }
  .toast ha-icon { color: var(--green-color, #4caf50); }
  .toast span { flex: 1; }
  .undo { all: unset; cursor: pointer; padding: 8px 14px; border-radius: 10px; font-size: 14px; font-weight: 600; background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
`;

PillBlisterCard.sheetStyles = `
  :host { position: fixed; inset: 0; z-index: 9999; display: flex; align-items: flex-end; justify-content: center; font-family: var(--ha-font-family-body, Roboto, sans-serif); }
  .bg { position: absolute; inset: 0; background: rgba(0,0,0,.5); }
  .sheet { position: relative; width: 100%; max-width: 480px; max-height: 90vh; overflow-y: auto; box-sizing: border-box;
    background: var(--card-background-color, #1c1c1e); color: var(--primary-text-color);
    border-radius: 22px 22px 0 0; padding: 10px 18px calc(18px + env(safe-area-inset-bottom)); animation: up .2s ease-out; }
  .sheet.still { animation: none; }
  @media (min-width: 600px) { :host { align-items: center; } .sheet { border-radius: 22px; } }
  @keyframes up { from { transform: translateY(24px); opacity: .6; } }
  @media (prefers-reduced-motion: reduce) { .sheet { animation: none; } }
  .grab { width: 36px; height: 4px; border-radius: 2px; margin: 0 auto 10px; background: color-mix(in srgb, var(--primary-text-color) 25%, transparent); }
  .sh-head { display: flex; align-items: center; justify-content: space-between; }
  .sh-title { font-size: 20px; font-weight: 700; }
  .sh-sub { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
  button { font: inherit; }
  .x { all: unset; cursor: pointer; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
  .status { display: flex; align-items: center; gap: 10px; margin: 16px 0 14px; padding: 12px 14px; border-radius: 14px; font-size: 15px; font-weight: 600;
    --s: var(--secondary-text-color); background: color-mix(in srgb, var(--s) 14%, transparent); }
  .status ha-icon { color: var(--s); flex: none; }
  .status.ok { --s: var(--green-color, #4caf50); }
  .status.late { --s: var(--orange-color, #ff9800); }
  .status.early { --s: var(--blue-color, #2196f3); }
  .hint, .or { font-size: 13px; color: var(--secondary-text-color); margin: 0 2px 10px; }
  .or { text-align: center; margin: 12px 0 8px; }
  .sec { font-size: 13px; font-weight: 600; color: var(--secondary-text-color); margin: 18px 2px 8px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 4px 12px; font-size: 15px; }
  .evrow { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 4px 8px; font-size: 14px; }
  input[type=time], input[type=datetime-local] { font: inherit; font-size: 16px; font-weight: 600; color: var(--primary-text-color); color-scheme: light dark;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); border: 0; border-radius: 10px; padding: 8px 12px; }
  .btns { display: flex; gap: 8px; }
  .btns.wrap { flex-wrap: wrap; }
  .btn { all: unset; box-sizing: border-box; cursor: pointer; flex: 1; min-height: 48px; padding: 0 14px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 15px; font-weight: 600; text-align: center;
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .btn.small { flex: none; min-height: 34px; font-size: 13px; padding: 0 12px; border-radius: 10px; }
  .btn.primary { background: color-mix(in srgb, var(--pink-color, #e91e63) 22%, var(--card-background-color, #1c1c1e)); }
  .btn.primary ha-icon { color: var(--pink-color, #e91e63); }
  .btn.danger { color: var(--error-color, #db4437); }
  .btn.wide { width: 100%; flex: none; }
  .err { margin-top: 12px; font-size: 13px; color: var(--error-color, #db4437); }
`;

customElements.define('pill-blister-card', PillBlisterCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'pill-blister-card', name: 'Pill Blister', description: 'Blister, Status, Hinweise und Tagebuch der Pill-Blister-Integration' });
