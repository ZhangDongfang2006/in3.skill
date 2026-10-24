// 钉钉采购申请滞留扫描核心脚本（无状态：只扫描并输出 JSON，提醒/去重/日志由 cron 的 Code Mode 处理）
// 用法: Code Mode 内 await exec({ command: 'node dingtalk_pr_overdue_scan.cjs' })，从输出中取 '###JSON###' 后的 JSON
// 输出字段: scanTime/totalIds/pages/listErr/errors[]/running[]{id,createTimeMs,createTimeRaw,title,pr,applicant}
// ⚠️ 关键经验(2026-10-24 验证): processinstance/get 返回 {errcode,errmsg,process_instance:{...}}，
//   状态在 process_instance.status('RUNNING'/...)、结果在 process_instance.result，
//   create_time 是字符串 'YYYY-MM-DD HH:mm:ss'（Asia/Shanghai），
//   表单在 form_component_values（不是 form/createTime/result 顶层字段，用错会得到空对象误判 0 滞留）。
//   listids 每页 size 上限 20，用 cursor 翻页。
const fs = require('fs');
const ENV_PATH = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const PROCESS_CODE = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const env = {};
for (const line of fs.readFileSync(ENV_PATH, 'utf8').split(/\r?\n/)) {
  const m = line.match(/^\s*(DINGTALK_APPKEY|DINGTALK_APPSECRET)\s*=\s*["']?([^"'\s]+)["']?\s*$/);
  if (m) env[m[1]] = m[2];
}
async function postJson(url, body) {
  let lastErr = '';
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      const rc = j && j.errcode;
      if (rc === 0 || rc === undefined || rc === null) return j;
      lastErr = 'errcode=' + rc + ' errmsg=' + (j.errmsg || '');
      if ([130101, 90018, -1].indexOf(rc) === -1) return j;
    } catch (e) { lastErr = String(e && e.message || e); }
    await new Promise(res => setTimeout(res, 400 * (i + 1)));
  }
  return { errcode: 'RETRY_EXHAUSTED', errmsg: lastErr };
}
const ctToMs = s => { const t = Date.parse(String(s).replace(' ', 'T') + '+08:00'); return isNaN(t) ? NaN : t; };
(async () => {
  const out = { scanTime: Date.now(), totalIds: 0, pages: 0, listErr: '', errors: [], running: [] };
  const tok = await postJson('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET });
  if (!tok || !tok.accessToken) { out.listErr = 'token失败:' + JSON.stringify(tok).slice(0, 200); console.log('###JSON###' + JSON.stringify(out)); return; }
  const startTime = out.scanTime - 7 * 24 * 3600 * 1000;
  let cursor = 0;
  const ids = [];
  for (;;) {
    out.pages++;
    const r = await postJson('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + tok.accessToken, { process_code: PROCESS_CODE, start_time: startTime, size: 20, cursor });
    if (r.errcode !== 0) { out.listErr = JSON.stringify(r).slice(0, 250); break; }
    const res = r.result || {};
    ids.push.apply(ids, res.list || []);
    if (res.next_cursor === undefined || res.next_cursor === null) break;
    cursor = res.next_cursor;
    if (out.pages >= 20) break;
  }
  out.totalIds = ids.length;
  for (let i = 0; i < ids.length; i += 12) {
    const chunk = ids.slice(i, i + 12);
    const rs = await Promise.all(chunk.map(id => postJson('https://oapi.dingtalk.com/topapi/processinstance/get?access_token=' + tok.accessToken, { process_instance_id: id })));
    chunk.forEach((id, k) => {
      const j = rs[k];
      if (!j || j.errcode !== 0) { out.errors.push({ id: String(id).slice(-8), err: JSON.stringify(j || {}).slice(0, 150) }); return; }
      const inst = j.process_instance || {};
      if (inst.status !== 'RUNNING') return;
      const forms = inst.form_component_values || [];
      const formText = forms.map(f => (f.name || '') + ':' + (f.value || '')).join('\n');
      const prM = formText.match(/PR[0-9]+/) || String(inst.title || '').match(/PR[0-9]+/);
      let applicant = '';
      for (const f of forms) {
        if (/申请人|提交人/.test(f.name || '')) {
          const v = String(f.value || "");
          const tm = v.match(/"text"\s*:\s*"([^"]+)"/);
          applicant = tm ? tm[1] : v.slice(0, 20);
          break;
        }
      }
      if (!applicant && inst.originator_userid) applicant = inst.originator_userid;
      out.running.push({ id, createTimeMs: ctToMs(inst.create_time), createTimeRaw: inst.create_time, title: inst.title || "", pr: prM ? prM[0] : "", applicant });
    });
  }
  out.running.sort((a, b) => a.createTimeMs - b.createTimeMs);
  console.log('###JSON###' + JSON.stringify(out));
})().catch(e => console.log('###JSON###' + JSON.stringify({ scanTime: Date.now(), fatal: String(e && e.stack || e).slice(0, 400) })));