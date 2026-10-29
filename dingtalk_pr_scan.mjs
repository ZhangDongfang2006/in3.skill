#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const ENV_PATH = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const RESULT_PATH = '/tmp/dt_pr_scan_result.json';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const OVERDUE_MS = 8 * 3600 * 1000;
const DEDUP_MS = 8 * 3600 * 1000;
const TOKEN_URL = 'https://api.dingtalk.com/v1.0/oauth2/accessToken';
const LIST_URL = 'https://oapi.dingtalk.com/topapi/processinstance/listids';
const GET_URL = 'https://oapi.dingtalk.com/topapi/processinstance/get';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readEnvSecrets() {
  const txt = fs.readFileSync(ENV_PATH, 'utf8');
  const map = {};
  for (const raw of txt.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if (v.length >= 2 && ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))) v = v.slice(1, -1);
    map[m[1]] = v;
  }
  return map;
}

async function httpJson(url, body) {
  let lastErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000)
      });
      const txt = await res.text();
      let j = null;
      try { j = JSON.parse(txt); } catch (e2) { throw new Error('non-json http=' + res.status); }
      return j;
    } catch (e) {
      lastErr = e;
      if (attempt < 2) await sleep(2000);
    }
  }
  throw new Error('http failed after retries: ' + String((lastErr && lastErr.message) || lastErr));
}

async function getToken() {
  const s = readEnvSecrets();
  if (!s.DINGTALK_APPKEY || !s.DINGTALK_APPSECRET) throw new Error('missing DINGTALK_APPKEY/SECRET in env file');
  const j = await httpJson(TOKEN_URL, { appKey: s.DINGTALK_APPKEY, appSecret: s.DINGTALK_APPSECRET });
  if (!j || !j.accessToken) throw new Error('token fail: ' + JSON.stringify(j).slice(0, 200));
  return j.accessToken;
}

async function listSlice(token, s, e, depth) {
  const body = { process_code: PROCESS_CODE, start_time: s, end_time: e, size: 20, next_cursor: 0 };
  const j = await httpJson(LIST_URL + '?access_token=' + token, body);
  if (!j || j.errcode !== 0) throw new Error('listids errcode=' + (j ? j.errcode : 'null') + ' errmsg=' + (j ? j.errmsg : 'null'));
  const list = (j.result && j.result.list) || [];
  if (!Array.isArray(list) || list.length === 0) return [];
  if (list.length < 20 || depth >= 10) return list;
  const mid = Math.floor((s + e) / 2);
  const ov = 10 * 60 * 1000;
  if (mid <= s || mid >= e) return list;
  const a = await listSlice(token, s, mid, depth + 1);
  const b = await listSlice(token, mid - ov, e, depth + 1);
  return list.concat(a, b);
}

async function listAll(token, nowMs) {
  const start = nowMs - 7 * 24 * 3600 * 1000;
  const sliceMs = 12 * 3600 * 1000;
  const ov = 10 * 60 * 1000;
  const all = [];
  let s = start;
  let guard = 0;
  while (guard++ < 40) {
    let e = s + sliceMs;
    if (e >= nowMs) e = nowMs;
    const sStart = (s === start) ? s : (s - ov);
    const ids = await listSlice(token, sStart, e, 0);
    for (const id of ids) all.push(id);
    if (e >= nowMs) break;
    s = e;
  }
  return Array.from(new Set(all));
}

async function getDetail(token, id) {
  const j = await httpJson(GET_URL + '?access_token=' + token, { process_instance_id: id });
  if (!j || j.errcode !== 0) throw new Error('detail errcode=' + (j ? j.errcode : 'null') + ' errmsg=' + (j ? j.errmsg : 'null') + ' id=' + id);
  return j.process_instance || (j.result && j.result.process_instance) || null;
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let i = 0;
  async function worker() {
    while (true) {
      const idx = i++;
      if (idx >= items.length) return;
      try { results[idx] = { ok: true, val: await fn(items[idx]) }; }
      catch (e) { results[idx] = { ok: false, err: String((e && e.message) || e) }; }
    }
  }
  const n = Math.max(1, Math.min(limit, items.length));
  const ws = [];
  for (let k = 0; k < n; k++) ws.push(worker());
  await Promise.all(ws);
  return results;
}

