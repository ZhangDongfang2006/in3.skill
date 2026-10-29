import fs from 'fs';
import { spawnSync } from 'child_process';
import path from 'path';

const WS = '/Users/zhangdongfang/.openclaw/workspace-in3bot';
const TMP = WS + '/.tmp';
const ERRF = TMP + '/pr_scan_err.log';
const STATEF = WS + '/IN3数据/dingtalk_pr_overdue_state.json';
const LOGF = WS + '/memory/dingtalk_scan.log';
const ENVF = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const HOUR8 = 8 * 3600 * 1000;
const OVERDUE_MS = HOUR8;
const REMIND_GAP_MS = HOUR8;
const SIZE = 20, SLICE = 12 * 3600 * 1000, OVERLAP = 10 * 60 * 1000, MAXDEPTH = 10;

function logErr(s) { try { fs.appendFileSync(ERRF, new Date().toISOString() + ' ' + s + '\n'); } catch (e) {} }
function shNow() { return new Date(Date.now() + HOUR8).toISOString().replace('T', ' ').slice(0, 19); }
function curlOnce(url, body) {
  const r = spawnSync('curl', ['--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors', '-s', '-S', '--connect-timeout', '10', '--max-time', '25', '-X', 'POST', '-H', 'Content-Type: application/json', '--data', JSON.stringify(body || {}), url], { timeout: 30000, stdio: ['ignore', 'pipe', fs.openSync(ERRF, 'a')] });
  if (r.error) throw new Error('curl_spawn:' + r.error.message);
  if (r.status !== 0) throw new Error('curl_exit:' + r.status);
  const o = (r.stdout || '').toString('utf8').trim();
  if (!o) throw new Error('curl_empty_body');
  return JSON.parse(o);
}
function api(url, body, tag) {
  let last = null;
  for (let i = 0; i <= 2; i++) {
    try {
      const j = curlOnce(url, body);
      if (j && typeof j.errcode === 'number' && j.errcode !== 0) throw new Error('errcode=' + j.errcode + ' errmsg=' + String(j.errmsg || '').slice(0, 150));
      return j;
    } catch (e) { last = e; logErr(tag + ' attempt' + (i + 1) + ': ' + String((e && e.message) || e).slice(0, 220)); }
  }
  throw last;
}
function readEnv() {
  const t = fs.readFileSync(ENVF, 'utf8');
  const m = {};
  const re = /^\s*(?:export\s+)?(DINGTALK_APPKEY|DINGTALK_APPSECRET)\s*=\s*(.+?)\s*$/;
  for (const line of t.split(/\r?\n/)) { const mm = re.exec(line); if (mm) m[mm[1]] = mm[2].replace(/^["']|["']$/g, ''); }
  if (!m.DINGTALK_APPKEY || !m.DINGTALK_APPSECRET) throw new Error('env_missing_keys');
  return m;
}
function parseCt(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(String(s || ''));
  if (!m) return NaN;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) - HOUR8;
}
function extractPi(g) {
  if (!g || typeof g !== 'object') return null;
  if (g.process_instance && typeof g.process_instance === 'object') return g.process_instance;
  if (g.result && typeof g.result === 'object' && !Array.isArray(g.result)) {
    if (g.result.process_instance && typeof g.result.process_instance === 'object') return g.result.process_instance;
    return g.result;
  }
  return null;
}
function scan() {
  const t0 = Date.now();
  const env = readEnv();
  const tok = api('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET }, 'token');
  const accessToken = tok.accessToken || (tok.result && tok.result.accessToken);
  if (!accessToken) throw new Error('no_access_token');
  const now = Date.now();
  const START = now - 7 * 24 * 3600 * 1000, END = now;
  const seen = new Set(); const ids = [];
  function listRange(s, e, depth) {
    const j = api('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + encodeURIComponent(accessToken), { process_code: PROCESS_CODE, start_time: s, end_time: e, size: SIZE, next_cursor: 0 }, 'listids');
    const res = j && j.result;
    let list = (res && (Array.isArray(res.list) ? res.list : Array.isArray(res.result) ? res.result : [])) || [];
    list = list.map(x => (x && typeof x === 'object') ? (x.processInstanceId || x.process_instance_id || x.id) : x).filter(Boolean);
    for (const id of list) if (!seen.has(id)) { seen.add(id); ids.push(id); }
    if (list.length >= SIZE && depth < MAXDEPTH) {
      const mid = Math.floor((s + e) / 2);
      if (mid > s && mid < e) { listRange(s, mid, depth + 1); listRange(mid - OVERLAP, e, depth + 1); }
    }
  }
  let cur = START;
  while (cur < END) {
    const e = Math.min(cur + SLICE, END);
    listRange(cur, e, 0);
    if (e >= END) break;
    cur = e - OVERLAP;
  }
  let apiErrGet = 0, unknownShape = 0; const inFlight = [];
  for (const id of ids) {
    let pi = null;
    try {
      const g = api('https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + encodeURIComponent(accessToken), { process_instance_id: id }, 'get');
      pi = extractPi(g);
    } catch (e) { apiErrGet++; continue; }
    if (!pi) { unknownShape++; logErr('shape_unknown id=' + id); continue; }
    const status = pi.status;
    const isRunning = status === 'RUNNING' || (status == null && (pi.result == null || pi.result === ''));
    if (!isRunning) continue;
    const createMs = parseCt(pi.create_time);
    const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
    const findV = (n) => { const c = forms.find(f => f && f.name === n); return c && c.value != null ? String(c.value) : ''; };
    let pr = findV('采购申请编号').match(/PR[0-9]+/i);
    if (!pr) { for (const f of forms) { const v = f && f.value != null ? String(f.value) : ''; const m2 = v.match(/PR[0-9]+/i); if (m2) { pr = m2; break; } } }
    if (!pr) pr = String(pi.title || '').match(/PR[0-9]+/i);
    const applicant = findV('申请人').replace(/[\[\]"\\]/g, '').trim();
    inFlight.push({ id: id, pr: pr ? pr[0].toUpperCase() : '无编号', title: String(pi.title || ''), createTime: String(pi.create_time || ''), createMs: createMs, applicant: applicant, hours: isFinite(createMs) ? Math.round((now - createMs) / 360000) / 10 : null });
  }
  const overdue = inFlight.filter(x => isFinite(x.createMs) && now - x.createMs > OVERDUE_MS);
  const sh = new Date(now + HOUR8);
  const mins = sh.getUTCHours() * 60 + sh.getUTCMinutes();
  const quiet = mins >= 21 * 60 || mins < 7 * 60 + 30;
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATEF, 'utf8')) || {}; } catch (e) { state = {}; }
  const toRemind = quiet ? [] : overdue.filter(o => !(state[o.id] && now - Number(state[o.id]) < REMIND_GAP_MS));
  const skippedDup = overdue.length - toRemind.length;
  return { ok: true, mode: 'scan', scanAt: shNow(), totalIds: ids.length, inFlightCount: inFlight.length, overdueCount: overdue.length, quietHours: quiet, apiErrGet: apiErrGet, unknownShape: unknownShape, skippedDup: skippedDup, toRemind: toRemind, overdueList: overdue, state: state, elapsedMs: Date.now() - t0 };
}
function finalize() {
  const fin = JSON.parse(process.env.FIN || '{}');
  const now = Date.now();
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATEF, 'utf8')) || {}; } catch (e) { state = {}; }
  const ids = fin.remindedIds || [];
  if (fin.sendOk) for (const id of ids) state[id] = now;
  fs.mkdirSync(path.dirname(STATEF), { recursive: true });
  fs.writeFileSync(STATEF, JSON.stringify(state));
  const remindNote = fin.sendOk ? ('是(' + ids.length + '单)') : ('否(' + (fin.note || '未提醒') + ')');
  const line = shNow() + ' | 在途 ' + fin.inFlight + ' | 滞留 ' + fin.overdueCount + ' | 提醒 ' + remindNote + ' | IDs=' + fin.totalIds + ' API错=' + (fin.apiErrGet || 0);
  fs.appendFileSync(LOGF, line + '\n');
  return { ok: true, mode: 'finalize', line: line, stateUpdated: fin.sendOk ? ids.length : 0 };
}
const mode = process.argv[2] || 'scan';
let out;
try { out = mode === 'finalize' ? finalize() : scan(); }
catch (e) { logErr('FATAL ' + String((e && e.stack) || e).slice(0, 800)); out = { ok: false, error: String((e && e.message) || e) }; }
try { fs.writeFileSync(TMP + '/pr_scan_out.json', JSON.stringify(out)); } catch (e) {}
console.log(JSON.stringify(out));
