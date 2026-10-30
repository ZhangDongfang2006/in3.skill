import { readFileSync, writeFileSync, appendFileSync, mkdirSync } from 'node:fs';
const SUM_F = '/Users/zhangdongfang/.openclaw/workspace-in3bot/.tmp/ding_pr_scan_summary.json';
const STATE_F = '/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const LOG_F = '/Users/zhangdongfang/.openclaw/workspace-in3bot/memory/dingtalk_scan.log';
const sum = JSON.parse(readFileSync(SUM_F, 'utf8'));
const reminded = process.argv[2] === 'yes';
const now = Date.now();
let state = {};
try { state = JSON.parse(readFileSync(STATE_F, 'utf8')) || {}; } catch (e) { state = {}; }
if (reminded) { for (const id of (sum.toRemindIds || [])) state[id] = now; }
try { mkdirSync('/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据', { recursive: true }); mkdirSync('/Users/zhangdongfang/.openclaw/workspace-in3bot/memory', { recursive: true }); } catch (e) {}
writeFileSync(STATE_F, JSON.stringify(state));
const ts = new Date(now + 8 * 3600000).toISOString().replace('T', ' ').slice(0, 19);
const flag = reminded ? '是' : (sum.quiet ? '否(静默时段)' : '否');
appendFileSync(LOG_F, ts + ' | 在途=' + (sum.inFlight || 0) + ' | 滞留=' + (sum.overdueCount || 0) + ' | 已提醒=' + flag + '\n');
console.log('committed flag=' + flag + ' stateIds=' + Object.keys(state).length);