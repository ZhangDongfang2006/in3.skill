#!/usr/bin/env node
'use strict';
const fs = require('fs');
const { spawnSync } = require('child_process');
const SECRETS = '/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const PC = 'PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const env = {};
fs.readFileSync(SECRETS, 'utf8').split(/\r?\n/).forEach(function (l) {
  const m = l.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$/);
  if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
});
function curl(url, body) {
  const r = spawnSync('curl', ['-sS', '--tlsv1.2', '--max-time', '20', '-X', 'POST', url, '-H', 'Content-Type: application/json', '-d', JSON.stringify(body)], { encoding: 'utf8', timeout: 30000 });
  return r.stdout;
}
const tok = JSON.parse(curl('https://api.dingtalk.com/v1.0/oauth2/accessToken', { appKey: env.DINGTALK_APPKEY, appSecret: env.DINGTALK_APPSECRET }));
const T = tok.accessToken;
const now = Date.now();
const out = { tokenOk: !!T };
const nowCn = new Date(now + 8 * 3600e3).toISOString().replace('T', ' ').slice(0, 16);
out.nowCn = nowCn;
// probe 1: last 12h window
const r1 = JSON.parse(curl('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + T, { process_code: PC, start_time: now - 12 * 3600e3, end_time: now, size: 20, next_cursor: 0 }));
out.probe1_full = JSON.stringify(r1).slice(0, 1500);
// probe 2: wider window 30 days, dump shape
const r2 = JSON.parse(curl('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token=' + T, { process_code: PC, start_time: now - 30 * 24 * 3600e3, end_time: now, size: 20, next_cursor: 0 }));
const res2 = r2.result || {};
const keys = Object.keys(res2);
out.probe2_keys = keys;
const arr2 = res2.result || res2.list || res2.data || [];
out.probe2_count = Array.isArray(arr2) ? arr2.length : String(typeof arr2);
out.probe2_sample = Array.isArray(arr2) ? JSON.stringify(arr2.slice(0, 3)) : '';
out.probe2_nextCursor = res2.next_cursor;
console.log(JSON.stringify(out));

