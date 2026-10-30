import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const T0 = Date.now();
const ENVF = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const SUM_F = '/Users/zhangdongfang/.openclaw/workspace-in3bot/.tmp/ding_pr_scan_summary.json';
const STATE_F = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const HOUR = 3600000;
const errors = [];
function warn(o) { if (errors.length < 20) errors.push(o); }
function curlJson(url, bodyObj) {
  for (let i = 0; i < 3; i++) {
    try {
      const raw = execFileSync('curl', ['--silent','--show-error','--tlsv1.2','--retry','3','--retry-delay','2','--retry-all-errors','--max-time','25','-X','POST', url, '-H','Content-Type: application/json','--data', JSON.stringify(bodyObj)], { encoding: 'utf8', timeout: 35000 });
      try { return JSON.parse(raw); } catch (e) { warn({ op: 'json_parse', api: url.split('?')[0], raw: String(raw).slice(0, 160) }); }
    } catch (e) { warn({ op: 'curl_exec', api: url.split('?')[0], err: String(e && e.message ? e.message : e).slice(0, 160) }); }
  }
  return { __failed: true };
}
function finish(sum) { try { writeFileSync(SUM_F, JSON.stringify(sum)); } catch (e) {} console.log(JSON.stringify(sum)); process.exit(sum && sum.error ? 3 : 0); }

const env = {};
try {
  for (const line of readFileSync(ENVF, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (m) { let v = m[2].trim(); if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1); env[m[1]] = v; }
  }
} catch (e) { warn({ op: 'read_env', err: String(e && e.message ? e.message : e).slice(0, 120) }); }
if (!env.DINGTALK_APPKEY || !env.DINGTALK_APPSECRET) finish({ error: 'missing_credentials', errors: errors });

const tok = curlJson('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET });
const TOKEN = tok && tok.accessToken;
if (!TOKEN) finish({ error: 'token_failed', errcode: tok && tok.errcode, errmsg: tok && tok.errmsg, code: tok && tok.code, message: tok && tok.message, errors: errors });

const idSet = new Set();
const OVERLAP = 600000, SLICE = 12 * HOUR;
const nowMs = Date.now();
const start0 = nowMs - 7 * 24 * HOUR;
let timeGuard = false;
function listSlice(s, e, depth) {
  if (Date.now() - T0 > 150000) { if (!timeGuard) { timeGuard = true; warn({ op: 'time_guard_list' }); } return; }
  if (depth > 10) { warn({ op: 'bisect_depth_exceeded' }); return; }
  const resp = curlJson('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + TOKEN, { process_code: PROCESS_CODE, start_time: s, end_time: e, size: 20, next_cursor: 0 });
  if (!resp || resp.__failed || resp.errcode !== 0) { warn({ op: 'listids', start: s, end: e, errcode: resp && resp.errcode, errmsg: resp && resp.errmsg }); return; }
  const r = resp.result || {};
  const list = Array.isArray(r.list) ? r.list : (r.data && Array.isArray(r.data.result) ? r.data.result : []);
  for (const x of list) { const id = typeof x === 'string' ? x : (x && (x.process_instance_id || x.processInstanceId || x.id)) || ''; if (id) idSet.add(String(id)); }
  if (list.length >= 20) { const mid = Math.floor((s + e) / 2); listSlice(s, mid, depth + 1); listSlice(mid - OVERLAP, e, depth + 1); }
}
let cur = start0;
while (cur < nowMs) {
  const e = Math.min(cur + SLICE, nowMs);
  listSlice(cur, e < nowMs ? e + OVERLAP : e, 0);
  cur = e;
}

const inFlight = [];
for (const id of idSet) {
  if (Date.now() - T0 > 210000) { warn({ op: 'time_guard_detail' }); break; }
  const resp = curlJson('https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + TOKEN, { process_instance_id: id });
  if (!resp || resp.__failed || resp.errcode !== 0) { warn({ op: 'get', id: String(id).slice(0, 8), errcode: resp && resp.errcode, errmsg: resp && resp.errmsg }); continue; }
  const pi = resp.process_instance || (resp.result && resp.result.process_instance);
  if (!pi) { warn({ op: 'get_shape', id: String(id).slice(0, 8) }); continue; }
  if (!(pi.status === 'RUNNING' || !pi.result)) continue;
  const ct = String(pi.create_time || '').trim();
  let createMs = NaN;
  if (/^\d{13}$/.test(ct)) createMs = Number(ct);
  else if (ct) { const d = new Date(ct.replace(' ', 'T') + '+08:00'); if (!isNaN(d.getTime())) createMs = d.getTime(); }
  const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
  const formVal = (name) => { const c = forms.find(f => f && f.name === name); return c ? String(c.value == null ? '' : c.value).trim() : ''; };
  let pr = formVal('采购申请编号');
  if (!/^PR\d+$/i.test(pr)) { const m = (pr + ' ' + String(pi.title || '')).match(/PR[0-9]+/i); pr = m ? m[0].toUpperCase() : pr; }
  inFlight.push({ id: String(id), title: String(pi.title || ''), createTime: ct, createMs: createMs, pr: pr, applicant: formVal('申请人') });
}
const overdue = inFlight.filter(d => Number.isFinite(d.createMs) && nowMs - d.createMs > 8 * HOUR).sort((a, b) => a.createMs - b.createMs);
const shD = new Date(nowMs + 8 * HOUR);
const shMin = shD.getUTCHours() * 60 + shD.getUTCMinutes();
const quiet = shMin >= 1260 || shMin < 450;
let state = {};
try { if (existsSync(STATE_F)) state = JSON.parse(readFileSync(STATE_F, 'utf8')) || {}; } catch (e) { state = {}; }
const toRemind = quiet ? [] : overdue.filter(d => !(typeof state[d.id] === 'number' && nowMs - state[d.id] < 8 * HOUR));
const lines = toRemind.map(d => (d.pr || '(无编号)') + '｜' + (d.title || '(无标题)') + '｜' + d.createTime + '｜已滞留' + Math.max(0, Math.floor((nowMs - d.createMs) / HOUR)) + 'h');
finish({ scannedAtMs: nowMs, instanceCount: idSet.size, inFlight: inFlight.length, overdueCount: overdue.length, quiet: quiet, toRemindIds: toRemind.map(d => d.id), remindText: lines.length ? '【采购申请滞留催办】' + '\n' + lines.join('\n') + '\n钉钉评论催办待权限开通后切换' : null, errors: errors });