'use strict';
// DingTalk PR overdue scan (IN3Bot cron). stdout = final JSON. Never prints secrets.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const NL = String.fromCharCode(10);
const ENV_PATH = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const RESULT_PATH = '/tmp/dt_pr_scan_result.json';
const ERR_DIR = '/tmp/dt_pr_scan_err';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const OVERDUE_MS = 8 * 3600 * 1000;
const SLICE_MS = 12 * 3600 * 1000;
const OVERLAP_MS = 10 * 60 * 1000;
const WINDOW_MS = 7 * 24 * 3600 * 1000;
const MAX_DEPTH = 10;
const DEADLINE = Date.now() + 220 * 1000;

fs.mkdirSync(ERR_DIR, { recursive: true });
function log() {
  const a = Array.prototype.slice.call(arguments);
  console.error(new Date().toISOString(), a.join(' '));
}
function readEnv(p) {
  const res = {};
  const txt = fs.readFileSync(p, 'utf8');
  for (const line of txt.split(NL)) {
    const t = line.trim();
    if (!t || t.charAt(0) === '#') continue;
    const i = t.indexOf('=');
    if (i < 0) continue;
    let v = t.slice(i + 1).trim();
    const q = String.fromCharCode(39);
    if (v.length > 1 && ((v.charAt(0) === '"' && v.charAt(v.length - 1) === '"') || (v.charAt(0) === q && v.charAt(v.length - 1) === q))) v = v.slice(1, -1);
    res[t.slice(0, i).trim()] = v;
  }
  return res;
}
let errSeq = 0;
function curlJson(url, bodyJson) {
  const errFile = ERR_DIR + '/e' + Date.now() + '_' + (errSeq++) + '.log';
  let fd = 'ignore';
  try { fd = fs.openSync(errFile, 'a'); } catch (e) {}
  try {
    const stdout = execFileSync('curl', [
      '-sS', '--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors',
      '--max-time', '25', '-X', 'POST', url,
      '-H', 'Content-Type: application/json', '--data', bodyJson
    ], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 120000, stdio: ['ignore', 'pipe', fd] });
    try { return { ok: true, json: JSON.parse(stdout) }; }
    catch (e) { return { ok: false, kind: 'non_json', raw: String(stdout).slice(0, 200) }; }
  } catch (e) {
    let d = '';
    try { d = fs.readFileSync(errFile, 'utf8').slice(-300); } catch (e2) {}
    return { ok: false, kind: 'curl_failed', detail: d };
  } finally {
    try { if (typeof fd === 'number') fs.closeSync(fd); } catch (e) {}
  }
}
// Success = any JSON object WITHOUT an explicit non-zero numeric errcode.
// Covers old oapi (errcode:0) and new api.dingtalk.com v1.0 (no errcode, e.g. accessToken).
async function apiWithRetry(url, bodyJson, tag) {
  let last = { errcode: -3, errmsg: 'unknown' };
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (Date.now() > DEADLINE) return { errcode: -9, errmsg: 'deadline', __failed: true };
    const r = curlJson(url, bodyJson);
    if (r.ok && r.json && typeof r.json === 'object' && !Array.isArray(r.json)) {
      const j = r.json;
      if (typeof j.errcode === 'number' && j.errcode !== 0) {
        last = { errcode: j.errcode, errmsg: j.errmsg };
        log('API err', tag, 'attempt', attempt, 'errcode=' + j.errcode, 'errmsg=' + j.errmsg);
      } else {
        return j;
      }
    } else if (r.ok) {
      last = { errcode: -1, errmsg: 'bad_shape:' + JSON.stringify(r.json).slice(0, 120) };
      log('API bad shape', tag, 'attempt', attempt);
    } else {
      last = { errcode: -2, errmsg: r.kind + ':' + (r.detail || r.raw || '') };
      log('curl fail', tag, 'attempt', attempt, r.kind);
    }
    if (attempt < 3) await new Promise(function (res) { setTimeout(res, 2000); });
  }
  last.__failed = true;
  return last;
}
async function getToken() {
  const env = readEnv(ENV_PATH);
  const key = env.DINGTALK_APPKEY;
  const secret = env.DINGTALK_APPSECRET;
  if (!key || !secret) throw new Error('env missing DINGTALK_APPKEY/DINGTALK_APPSECRET');
  const j = await apiWithRetry('https://api.dingtalk.com/v1.0/oauth2/accessToken', JSON.stringify({ appKey: key, appSecret: secret }), 'token');
  if (!j || j.__failed || !j.accessToken) throw new Error('TOKEN_FAIL errcode=' + (j ? j.errcode : '?') + ' ' + (j ? j.errmsg : ''));
  return j.accessToken;
}
function pad(n) { return (n < 10 ? '0' : '') + n; }
function shParts(ms) {
  const d = new Date(ms + 8 * 3600 * 1000);
  return {
    date: d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()),
    time: pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds()),
    hours: d.getUTCHours(), minutes: d.getUTCMinutes()
  };
}
function parseShanghai(v) {
  if (typeof v === 'number') return v;
  if (typeof v === 'string') {
    const m = /^([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})[ T]([0-9]{1,2}):([0-9]{1,2})(:([0-9]{1,2}))?$/.exec(v.trim());
    if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[7] || 0)) - 8 * 3600 * 1000;
    const n = Number(v);
    if (Number.isFinite(n) && n > 1e11) return n;
  }
  return NaN;
}
async function listAll(token, outp) {
  const now = Date.now();
  const end0 = now;
  const start0 = now - WINDOW_MS;
  const ids = new Set();
  async function querySlice(s, e, depth) {
    if (Date.now() > DEADLINE) { outp.incomplete = true; log('deadline during list'); return; }
    const url = 'https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token;
    const body = JSON.stringify({ process_code: PROCESS_CODE, start_time: s, end_time: e, size: 20, next_cursor: 0 });
    const j = await apiWithRetry(url, body, 'listids d' + depth);
    if (!j || j.__failed || (typeof j.errcode === 'number' && j.errcode !== 0)) {
      outp.errors.push({ slice: [s, e], errcode: j ? j.errcode : '?', errmsg: j ? j.errmsg : 'no resp' });
      outp.incomplete = true;
      return;
    }
    const list = (j.result && Array.isArray(j.result.list)) ? j.result.list : [];
    for (const id of list) ids.add(String(id));
    log('slice d' + depth, s, e, 'got', list.length);
    if (list.length >= 20) {
      if (depth >= MAX_DEPTH) { outp.incomplete = true; log('max depth', s, e); return; }
      const mid = Math.floor((s + e) / 2);
      await querySlice(s, mid, depth + 1);
      await querySlice(mid - OVERLAP_MS, e, depth + 1);
    }
  }
  let s = start0;
  while (s < end0) {
    const e = Math.min(s + SLICE_MS + OVERLAP_MS, end0);
    await querySlice(s, e, 0);
    s += SLICE_MS;
  }
  return Array.from(ids);
}
async function fetchDetails(token, ids, outp) {
  const inFlight = [];
  let okCount = 0;
  for (const id of ids) {
    if (Date.now() > DEADLINE) { outp.errors.push({ id: id, errcode: 'DEADLINE', errmsg: 'aborted' }); outp.incomplete = true; break; }
    const url = 'https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token;
    const j = await apiWithRetry(url, JSON.stringify({ process_instance_id: id }), 'get');
    if (!j || j.__failed || (typeof j.errcode === 'number' && j.errcode !== 0)) { outp.errors.push({ id: id, errcode: j ? j.errcode : '?', errmsg: j ? j.errmsg : 'no resp' }); continue; }
    const pi = j.process_instance;
    if (!pi || typeof pi !== 'object') { outp.errors.push({ id: id, errcode: 'NO_PI', errmsg: 'process_instance missing at top level' }); continue; }
    okCount++;
    const resultEmpty = pi.result === null || pi.result === undefined || pi.result === '';
    if (!(pi.status === 'RUNNING' || resultEmpty)) continue;
    const ctMs = parseShanghai(pi.create_time);
    const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
    let prRaw = '';
    for (const f of forms) { if (f && f.name === '采购申请编号' && f.value) { prRaw = String(f.value).trim(); break; } }
    let pr = '';
    const m1 = /PR[0-9]+/.exec(prRaw);
    if (m1) pr = m1[0]; else if (prRaw) pr = prRaw;
    if (!pr && pi.title) { const m = /PR[0-9]+/.exec(String(pi.title)); if (m) pr = m[0]; }
    if (!pr) { for (const f of forms) { if (f && f.value) { const m = /PR[0-9]+/.exec(String(f.value)); if (m) { pr = m[0]; break; } } } }
    let applicant = '';
    for (const f of forms) { if (f && f.name === '申请人' && f.value) { applicant = String(f.value).trim(); break; } }
    let createStr;
    if (Number.isNaN(ctMs)) createStr = String(pi.create_time);
    else { const sp = shParts(ctMs); createStr = sp.date + ' ' + sp.time; }
    inFlight.push({ id: id, title: pi.title || '', createMs: ctMs, createStr: createStr, pr: pr, applicant: applicant });
  }
  outp.detailOk = okCount;
  return inFlight;
}
async function scan() {
  const o = { scannedAt: null, inFlightCount: 0, overdueCount: 0, due: [], errors: [], incomplete: false, quietHours: false, fatal: null, detailOk: 0 };
  try {
    const token = await getToken();
    const ids = await listAll(token, o);
    log('unique ids:', ids.length);
    const inFlight = await fetchDetails(token, ids, o);
    o.inFlightCount = inFlight.length;
    const now = Date.now();
    const overdue = inFlight.filter(function (x) { return !Number.isNaN(x.createMs) && (now - x.createMs) > OVERDUE_MS; });
    let state = {};
    try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); } catch (e) {}
    if (typeof state !== 'object' || state === null || Array.isArray(state)) state = {};
    for (const x of overdue) {
      const last = state[x.id] || 0;
      if (now - last >= OVERDUE_MS) {
        o.due.push({ id: x.id, pr: x.pr || '(无编号)', title: x.title, create_time: x.createStr, applicant: x.applicant, hoursOverdue: Math.floor((now - x.createMs) / 3600000) });
      }
    }
    o.overdueCount = overdue.length;
  } catch (e) {
    o.fatal = String((e && e.message) || e);
  }
  const sp = shParts(Date.now());
  o.scannedAt = sp.date + ' ' + sp.time;
  o.quietHours = sp.hours >= 21 || sp.hours < 7 || (sp.hours === 7 && sp.minutes < 30);
  fs.writeFileSync(RESULT_PATH, JSON.stringify(o, null, 2));
  console.log(JSON.stringify(o));
}
const mode = process.argv[2] || 'scan';
if (mode === 'finalize') {
  // kept for compatibility; main flow now finalizes directly
  console.log(JSON.stringify({ ok: true }));
} else await scan();
