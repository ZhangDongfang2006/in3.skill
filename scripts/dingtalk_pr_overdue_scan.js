'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const WS = '/Users/zhangdongfang/.openclaw/workspace-in3bot';
const ENVF = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATEF = WS + '/IN3数据/dingtalk_pr_overdue_state.json';
const LOGF = WS + '/memory/dingtalk_scan.log';
const ERRLOG = WS + '/memory/dingtalk_scan_err.log';
const PC = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const SH = 8 * 3600 * 1000;
const NOWMS = Date.now();

function out(o) { console.log(JSON.stringify(o)); }
function fail(msg) { out({ ok: false, error: String(msg).slice(0, 300) }); process.exit(0); }
function p2(n) { return (n < 10 ? '0' : '') + n; }
function fmtSH(ms) { const d = new Date(ms + SH); return d.getUTCFullYear() + '-' + p2(d.getUTCMonth() + 1) + '-' + p2(d.getUTCDate()) + ' ' + p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()); }
function parseCT(v) { if (v === undefined || v === null) return NaN; if (typeof v === 'number') return v > 1e12 ? v : v * 1000; const s = String(v); const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/); if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 8, +m[5], +m[6]); const n = Number(s); if (isFinite(n) && n > 1e12) return n; return NaN; }
function fmtCT(v) { const ms = parseCT(v); return isFinite(ms) ? fmtSH(ms) : String(v === undefined || v === null ? '' : v); }

