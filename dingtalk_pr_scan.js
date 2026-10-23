'use strict';
const fs = require('fs');
const ENV = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const PC = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const now = Date.now();
const start = now - 604800000;
const env = {};
for (const line of fs.readFileSync(ENV, 'utf8').split('\n')) {
  const t = line.trim();
  if (!t || t.charAt(0) === '#') continue;
  const eq = t.indexOf('=');
  if (eq < 1) continue;
  let k = t.slice(0, eq).trim();
  if (k.slice(0, 7) === 'export ') k = k.slice(7).trim();
  let v = t.slice(eq + 1).trim();
  const q = String.fromCharCode(39);
  const dq = String.fromCharCode(34);
  if (v.length > 1) {
    const c0 = v.charAt(0);
    const cN = v.charAt(v.length - 1);
    if ((c0 === q && cN === q) || (c0 === dq && cN === dq)) v = v.slice(1, -1);
  }
  env[k] = v;
}
if (!env.DINGTALK_APPKEY || !env.DINGTALK_APPSECRET) { console.error('FATAL env keys missing'); process.exit(1); }
let state = {};
try { state = JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (e) { state = {}; }
const mode = process.argv[2] || 'scan';
const commitIds = (process.argv[3] || '').split(',').filter(Boolean);
function post(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
}
function parseCt(s) {
  if (!s) return NaN;
  if (/^[0-9]+$/.test(String(s))) return Number(s);
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/);
  if (!m) return NaN;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6])) - 28800000;
}
async function retry(fn, label) {
  let lastErr = null;
  for (let a = 0; a < 3; a++) {
    try { return await fn(); } catch (e) { lastErr = e; }
  }
  throw new Error(label + ' failed: ' + (lastErr ? lastErr.message : 'unknown'));
}
(async function main() {
  if (mode === 'commit') {
    for (const id of commitIds) state[id] = now;
    for (const k of Object.keys(state)) { if (now - Number(state[k]) > 691200000) delete state[k]; }
    fs.writeFileSync(STATE, JSON.stringify(state));
    console.log('===RESULT===');
    console.log(JSON.stringify({ ok: true, committed: commitIds.length }));
    return;
  }
  const tr = await retry(function () { return post('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET }); }, 'token');
  const token = tr && tr.accessToken;
  if (!token) { console.error('FATAL token failed: ' + JSON.stringify(tr).slice(0, 200)); process.exit(1); }
  const ids = [];
  let cursor = 0;
  for (;;) {
    const r = await retry(function () { return post('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + token, { process_code: PC, start_time: start, cursor: cursor, size: 20 }); }, 'listids');
    if (r.errcode !== 0) { console.error('FATAL listids errcode=' + r.errcode + ' errmsg=' + r.errmsg); process.exit(1); }
    if (r.result && r.result.list) for (const x of r.result.list) ids.push(x);
    const nc = r.result && r.result.next_cursor;
    if (!nc) break;
    cursor = nc;
  }
  const running = [];
  const apiErrors = [];
  for (let i = 0; i < ids.length; i += 8) {
    const chunk = ids.slice(i, i + 8);
    const rs = await Promise.all(chunk.map(async function (id) {
      let lastE = null;
      for (let a = 0; a < 3; a++) {
        try {
          const r = await post('https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + token, { process_instance_id: id });
          if (r.errcode !== 0) return { id: id, errcode: r.errcode, errmsg: r.errmsg };
          return { id: id, res: r.process_instance || r.result || {} };
        } catch (e) { lastE = e; }
      }
      return { id: id, errcode: -1, errmsg: lastE ? lastE.message : 'unknown' };
    }));
    for (const x of rs) {
      if (x.errcode !== undefined && x.errcode !== 0) { apiErrors.push({ id: x.id, errcode: x.errcode, errmsg: x.errmsg }); continue; }
      const res = x.res || {};
      const status = String(res.status || '');
      const resultEmpty = !(res.result && String(res.result).trim());
      const isRunning = (status === 'RUNNING') || (!status && resultEmpty);
      if (!isRunning) continue;
      const title = res.title || '';
      let prNo = '';
      let applicant = '';
      try {
        const fcv = res.form_component_values || res.form || [];
        let hay = '';
        try { hay = JSON.stringify(fcv); } catch (e2) { hay = ''; }
        const mm = hay.match(/PR[0-9]{6,}/);
        if (mm) prNo = mm[0];
        if (!prNo) { const t2 = title.match(/PR[0-9]{6,}/); if (t2) prNo = t2[0]; }
        for (const f of fcv) {
          const nm = String((f && f.name) || '');
          const vs = String((f && f.value) || '');
          if (vs && (nm.indexOf('申请人') >= 0 || nm.indexOf('提交人') >= 0)) { applicant = vs.replace(/<[^>]*>/g, '').slice(0, 24); break; }
        }
        if (!applicant) { const am = title.match(/^(.+?)提交的/); if (am) applicant = am[1]; }
      } catch (e2) {}
      running.push({ id: x.id, title: title, createTime: res.create_time, prNo: prNo, applicant: applicant });
    }
  }
  const overdue = running.filter(function (o) { const ct = parseCt(o.createTime); return isFinite(ct) && (now - ct > 28800000); }).sort(function (a, b) { return parseCt(a.createTime) - parseCt(b.createTime); });
  const shStr = new Date(now).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' });
  const hhmm = shStr.slice(11, 16);
  const quiet = (hhmm >= '21:00') || (hhmm < '07:30');
  const toRemind = quiet ? [] : overdue.filter(function (o) { return now - Number(state[o.id] || 0) >= 28800000; });
  function mapO(o) { const ct = parseCt(o.createTime); return { id: o.id, prNo: o.prNo, title: o.title, createTime: o.createTime, applicant: o.applicant, hours: Math.floor((now - ct) / 3600000) }; }
  console.log('===RESULT===');
  console.log(JSON.stringify({ scanned: ids.length, inFlight: running.length, overdue: overdue.length, quiet: quiet, apiErrors: apiErrors, overdueAll: overdue.map(mapO), toRemind: toRemind.map(mapO) }));
})().catch(function (e) { console.error('FATAL ' + e.message); process.exit(1); });