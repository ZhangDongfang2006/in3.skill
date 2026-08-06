# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20260806-001] correction

**Logged**: 2026-08-06T10:00:00+08:00
**Priority**: high
**Status**: resolved
**Area**: config

### Summary
IN3 采购订单路由变更：`/purchase/po/list` 已 404，新路由 `/spm/purchase-order/list`

### Details
测试每日采购价格分析导出流程时，发现直接 navigate 到 `/purchase/po/list` 返回 404 页面。IN3 已改版路由。正确导航方式：先在首页菜单点击「采购管理」，然后在右侧 `.menu-groups-container` 中点击「采购订单管理」(`.third-menu-item`)，页面跳转到 `/spm/purchase-order/list`。

### Suggested Action
更新 cron prompt 中的导航步骤，不再使用 URL 直达，改用菜单导航。

### Metadata
- Source: conversation
- Related Files: MEMORY.md
- Tags: in3, routing, navigation
- Pattern-Key: in3.menu_navigation

---

## [LRN-20260806-002] correction

**Logged**: 2026-08-06T10:21:00+08:00
**Priority**: high
**Status**: resolved
**Area**: config

### Summary
IN3 首页没有工厂切换选项，必须先进入下级菜单后才能切换工厂

### Details
Dongfang 纠正：首页找不到切换工厂的地方。工厂选择器只在进入采购管理、销售管理等下级页面后才会出现。切换工厂后页面跳回 `/home`，需要重新通过菜单导航进入目标页面。

### Suggested Action
MEMORY.md 已更新，cron prompt 已包含正确步骤。

### Metadata
- Source: user_feedback
- Related Files: MEMORY.md
- Tags: in3, factory-switch, navigation
- See Also: LRN-20260806-001
- Pattern-Key: in3.factory_switch