function shParts(nowMs) {
  const d = new Date(nowMs + 8 * 3600 * 1000);
  const p = (x) => String(x).padStart(2, '0');
  return {
    h: d.getUTCHours(),
    min: d.getUTCMinutes(),
    str: d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate()) + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ':' + p(d.getUTCSeconds())
  };
}

function isQuiet(nowMs) {
  const q = shParts(nowMs);
  return q.h >= 21 || q.h < 7 || (q.h === 7 && q.min < 30);
}

function parseCt(v) {
  if (typeof v === 'number') return v;
  const m = String(v || '').match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return NaN;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6])) - 8 * 3600 * 1000;
}

function extractForm(pi) {
  const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
  let prNo = '';
  let applicant = '';
  for (const f of forms) {
    const name = String((f && f.name) || '').trim();
    const val = (f && f.value == null) ? '' : String(f.value).trim();
    if (!prNo && name === '采购申请编号') prNo = val;
    if (!applicant && name === '申请人') applicant = val;
  }
  if (!prNo) {
    const m = JSON.stringify(pi).match(/PR[0-9]+/);
    if (m) prNo = m[0];
  }
  return { prNo: prNo || '-', applicant: applicant || '-' };
}

function readState() {
  try { const j = JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); return (j && typeof j === 'object' && !Array.isArray(j)) ? j : {}; } catch (e) { return {}; }
}

const mode = process.argv[2] || 'scan';

if (mode === 'scan') {
  const nowMs = Date.now();
  const token = await getToken();
  const ids = await listAll(token, nowMs);
  const details = await mapLimit(ids, 5, async (id) => getDetail(token, id));
  const inFlight = [];
  const errors = [];
  for (const d of details) {
    if (!d.ok) { errors.push(d.err); continue; }
    const pi = d.val;
    if (!pi) { errors.push('empty detail object'); continue; }
    const st = String(pi.status || '');
    const res = pi.result;
    if (st === 'RUNNING' || res === undefined || res === null || res === '') inFlight.push(pi);
  }
  if (details.length > 0 && errors.length === details.length) throw new Error('all ' + errors.length + ' detail queries failed; last: ' + errors[errors.length - 1]);
  const state = readState();
  const overdue = [];
  for (const pi of inFlight) {
    const ct = parseCt(pi.create_time);
    if (isNaN(ct)) continue;
    if (nowMs - ct > OVERDUE_MS) {
      const f = extractForm(pi);
      overdue.push({
        id: String(pi.id || ''),
        prNo: f.prNo,
        applicant: f.applicant,
        title: String(pi.title || ''),
        createTime: String(pi.create_time || ''),
        hours: Math.round(((nowMs - ct) / 3600000) * 10) / 10
      });
    }
  }
  const toRemind = overdue.filter((x) => !(state[x.id] && (nowMs - state[x.id]) < DEDUP_MS));
  const result = {
    ok: true,
    nowStr: shParts(nowMs).str,
    quiet: isQuiet(nowMs),
    idCount: ids.length,
    inFlightCount: inFlight.length,
    overdueCount: overdue.length,
    toRemindCount: toRemind.length,
    errorCount: errors.length,
    overdue: overdue,
    toRemindIds: toRemind.map((x) => x.id)
  };
  fs.mkdirSync(path.dirname(RESULT_PATH), { recursive: true });
  fs.writeFileSync(RESULT_PATH, JSON.stringify(result));
  process.stdout.write(JSON.stringify(result));
} else if (mode === 'finish') {
  const arg = JSON.parse(process.argv[3] || '{}');
  const res = JSON.parse(fs.readFileSync(RESULT_PATH, 'utf8'));
  const state = readState();
  if (arg.reminded) {
    for (const id of (res.toRemindIds || [])) state[id] = Date.now();
  }
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(state));
  const remindedTxt = arg.reminded ? '是' : (arg.quiet ? '否(静默时段)' : '否');
  const logLine = res.nowStr + ' | 在途 ' + res.inFlightCount + ' | 滞留 ' + res.overdueCount + ' | 已提醒=' + remindedTxt;
  fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
  fs.appendFileSync(LOG_PATH, logLine + '\n');
  process.stdout.write(JSON.stringify({ ok: true, logLine: logLine }));
}
