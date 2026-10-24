import fs from 'node:fs';
import path from 'node:path';

const ENV_PATH = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const OVERDUE_MS = 8 * 3600 * 1000;

function parseEnv(txt) {
  const out = {};
  for (const line of String(txt || '').split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const m = t.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}
function fmtTime(ms) {
  const d = new Date(ms + 8 * 3600 * 1000);
  return d.toISOString().slice(0, 16).replace('T', ' ');
}
function parseCreateTime(v) {
  if (v === null || v === undefined) return 0;
  if (typeof v === 'number') return v;
  const s = String(v).trim();
  if (/^\d{13}$/.test(s)) return Number(s);
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) - 8 * 3600 * 1000;
  return 0;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function postJson(url, body, label) {
  let last = null;
  for (let i = 0; i < 3; i++) {
    try {
      const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await resp.json();
      if (!j || j.errcode === undefined || j.errcode === 0) return j;
      last = j;
    } catch (e) {
      last = { errcode: -1, errmsg: String((e && e.message) || e) };
    }
    if (i < 2) await sleep(400 * (i + 1));
  }
  throw new Error(label + '_err errcode=' + (last && last.errcode) + ' errmsg=' + ((last && (last.errmsg || last.message)) || ''));
}

let APPKEY = process.env.DINGTALK_APPKEY || '';
let APPSECRET = process.env.DINGTALK_APPSECRET || '';
try {
  const ev = parseEnv(fs.readFileSync(ENV_PATH, 'utf8'));
  APPKEY = APPKEY || ev.DINGTALK_APPKEY || '';
  APPSECRET = APPSECRET || ev.DINGTALK_APPSECRET || '';
} catch (e) {}
if (!APPKEY || !APPSECRET) { console.log('RESULT ' + JSON.stringify({ ok: false, reason: 'missing_credentials' })); process.exit(3); }

const nowMs = Date.now();
let token = '';
try {
  const tr = await postJson('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: APPKEY, appSecret: APPSECRET }, 'token');
  token = (tr && tr.accessToken) || '';
} catch (e) { console.log('RESULT ' + JSON.stringify({ ok: false, reason: 'token', msg: String(e.message || e).slice(0, 150) })); process.exit(3); }
if (!token) { console.log('RESULT ' + JSON.stringify({ ok: false, reason: 'token_empty' })); process.exit(3); }

const startMs = nowMs - 7 * 24 * 3600 * 1000;
const ids = [];
let cursor = 0, pages = 0, listErr = '';
while (pages < 100) {
  let j;
  try {
    j = await postJson('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token, { process_code: PROCESS_CODE, start_time: startMs, size: 20, cursor: cursor }, 'listids');
  } catch (e) { listErr = String(e.message || e).slice(0, 150); break; }
  const res = (j && j.result) || {};
  const list = res.list || res.data || [];
  for (const x of list) ids.push(typeof x === 'string' ? x : ((x && x.processInstanceId) || ''));
  pages++;
  if (res.next_cursor) cursor = res.next_cursor; else break;
}

const GET_URL = 'https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token;
async function getDetail(id) {
  try {
    const j = await postJson(GET_URL, { process_instance_id: id }, 'get');
    const r = (j && (j.process_instance || j.result)) || null;
    if (r) return { id, r, err: '' };
    return { id, r: null, err: 'empty errcode=' + ((j && j.errcode) ?? '?') };
  } catch (e) {
    return { id, r: null, err: String(e.message || e).slice(0, 100) };
  }
}

const details = [];
for (let i = 0; i < ids.length; i += 6) {
  const rs = await Promise.all(ids.slice(i, i + 6).map(getDetail));
  for (const x of rs) details.push(x);
}

function extractPr(form) {
  const m = JSON.stringify(form || '').match(/PR[0-9]+/);
  return m ? m[0] : '';
}
function extractApplicant(form) {
  for (const it of form || []) {
    const n = String((it && it.name) || '');
    if (n.indexOf('申请人') >= 0 || n.indexOf('发起人') >= 0) {
      let v = it ? it.value : '';
      if (v === null || v === undefined) continue;
      v = String(v);
      try {
        const arr = JSON.parse(v);
        if (Array.isArray(arr)) {
          const t = arr.map((x) => (x && (x.text || x.value || x.name)) || '').filter(Boolean).join(',');
          if (t) return t.slice(0, 30);
        }
      } catch (e) {}
      return v.slice(0, 30);
    }
  }
  return '';
}

const running = [];
let detailErr = 0;
const errNotes = [];
for (const d of details) {
  if (!d.r) { detailErr++; if (errNotes.length < 4) errNotes.push(d.id + ':' + d.err); continue; }
  const status = String(d.r.status || '');
  const finishTime = d.r.finish_time;
  const isOpen = status === 'RUNNING' || (!status && !finishTime);
  if (!isOpen) continue;
  const created = parseCreateTime(d.r.create_time);
  running.push({
    id: d.id, title: String(d.r.title || '').slice(0, 60),
    pr: extractPr(d.r.form_component_values || d.r.form),
    applicant: extractApplicant(d.r.form_component_values || d.r.form),
    createTime: created, createStr: created ? fmtTime(created) : '',
    status: status,
    ageH: created ? Math.round(((nowMs - created) / 3600000) * 10) / 10 : -1
  });
}
running.sort((a, b) => a.createTime - b.createTime);
const overdue = running.filter((x) => x.createTime > 0 && nowMs - x.createTime > OVERDUE_MS);

let state = {};
try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); } catch (e) {}
const dueRemind = overdue.filter((x) => !(state[x.id] && nowMs - state[x.id] < OVERDUE_MS));

const hm = fmtTime(nowMs).slice(11, 16);
const quiet = hm >= '21:00' || hm < '07:30';
const willRemind = dueRemind.length > 0 && !quiet;

if (!willRemind) {
  for (const x of dueRemind) state[x.id] = nowMs;
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
  const line = fmtTime(nowMs) + ' | 在途列表=' + ids.length + ' | RUNNING=' + running.length + ' | 滞留>8h=' + overdue.length + ' | 本轮提醒=否(静默=' + quiet + ') | 详情报错=' + detailErr + (listErr ? ' | 列表报错:' + listErr : '');
  fs.appendFileSync(LOG_PATH, line + '\n');
}

const payload = { ok: true, now: fmtTime(nowMs), listCount: ids.length, pages, listErr, detailErr, errNotes, runningCount: running.length, running, overdueCount: overdue.length, dueRemindCount: dueRemind.length, dueRemind, quiet, willRemind };
console.log('RESULT ' + JSON.stringify(payload));
