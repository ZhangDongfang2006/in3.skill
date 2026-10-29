import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execFileP = promisify(execFile);
const TMP_DIR = '/Users/zhangdongfang/.openclaw/workspace-in3bot/.tmp';
const ENV_FILE = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_FILE = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_FILE = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const ERR_FILE = TMP_DIR + '/dingtalk_scan_err.log';
const RESULT_FILE = TMP_DIR + '/dt_pr_scan_result.json';
const COMMIT_FILE = TMP_DIR + '/dt_pr_commit.json';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const OVERDUE_MS = 8 * 3600 * 1000, SLICE_MS = 12 * 3600 * 1000, OVERLAP_MS = 10 * 60 * 1000, SIZE = 20, MAX_DEPTH = 10, WINDOW_MS = 7 * 24 * 3600 * 1000;
const errors = [];
function readEnv(p) {
  const out = {};
  const txt = fs.readFileSync(p, 'utf8');
  for (const raw of txt.split(/\r?\n/)) {
    const m = raw.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m) continue;
    let v = m[2];
    if (v.length >= 2 && ((v[0] === '"' && v.endsWith('"')) || (v[0] === "'" && v.endsWith("'")))) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}
async function curlJson(url, body, tag) {
  const args = ['-sS', '--tlsv1.2', '--retry', '3', '--retry-delay', '2', '--retry-all-errors', '-X', 'POST', url, '-H', 'Content-Type: application/json', '--data', JSON.stringify(body)];
  let last = '';
  for (let a = 0; a < 3; a++) {
    try {
      const { stdout } = await execFileP('curl', args, { encoding: 'utf8', timeout: 30000, maxBuffer: 8 * 1024 * 1024 });
      let j = null;
      try { j = JSON.parse(stdout); } catch (e2) { last = 'non-json: ' + String(stdout).slice(0, 120); }
      if (j) {
        if (j.errcode === undefined || j.errcode === 0) return j;
        last = 'errcode=' + j.errcode + ' errmsg=' + (j.errmsg || '');
      }
    } catch (e) { last = 'curl: ' + String(e.message || e).slice(0, 200); }
    try { fs.appendFileSync(ERR_FILE, new Date().toISOString() + ' ' + tag + ' try' + a + ': ' + last + '\n'); } catch (e3) {}
    if (a < 2) await new Promise(r => setTimeout(r, 700));
  }
  errors.push(tag + ': ' + last);
  return null;
}
function parseCt(raw) {
  if (raw == null) return NaN;
  if (typeof raw === 'number') return raw;
  const s = String(raw).trim();
  if (/^\d{13}$/.test(s)) return Number(s);
  if (/^\d{10}$/.test(s)) return Number(s) * 1000;
  return Date.parse(s.replace(' ', 'T') + (s.length === 19 ? '+08:00' : ''));
}
function field(forms, name) {
  for (const f of forms) { if (f && f.name === name) return String(f.value == null ? '' : f.value).trim(); }
  return '';
}
function cleanVal(v) {
  if (v.startsWith('[') || v.startsWith('"')) { try { const a = JSON.parse(v); if (Array.isArray(a) && a.length) return String(typeof a[0] === 'object' && a[0] && a[0].name ? a[0].name : a[0]); if (typeof a === 'string') return a; } catch (e) {} }
  return v;
}
async function main() {
  const mode = process.argv[2] || 'scan';
  if (mode === 'commit') {
    const p = JSON.parse(fs.readFileSync(COMMIT_FILE, 'utf8'));
    fs.mkdirSync(path.dirname(p.statePath), { recursive: true });
    fs.writeFileSync(p.statePath, JSON.stringify(p.state, null, 2));
    fs.mkdirSync(path.dirname(p.logPath), { recursive: true });
    fs.appendFileSync(p.logPath, p.logLine + '\n');
    console.log('COMMIT_OK');
    return;
  }
  fs.mkdirSync(TMP_DIR, { recursive: true });
  const t0 = Date.now();
  const env = readEnv(ENV_FILE);
  if (!env.DINGTALK_APPKEY || !env.DINGTALK_APPSECRET) throw new Error('missing DINGTALK_APPKEY/APPSECRET in env file');
  const tok = await curlJson('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET }, 'token');
  if (!tok || !tok.accessToken) throw new Error('token fail: ' + (tok && (tok.code || tok.message) ? 'code=' + tok.code + ' msg=' + tok.message + ' | ' : '') + errors.join(' | '));
  const token = tok.accessToken;
  const ids = new Set();
  const end0 = Date.now(), start0 = end0 - WINDOW_MS;
  async function slice(s, e, d) {
    if (d > MAX_DEPTH) { errors.push('slice depth>10 @' + s); return; }
    const j = await curlJson('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token, { process_code: PROCESS_CODE, start_time: s, end_time: e, size: SIZE, next_cursor: 0 }, 'listids');
    if (!j) return;
    const list = (j.result && (j.result.list || j.result.data)) || [];
    for (const id of list) ids.add(String(id));
    if (list.length < SIZE) return;
    const mid = Math.floor((s + e) / 2);
    await slice(s, mid, d + 1);
    await slice(mid - OVERLAP_MS, e, d + 1);
  }
  for (let s = start0; s < end0; s += SLICE_MS) { await slice(s, Math.min(s + SLICE_MS + OVERLAP_MS, end0), 0); }
  const arr = Array.from(ids);
  let idx = 0;
  const inflight = [];
  async function worker() {
    while (idx < arr.length) {
      const id = arr[idx++];
      const j = await curlJson('https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token, { process_instance_id: id }, 'get:' + id.slice(-6));
      if (!j) continue;
      const pi = j.process_instance || (j.result && j.result.process_instance) || null;
      if (!pi) { errors.push('get ' + id + ': no process_instance key; topKeys=' + Object.keys(j).join(',')); continue; }
      const status = pi.status == null ? '' : String(pi.status);
      const res = pi.result == null ? '' : String(pi.result);
      if (status === 'RUNNING' || res === '') inflight.push({ id: id, pi: pi });
    }
  }
  await Promise.all([worker(), worker(), worker(), worker(), worker()]);
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')) || {}; } catch (e) {}
  const nowMs = Date.now();
  const hm = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(nowMs));
  const quiet = (hm >= '21:00' || hm < '07:30');
  const overdue = [];
  const toRemind = [];
  for (const it of inflight) {
    const pi = it.pi;
    const ct = parseCt(pi.create_time);
    if (!isFinite(ct)) { errors.push('get ' + it.id + ': bad create_time=' + JSON.stringify(pi.create_time)); continue; }
    const ageMs = nowMs - ct;
    if (ageMs <= OVERDUE_MS) continue;
    const forms = Array.isArray(pi.form_component_values) ? pi.form_component_values : [];
    let pr = cleanVal(field(forms, '采购申请编号'));
    if (pr && !/^PR[0-9]+$/.test(pr)) { const m = pr.match(/PR[0-9]+/); pr = m ? m[0] : ''; }
    const applicant = cleanVal(field(forms, '申请人'));
    const title = String(pi.title || '');
    if (!pr) { const m = (title + ' ' + JSON.stringify(forms)).match(/PR[0-9]+/); pr = m ? m[0] : ''; }
    const o = { id: it.id, pr: pr || '(编号缺失)', title: title || '(无标题)', createTime: String(pi.create_time == null ? '' : pi.create_time), hours: Math.floor(ageMs / 3600000), applicant: applicant || '(申请人缺失)' };
    overdue.push(o);
    const last = state[it.id];
    if (!last || nowMs - Number(last) >= OVERDUE_MS) toRemind.push(o);
  }
  overdue.sort(function (a, b) { return a.createTime < b.createTime ? -1 : 1; });
  const result = { quiet: quiet, inFlightCount: inflight.length, overdueCount: overdue.length, toRemindCount: toRemind.length, toRemind: toRemind, overdue: overdue, state: state, errors: errors, elapsedMs: Date.now() - t0, ts: nowMs, hm: hm };
  fs.writeFileSync(RESULT_FILE, JSON.stringify(result, null, 2));
  console.log('SCAN_OK inflight=' + inflight.length + ' overdue=' + overdue.length + ' toRemind=' + toRemind.length + ' quiet=' + quiet + ' errs=' + errors.length + ' ms=' + (Date.now() - t0));
}
main().catch(function (e) {
  console.error('FATAL: ' + (e && e.message || e));
  try { fs.mkdirSync(TMP_DIR, { recursive: true }); fs.writeFileSync(RESULT_FILE, JSON.stringify({ fatal: String(e && e.message || e), errors: errors }, null, 2)); } catch (e2) {}
  process.exit(1);
});