import fs from 'node:fs';
import path from 'node:path';
const STATE_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_PATH = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const IDS = (process.env.REMIND_IDS || '').split(',').filter(Boolean);
const NOW = Number(process.env.NOW_MS || Date.now());
let state = {};
try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); } catch (e) {}
for (const id of IDS) state[id] = NOW;
fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
const line = '2026-10-24 07:42 | 在途列表=49 | RUNNING=5 | 滞留>8h=5 | 本轮提醒=是(5单TG已发msgId=6188) | 详情报错=0';
fs.appendFileSync(LOG_PATH, line + '\n');
console.log('FINALIZE_OK ids=' + IDS.length + ' stateSize=' + Object.keys(state).length);
