'use strict';
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const ENV_FILE = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_FILE = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const ERRLOG = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan_err.log';
const SCANLOG = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const HOUR = 3600000; const OVERDUE_MS = 8 * HOUR; const SIZE = 20; const OVERLAP = 600000; const MAX_DEPTH = 10; const SLICE_CAP = 60;
const DEADLINE = Date.now() + 150000;
const NL = String.fromCharCode(10);
const errors = [];
function mask(s) { let t = String(s); const parts = t.split('access_token='); if (parts.length > 1) { t = parts[0] + 'access_token=***' + parts.slice(1).join(''); } if (t.length > 300) t = t.slice(0, 300); return t; }
function logErr(m) { errors.push(mask(m)); try { fs.appendFileSync(ERRLOG, mask(new Date().toISOString() + ' ' + m) + NL); } catch (e) {} }
function readEnv() { const txt = fs.readFileSync(ENV_FILE, 'utf8'); const out = {}; const lines = txt.split(NL); for (let raw of lines) { let line = raw.trim(); if (!line || line.charAt(0) === '#') continue; if (line.indexOf('export ') === 0) line = line.slice(7).trim(); const eq = line.indexOf('='); if (eq < 0) continue; const k = line.slice(0, eq).trim(); let v = line.slice(eq + 1).trim(); if (v.length >= 2 && ((v.charAt(0) === String.fromCharCode(34) && v.charAt(v.length - 1) === String.fromCharCode(34)) || (v.charAt(0) === String.fromCharCode(39) && v.charAt(v.length - 1) === String.fromCharCode(39)))) v = v.slice(1, -1); v = v.split(' ').join('').split(String.fromCharCode(9)).join(''); out[k] = v; } return out; }
function curlJson(url, jsonBody, isGet) { const args = ['-sS', '--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors', '--max-time', '8', '-X', isGet ? 'GET' : 'POST', '-H', 'Content-Type: application/json']; if (jsonBody) args.push('-d', JSON.stringify(jsonBody)); args.push(url); const out = cp.execFileSync('curl', args, { timeout: 45000, maxBuffer: 20971520, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }); if (!out || !out.trim()) throw new Error('empty response'); return JSON.parse(out); }
function apiCall(url, jsonBody, isGet) { let last = ''; for (let i = 0; i < 3; i++) { if (Date.now() > DEADLINE) break; try { const j = curlJson(url, jsonBody, isGet); if (j && typeof j.errcode === 'number' && j.errcode !== 0) { last = 'errcode=' + j.errcode + ' errmsg=' + (j.errmsg || ''); continue; } return { ok: true, json: j }; } catch (e) { last = mask(e && e.message ? e.message : String(e)); } } return { ok: false, error: last || 'unknown' }; }
function shNow() { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()); }
function shMinuteOfDay() { const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date()); let h = 0; let m = 0; for (const p of parts) { if (p.type === 'hour') h = Number(p.value); else if (p.type === 'minute') m = Number(p.value); } return h * 60 + m; }
function parseCreateTime(v) { if (typeof v === 'number') return v < 1e12 ? v * 1000 : v; if (typeof v !== 'string') return NaN; const s = v.trim(); if (/^[0-9]{14,}$/.test(s)) { const n = Number(s); return n < 1e12 ? n * 1000 : n; } const m = s.match(/^([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})/); if (m) { const t = Date.parse(m[1] + '-' + m[2] + '-' + m[3] + 'T' + m[4] + ':' + m[5] + ':' + m[6] + '+08:00'); if (Number.isFinite(t)) return t; } const t2 = Date.parse(s); return Number.isFinite(t2) ? t2 : NaN; }
(async () => {
  const t0 = Date.now();
  const env = readEnv();
  const ak = env.DINGTALK_APPKEY || ''; const as = env.DINGTALK_APPSECRET || '';
  if (!ak || !as) { logErr('FATAL env missing keys'); throw new Error('env credentials missing'); }
  let token = '';
  const r1 = apiCall('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: ak, appSecret: as }, false);
  if (r1.ok && r1.json && r1.json.accessToken) token = r1.json.accessToken;
  if (!token) {
    const GT = 'https://oapi.dingtalk.com/gettoken?appkey=' + encodeURIComponent(ak) + '&appsecret=' + encodeURIComponent(as);
    const r2 = apiCall(GT, null, true);
    if (r2.ok && r2.json && r2.json.access_token) token = r2.json.access_token;
    else logErr('token failed new=' + (r1.ok ? 'ok-but-empty' : r1.error) + ' oapi=' + (r2.ok ? 'ok-but-empty' : r2.error));
  }
  if (!token) throw new Error('no token');
  const LIST_URL = 'https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token;
  const GET_URL = 'https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token;
  const ids = new Set();
  let slices = 0; let sliceErr = 0; let truncated = false;
  function scanSlice(s, e, depth) {
    if (Date.now() > DEADLINE || slices >= SLICE_CAP) { truncated = true; return; }
    slices++;
    const r = apiCall(LIST_URL, { process_code: PROCESS_CODE, start_time: Math.round(s), end_time: Math.round(e), size: SIZE, next_cursor: 0 }, false);
    if (!r.ok) { sliceErr++; logErr('listids ' + new Date(s).toISOString() + '~' + new Date(e).toISOString() + ': ' + r.error); return; }
    const res = r.json.result;
    let arr = [];
    if (Array.isArray(res)) arr = res; else if (res && Array.isArray(res.result)) arr = res.result; else if (res && Array.isArray(res.list)) arr = res.list;
    for (const x of arr) { if (x) ids.add(String(typeof x === 'string' ? x : (x.processInstanceId || x.id || ''))); }
    if (arr.length >= SIZE && depth < MAX_DEPTH) { const mid = s + Math.floor((e - s) / 2); scanSlice(s, mid, depth + 1); scanSlice(mid - OVERLAP, e, depth + 1); }
  }
  let s = t0 - 7 * 24 * HOUR;
  while (s < t0) {
    const e = Math.min(s + 12 * HOUR, t0);
    scanSlice(s, e, 0);
    if (e >= t0) break;
    s = e - OVERLAP;
  }
  const inflight = []; let getErr = 0;
  for (const id of ids) {
    if (Date.now() > DEADLINE) { truncated = true; break; }
    const r = apiCall(GET_URL, { process_instance_id: id }, false);
    if (!r.ok) { getErr++; logErr('get ' + id + ': ' + r.error); continue; }
    const pi = r.json.process_instance || (r.json.result && r.json.result.process_instance) || null;
    if (!pi) { logErr('get ' + id + ': no process_instance key'); continue; }
    const status = pi.status || ''; const result = pi.result == null ? '' : String(pi.result);
    if (!(status === 'RUNNING' || result === '')) continue;
    const comps = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
    const getV = (name) => { for (const c of comps) { if (c && c.name === name && c.value != null) return String(c.value); } return ''; };
    const title = String(pi.title || '');
    let pr = (getV('采购申请编号').match(/PR[0-9]+/) || [''])[0];
    if (!pr) { for (const c of comps) { const m2 = (String(c.value || '').match(/PR[0-9]+/) || [''])[0]; if (m2) { pr = m2; break; } } }
    if (!pr) pr = (title.match(/PR[0-9]+/) || ['无编号'])[0];
    const applicant = (getV('申请人') || pi.originator_user_name || '未知').slice(0, 30);
    const ctMs = parseCreateTime(pi.create_time);
    inflight.push({ id: String(id), title: title.slice(0, 80), pr: pr, applicant: applicant, ctMs: ctMs, ctStr: typeof pi.create_time === 'string' ? pi.create_time : '' });
  }
  const nowMs = Date.now();
  const overdue = inflight.filter((x) => Number.isFinite(x.ctMs) && nowMs - x.ctMs > OVERDUE_MS);
  const quiet = (() => { const mm = shMinuteOfDay(); return mm >= 21 * 60 || mm < 7 * 60 + 30; })();
  let state = {}; let stateWasValid = false;
  try { const p = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); if (p && typeof p === 'object' && !Array.isArray(p)) { state = p; stateWasValid = true; } } catch (e) {}
  let wouldRemind = 0; const lines = [];
  if (!quiet) {
    for (const x of overdue) {
      const last = state[x.id];
      if (typeof last === 'number' && nowMs - last < OVERDUE_MS) continue;
      lines.push(x.pr + '|' + x.title + '|' + (x.ctStr || '') + '|已滞留' + ((nowMs - x.ctMs) / HOUR).toFixed(1) + 'h');
      state[x.id] = nowMs; wouldRemind++;
    }
  }
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + NL);
  let tag = quiet ? '已提醒=否(静默时段21:00-07:30)' : (wouldRemind > 0 ? '已提醒=是(' + wouldRemind + ')' : '已提醒=否');
  if (truncated) tag += ';截断';
  if (errors.length) tag += ';err=' + errors.length;
  fs.mkdirSync(path.dirname(SCANLOG), { recursive: true });
  fs.appendFileSync(SCANLOG, shNow() + ' | 在途=' + inflight.length + ' | 滞留=' + overdue.length + ' | ' + tag + NL);
  const od = overdue.map((x) => ({ pr: x.pr, title: x.title, ct: x.ctStr || '', applicant: x.applicant, hours: Number.isFinite(x.ctMs) ? Number(((nowMs - x.ctMs) / HOUR).toFixed(1)) : null }));
  console.log('RESULT_JSON=' + JSON.stringify({ ok: true, quiet: quiet, slices: slices, sliceErr: sliceErr, ids: ids.size, inflight: inflight.length, overdueCount: overdue.length, wouldRemind: wouldRemind, lines: lines, overdue: od, truncated: truncated, errCount: errors.length, getErr: getErr, tookMs: nowMs - t0, stateWasValid: stateWasValid }));
})().catch((e) => {
  try { fs.appendFileSync(SCANLOG, shNow() + ' | FATAL | ' + mask(e && e.message ? e.message : String(e)) + NL); } catch (e2) {}
  console.log('RESULT_JSON=' + JSON.stringify({ ok: false, error: mask(e && e.message ? e.message : String(e)) }));
});