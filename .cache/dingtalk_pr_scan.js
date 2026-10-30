#!/usr/bin/env node
'use strict';
const spawnSync = require('child_process').spawnSync;
const fs = require('fs');
const path = require('path');
const WS = '/Users/zhangdongfang/.openclaw/workspace-in3bot';
const SECRETS = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE = WS + '/IN3数据/dingtalk_pr_overdue_state.json';
const LOG = WS + '/memory/dingtalk_scan.log';
const LAST = '/tmp/dingtalk_pr_scan_last.json';
const PC = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const OAPI = 'https://oapi.dingtalk.com';
const SLICE = 12 * 3600 * 1000;
const OV = 10 * 60 * 1000;
const WINDOW = 7 * 24 * 3600 * 1000;
const OVERDUE_H = 8;
const DEDUP_MS = 8 * 3600 * 1000;
let TOKEN = '';
const errors = [];
function fatal(kind, detail) {
  console.log(JSON.stringify({ ok: false, fatal: kind, detail: String(detail).slice(0, 300) }));
  process.exit(3);
}
function curlJson(url, bodyObj, tag) {
  const errFile = '/tmp/dingtalk_pr_scan_' + tag + '.err.log';
  for (let attempt = 0; attempt < 3; attempt++) {
    const fd = fs.openSync(errFile, 'a');
    const r = spawnSync('curl', ['-sS', '--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors', '--max-time', '20', '-X', 'POST', url, '-H', 'Content-Type: application/json', '-d', JSON.stringify(bodyObj)], { stdio: ['ignore', 'pipe', fd], timeout: 30000, encoding: 'utf8' });
    try { fs.closeSync(fd); } catch (e) {}
    if (r.error) { errors.push({ api: tag, curlError: String(r.error.message || r.error) }); continue; }
    let j;
    try { j = JSON.parse(r.stdout); } catch (e) { errors.push({ api: tag, parseError: String(e).slice(0, 120) }); continue; }
    return j;
  }
  return null;
}
function getToken() {
  let envText = '';
  try { envText = fs.readFileSync(SECRETS, 'utf8'); } catch (e) { fatal('secrets_read', e); }
  const env = {};
  envText.split(/\r?\n/).forEach(function (line) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  });
  if (!env.DINGTALK_APPKEY || !env.DINGTALK_APPSECRET) fatal('secrets_missing', 'APPKEY/APPSECRET not found in env file');
  const j = curlJson('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET }, 'token');
  const tk = j && (j.accessToken || (j.result && j.result.accessToken));
  if (!tk) fatal('token', JSON.stringify({ errcode: j && j.errcode, code: j && j.code, errmsg: j && (j.errmsg || j.message) }));
  TOKEN = tk;
}
function listSlice(s, e, depth) {
  if (s >= e || depth > 10) return [];
  const body = { process_code: PC, start_time: s, end_time: e, size: 20, next_cursor: 0 };
  const j = curlJson(OAPI + '/topapi/processinstance/listids?access_token=' + TOKEN, body, 'list');
  if (!j || j.errcode !== 0) { errors.push({ api: 'listids', errcode: j ? j.errcode : 'curlfail', errmsg: j ? j.errmsg : undefined }); return []; }
  const res = j.result || {};
  const arr = res.list || res.result || res.data || [];
  const ids = arr.map(function (x) { return typeof x === 'string' ? x : (x && (x.process_instance_id || x.processInstanceId)); }).filter(Boolean);
  if (ids.length < 20 || depth >= 10) return ids;
  const mid = Math.floor((s + e) / 2);
  const seen = {};
  ids.forEach(function (i) { seen[i] = 1; });
  listSlice(s, mid, depth + 1).concat(listSlice(mid - OV, e, depth + 1)).forEach(function (i) { if (!seen[i]) { seen[i] = 1; ids.push(i); } });
  return ids;
}
function parseCt(v) {
  if (v == null || v === '') return NaN;
  const s = String(v).trim();
  if (/^\d+$/.test(s)) { const n = Number(s); return n > 1e12 ? n : n * 1000; }
  const t = s.replace(' ', 'T');
  let ms = new Date(t + '+08:00').getTime();
  if (isNaN(ms)) ms = new Date(t).getTime();
  return ms;
}
function loadState() {
  let s;
  try { s = JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (e) { return {}; }
  if (!s || typeof s !== 'object' || Array.isArray(s)) return {};
  const clean = {};
  Object.keys(s).forEach(function (k) { if (k && k !== 'undefined' && typeof s[k] === 'number' && isFinite(s[k])) clean[k] = s[k]; });
  return clean;
}
function scan() {
  try {
    getToken();
    const now = Date.now();
    const end = now;
    const start = now - WINDOW;
    const idSet = {};
    const order = [];
    let t = start;
    let slices = 0;
    while (t < end) {
      const s = t;
      const e = Math.min(t + SLICE, end);
      slices++;
      listSlice(s, e, 0).forEach(function (id) { if (id && !idSet[id]) { idSet[id] = 1; order.push(id); } });
      if (e >= end) break;
      t += (SLICE - OV);
    }
    const inFlight = [];
    let apiErr = 0;
    order.forEach(function (id) {
      const j = curlJson(OAPI + '/topapi/processinstance/get?access_token=' + TOKEN, { process_instance_id: id }, 'get');
      if (!j || j.errcode !== 0) { apiErr++; errors.push({ api: 'get', id: id, errcode: j ? j.errcode : 'curlfail', errmsg: j ? j.errmsg : undefined }); return; }
      const pi = (j.result && j.result.process_instance) || j.process_instance || (j.result || {});
      const status = String(pi.status || '');
      const result = pi.result == null ? '' : String(pi.result);
      if (status.toUpperCase() === 'RUNNING' || result === '') {
        const createMs = parseCt(pi.create_time);
        const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
        function getV(name) { const f = forms.find(function (x) { return x && x.name === name; }); return f && f.value != null ? String(f.value) : ''; }
        let pr = getV('采购申请编号');
        const m1 = pr.match(/PR[0-9]+/i);
        if (m1) pr = m1[0].toUpperCase();
        else {
          let all = String(pi.title || '');
          try { all += ' ' + JSON.stringify(forms); } catch (e2) {}
          const m2 = all.match(/PR[0-9]+/i);
          pr = m2 ? m2[0].toUpperCase() : (pr || '未知PR');
        }
        inFlight.push({ id: id, pr: pr, title: String(pi.title || ''), applicant: getV('申请人'), createTime: String(pi.create_time || ''), createMs: createMs, hours: isNaN(createMs) ? -1 : (now - createMs) / 3600000 });
      }
    });
    const state = loadState();
    const overdueAll = inFlight.filter(function (x) { return x.hours > OVERDUE_H; });
    const candidates = overdueAll.filter(function (x) {
      const last = state[x.id];
      return !(typeof last === 'number' && (now - last) < DEDUP_MS);
    }).sort(function (a, b) { return a.createMs - b.createMs; });
    try { fs.writeFileSync(LAST, JSON.stringify({ inFlightIds: inFlight.map(function (x) { return x.id; }), candidates: candidates, stats: { totalIds: order.length, inFlight: inFlight.length, overdueAll: overdueAll.length, apiErrors: apiErr } })); } catch (e3) {}
    console.log(JSON.stringify({ ok: true, mode: 'scan', nowMs: now, slices: slices, totalIds: order.length, inFlight: inFlight.length, overdueAll: overdueAll.length, candidates: candidates.length, apiErrors: apiErr, errors: errors.slice(0, 20) }));
  } catch (ex) {
    fatal('exception', ex && (ex.stack || ex.message || ex));
  }
}
function finalize(argv) {
  function get(f, d) { const i = argv.indexOf(f); return i >= 0 && argv[i + 1] != null ? argv[i + 1] : d; }
  const remindedArg = get('--reminded', 'none');
  const inflight = parseInt(get('--inflight', '0'), 10) || 0;
  const overdue = parseInt(get('--overdue', '0'), 10) || 0;
  const quiet = get('--quiet', '0') === '1';
  const reminded = remindedArg === 'none' ? [] : remindedArg.split(',').filter(Boolean);
  const now = Date.now();
  let next = loadState();
  let keep = null;
  try { keep = new Set(JSON.parse(fs.readFileSync(LAST, 'utf8')).inFlightIds); } catch (e) {}
  if (keep) { const filtered = {}; Object.keys(next).forEach(function (k) { if (keep.has(k)) filtered[k] = next[k]; }); next = filtered; }
  reminded.forEach(function (id) { next[id] = now; });
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  fs.writeFileSync(STATE, JSON.stringify(next));
  const d = new Date(now + 8 * 3600 * 1000);
  const ts = d.toISOString().replace('T', ' ').slice(0, 19);
  let line = ts + ' | 在途 ' + inflight + ' | 滞留 ' + overdue + ' | 已提醒:' + (reminded.length ? '是' : (quiet ? '否(静默)' : '否'));
  if (quiet) line += ' | 静默时段';
  fs.mkdirSync(path.dirname(LOG), { recursive: true });
  fs.appendFileSync(LOG, line + '\n');
  console.log(JSON.stringify({ ok: true, mode: 'finalize', stateKeys: Object.keys(next).length, logLine: line }));
}
const mode = process.argv[2];
if (mode === 'scan') scan();
else if (mode === 'finalize') finalize(process.argv.slice(2));
else { console.log(JSON.stringify({ ok: false, fatal: 'bad_mode', detail: String(mode) })); process.exit(2); }