let creds = {};
try {
  const txt = fs.readFileSync(ENVF, 'utf8');
  txt.split(/\r?\n/).forEach(function (line) {
    const m = line.match(/^\s*(?:export\s+)?(DINGTALK_APPKEY|DINGTALK_APPSECRET)\s*=\s*(.*?)\s*$/);
    if (m) creds[m[1]] = m[2].replace(/^["']|["']$/g, '');
  });
} catch (e) { fail('env_read_failed: ' + e.message); }
if (!creds.DINGTALK_APPKEY || !creds.DINGTALK_APPSECRET) fail('env_missing_keys');

function curlJson(method, url, body) {
  const args = ['-sS', '--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors', '-X', method, url];
  if (body) { args.push('-H', 'Content-Type: application/json'); args.push('--data', JSON.stringify(body)); }
  let o;
  try {
    o = execFileSync('curl', args, { encoding: 'utf8', timeout: 60000, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) {
    throw new Error('curl_rc=' + e.status + ' stderr=' + String(e.stderr || '').replace(/\s+/g, ' ').slice(0, 200));
  }
  try { return JSON.parse(o); } catch (e) { throw new Error('bad_json head=' + o.slice(0, 150)); }
}
function api(method, url, body) {
  let last = null;
  for (let i = 0; i < 3; i++) {
    try {
      const r = curlJson(method, url, body);
      if (r && typeof r.errcode === 'number' && r.errcode !== 0) { last = new Error('errcode=' + r.errcode + ' errmsg=' + (r.errmsg || '')); continue; }
      return r;
    } catch (e) { last = e; }
  }
  throw last;
}

let token = '';
try {
  const t = curlJson('POST', 'https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: creds.DINGTALK_APPKEY, appSecret: creds.DINGTALK_APPSECRET });
  token = t.accessToken || '';
  if (!token) fail('token_failed code=' + String(t.code || '') + ' message=' + String(t.message || '').slice(0, 150));
} catch (e) { fail('token_request_failed (details suppressed)'); }

const START = NOWMS - 7 * 24 * 3600 * 1000;
const OVERLAP = 10 * 60 * 1000;
const SIZE = 20;
const rawIds = [];
const listErrors = [];
let sliceCount = 0, depthHit = false;
function scanSlice(s, e, depth) {
  if (depth > 10) { depthHit = true; return; }
  sliceCount++;
  let r = null;
  try {
    r = api('POST', 'https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token, { process_code: PC, start_time: s, end_time: e, size: SIZE, next_cursor: 0 });
  } catch (err) { listErrors.push('slice@' + s + ': ' + err.message); return; }
  const list = (r.result && r.result.list) || [];
  for (let i = 0; i < list.length; i++) rawIds.push(list[i]);
  if (list.length >= SIZE) {
    const mid = Math.floor((s + e) / 2);
    scanSlice(s, mid, depth + 1);
    scanSlice(mid - OVERLAP, e, depth + 1);
  }
}
scanSlice(START, NOWMS, 0);
const ids = Array.from(new Set(rawIds));

const unfinished = [];
const detailErrors = [];
for (let i = 0; i < ids.length; i++) {
  const pid = ids[i];
  let r = null;
  try {
    r = api('POST', 'https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token, { process_instance_id: pid });
  } catch (err) { detailErrors.push(String(pid).slice(0, 10) + ': ' + err.message); continue; }
  const pi = (r && r.process_instance) || {};
  const status = String(pi.status || '');
  const result = (pi.result === undefined || pi.result === null) ? '' : String(pi.result);
  if (status === 'RUNNING' || result === '') {
    unfinished.push({ pid: pid, title: String(pi.title || ''), ctMs: parseCT(pi.create_time), ctRaw: fmtCT(pi.create_time), forms: pi.form_component_values || [] });
  }
}

const overdueAll = [];
for (let i = 0; i < unfinished.length; i++) {
  const u = unfinished[i];
  u.hours = isFinite(u.ctMs) ? (NOWMS - u.ctMs) / 3600000 : NaN;
  if (u.hours > 8) overdueAll.push(u);
}
overdueAll.sort(function (a, b) { return a.ctMs - b.ctMs; });

function extractPr(u) {
  let val = '';
  for (let i = 0; i < u.forms.length; i++) { const f = u.forms[i]; if (f && f.name === '采购申请编号') { val = String(f.value || '').trim(); break; } }
  let m = val.match(/PR[0-9]+/); if (m) return m[0];
  if (val) return val;
  m = u.title.match(/PR[0-9]+/); if (m) return m[0];
  for (let i = 0; i < u.forms.length; i++) { const f = u.forms[i]; const mm = String((f && f.value) || '').match(/PR[0-9]+/); if (mm) return mm[0]; }
  return 'PR?';
}
function extractApplicant(u) {
  for (let i = 0; i < u.forms.length; i++) { const f = u.forms[i]; if (f && f.name === '申请人') { const v = String(f.value || '').trim(); if (v) return v; } }
  return '';
}

const nowSH = new Date(NOWMS + SH);
const hh = nowSH.getUTCHours(), mi = nowSH.getUTCMinutes();
const quiet = (hh >= 21) || (hh < 7) || (hh === 7 && mi < 30);

let state = {};
try { const sTxt = fs.readFileSync(STATEF, 'utf8'); const parsed = JSON.parse(sTxt); if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) state = parsed; } catch (e) {}
const toRemind = [];
for (let i = 0; i < overdueAll.length; i++) {
  const u = overdueAll[i];
  const last = Number(state[u.pid] || 0);
  if (NOWMS - last >= 8 * 3600 * 1000) toRemind.push(u);
}
const reminded = (!quiet) && toRemind.length > 0;
if (reminded) { for (let i = 0; i < toRemind.length; i++) state[toRemind[i].pid] = NOWMS; }
const kept = {};
for (const k of Object.keys(state)) { if (NOWMS - Number(state[k]) < 14 * 24 * 3600 * 1000) kept[k] = state[k]; }
try { fs.mkdirSync(STATEF.substring(0, STATEF.lastIndexOf('/')), { recursive: true }); fs.writeFileSync(STATEF, JSON.stringify(kept, null, 2)); } catch (e) {}

const lines = [];
const applicants = [];
for (let i = 0; i < toRemind.length; i++) {
  const u = toRemind[i];
  const hrs = Math.round(u.hours * 10) / 10;
  applicants.push(extractApplicant(u));
  lines.push(extractPr(u) + '｜' + u.title + '｜' + u.ctRaw + '｜已滞留' + hrs + 'h');
}

let logLine = fmtSH(NOWMS) + ' | in-flight=' + unfinished.length + ' | overdue=' + overdueAll.length + ' | reminded=' + (reminded ? 'yes' : 'no');
try { fs.mkdirSync(LOGF.substring(0, LOGF.lastIndexOf('/')), { recursive: true }); fs.appendFileSync(LOGF, logLine + '\n'); } catch (e) { logLine = 'log_write_failed: ' + e.message; }
if (listErrors.length > 0 || detailErrors.length > 0 || depthHit) {
  try { fs.appendFileSync(ERRLOG, fmtSH(NOWMS) + ' | depthHit=' + depthHit + ' | ' + JSON.stringify({ listErrors: listErrors.slice(0, 10), detailErrors: detailErrors.slice(0, 20) }) + '\n'); } catch (e) {}
}

out({ ok: true, quiet: quiet, sliceCount: sliceCount, listed: ids.length, rawListed: rawIds.length, inFlight: unfinished.length, overdue: overdueAll.length, toRemindCount: toRemind.length, reminded: reminded, lines: lines, applicants: applicants, listErrorCount: listErrors.length, detailErrorCount: detailErrors.length, depthHit: depthHit, logLine: logLine });
