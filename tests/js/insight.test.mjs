/**
 * insight.js 纯函数单元测试（node --test，零依赖）
 *
 * 运行：npm run test:js
 *     或 node --test "tests/js/**\/*.test.mjs"
 *
 * insight.js 是浏览器 IIFE，末尾有 `if (typeof document === 'undefined') return;`
 * 守卫，因此在 node 下只会挂载 InsightPure，不会触碰 DOM。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../static/js/insight.js');

/* ==================== 级别 -> 颜色 / 中文 ==================== */
test('levelClass: danger=红 warning=橙 info=蓝', () => {
    assert.equal(P.levelClass('danger'), 'lv-danger');
    assert.equal(P.levelClass('warning'), 'lv-warning');
    assert.equal(P.levelClass('info'), 'lv-info');
});

test('levelClass: 大小写不敏感 + error/warn 别名', () => {
    assert.equal(P.levelClass('DANGER'), 'lv-danger');
    assert.equal(P.levelClass('Warning'), 'lv-warning');
    assert.equal(P.levelClass('error'), 'lv-danger');
    assert.equal(P.levelClass('warn'), 'lv-warning');
});

test('levelClass: 未知 / 空值回退 info 蓝（不抛异常）', () => {
    assert.equal(P.levelClass('unknown'), 'lv-info');
    assert.equal(P.levelClass(''), 'lv-info');
    assert.equal(P.levelClass(null), 'lv-info');
    assert.equal(P.levelClass(undefined), 'lv-info');
});

test('levelText: 三级中文名与未知兜底', () => {
    assert.equal(P.levelText('danger'), '严重');
    assert.equal(P.levelText('warning'), '警告');
    assert.equal(P.levelText('info'), '提示');
    assert.equal(P.levelText('weird'), '未知');
    assert.equal(P.levelText(null), '未知');
});

/* ==================== 来源 -> 中文映射 ==================== */
test('sourceText: 6 个来源全部映射为中文', () => {
    assert.equal(P.sourceText('system'), '系统');
    assert.equal(P.sourceText('device'), '设备');
    assert.equal(P.sourceText('auto'), '自动调控');
    assert.equal(P.sourceText('manual'), '手动');
    assert.equal(P.sourceText('plan'), '预案');
    assert.equal(P.sourceText('config'), '配置');
});

test('sourceText: 大小写不敏感；未知来源原样返回不编造', () => {
    assert.equal(P.sourceText('SYSTEM'), '系统');
    assert.equal(P.sourceText('Auto'), '自动调控');
    assert.equal(P.sourceText('mystery'), 'mystery');
    assert.equal(P.sourceText(null), '未知');
    assert.equal(P.sourceText(''), '未知');
});

test('sourceText: SOURCE_TEXT 表覆盖 6 个来源且无多余键', () => {
    assert.deepEqual(Object.keys(P.SOURCE_TEXT).sort(),
        ['auto', 'config', 'device', 'manual', 'plan', 'system']);
});

test('sourceClass: 已知来源给 src-<name>，未知回退 src-system', () => {
    assert.equal(P.sourceClass('auto'), 'src-auto');
    assert.equal(P.sourceClass('plan'), 'src-plan');
    assert.equal(P.sourceClass('nope'), 'src-system');
    assert.equal(P.sourceClass(null), 'src-system');
});

test('logLevelClass: error/warning/info 三档', () => {
    assert.equal(P.logLevelClass('error'), 'log-error');
    assert.equal(P.logLevelClass('warning'), 'log-warning');
    assert.equal(P.logLevelClass('warn'), 'log-warning');
    assert.equal(P.logLevelClass('info'), 'log-info');
    assert.equal(P.logLevelClass(null), 'log-info');
});

/* ==================== 预案状态 / 设备动作 ==================== */
test('planStatusText: pending/confirmed/rejected/expired/failed 中文名', () => {
    assert.equal(P.planStatusText('pending'), '待确认');
    assert.equal(P.planStatusText('confirmed'), '已下发');
    assert.equal(P.planStatusText('rejected'), '已拒绝');
    assert.equal(P.planStatusText('expired'), '已过期');
    assert.equal(P.planStatusText('failed'), '下发失败');
    assert.equal(P.planStatusText('zzz'), 'zzz');
    assert.equal(P.planStatusText(null), '未知');
});

test('planStatusClass: 已知状态给 st-<name>，未知回退 st-expired', () => {
    assert.equal(P.planStatusClass('pending'), 'st-pending');
    assert.equal(P.planStatusClass('confirmed'), 'st-confirmed');
    assert.equal(P.planStatusClass('bogus'), 'st-expired');
});

test('actionText: on/off 及别名转中文，未知原样', () => {
    assert.equal(P.actionText('on'), '开启');
    assert.equal(P.actionText('ON'), '开启');
    assert.equal(P.actionText('start'), '开启');
    assert.equal(P.actionText('off'), '关闭');
    assert.equal(P.actionText('stop'), '关闭');
    assert.equal(P.actionText('pulse'), 'pulse');
    assert.equal(P.actionText(null), '—');
});

test('deviceText: 气泵 / 水泵 / 未知兜底', () => {
    assert.equal(P.deviceText('air_pump'), '气泵');
    assert.equal(P.deviceText('water_pump'), '水泵');
    assert.equal(P.deviceText('AIR_PUMP'), '气泵');
    assert.equal(P.deviceText('fan'), 'fan');
    assert.equal(P.deviceText(null), '未知设备');
});

/* ==================== 时间格式化 ==================== */
test('fmtStamp: 毫秒时间戳 -> MM-DD HH:MM:SS', () => {
    const ts = new Date(2026, 9, 18, 9, 5, 3).getTime();   // 2026-10-18 09:05:03 本地
    assert.equal(P.fmtStamp(ts), '10-18 09:05:03');
});

test('fmtStamp: 补零正确（个位数月/日/时/分/秒）', () => {
    const ts = new Date(2026, 0, 2, 3, 4, 5).getTime();
    assert.equal(P.fmtStamp(ts), '01-02 03:04:05');
});

test('fmtStamp: 非法值统一 --（不显示 NaN）', () => {
    assert.equal(P.fmtStamp(0), '--');
    assert.equal(P.fmtStamp(-1), '--');
    assert.equal(P.fmtStamp(NaN), '--');
    assert.equal(P.fmtStamp(null), '--');
    assert.equal(P.fmtStamp(undefined), '--');
    assert.equal(P.fmtStamp('abc'), '--');
    assert.equal(P.fmtStamp(''), '--');
});

test('fmtStamp: 数字字符串可被接受', () => {
    const ts = new Date(2026, 5, 1, 12, 0, 0).getTime();
    assert.equal(P.fmtStamp(String(ts)), '06-01 12:00:00');
});

test('fmtSilent: 各区间文案', () => {
    assert.equal(P.fmtSilent(0), '刚刚');
    assert.equal(P.fmtSilent(4), '刚刚');
    assert.equal(P.fmtSilent(5), '5 秒');
    assert.equal(P.fmtSilent(59), '59 秒');
    assert.equal(P.fmtSilent(60), '1 分钟');
    assert.equal(P.fmtSilent(65), '1 分 5 秒');
    assert.equal(P.fmtSilent(3599), '59 分 59 秒');
    assert.equal(P.fmtSilent(3600), '1 小时');
    assert.equal(P.fmtSilent(7800), '2 小时 10 分');
});

test('fmtSilent: 非法值回退 --', () => {
    assert.equal(P.fmtSilent(NaN), '--');
    assert.equal(P.fmtSilent(-3), '--');
    assert.equal(P.fmtSilent(null), '--');
    assert.equal(P.fmtSilent(undefined), '--');
    assert.equal(P.fmtSilent(''), '--');
    assert.equal(P.fmtSilent('x'), '--');
});

test('fmtSilent: null/undefined 表示无数据，不能误判为 0 秒「刚刚」', () => {
    // Number(null) === 0 是经典陷阱：若不显式判空会渲染成「刚刚」，误导用户以为设备刚上报
    assert.notEqual(P.fmtSilent(null), '刚刚');
    assert.notEqual(P.fmtSilent(undefined), '刚刚');
    assert.equal(P.fmtSilent(0), '刚刚');   // 真正的 0 秒仍是「刚刚」
});

test('fmtSilent: 小数秒向下取整', () => {
    assert.equal(P.fmtSilent(9.9), '9 秒');
    assert.equal(P.fmtSilent(65.7), '1 分 5 秒');
});

/* ==================== 数值格式化（保留 1 位小数） ==================== */
test('fmtNum: 默认保留 1 位小数', () => {
    assert.equal(P.fmtNum(0), '0.0');
    assert.equal(P.fmtNum(12.345), '12.3');
    assert.equal(P.fmtNum(12.36), '12.4');
    assert.equal(P.fmtNum(100), '100.0');
    assert.equal(P.fmtNum(-1.25), '-1.3');
});

test('fmtNum: 数字字符串可解析', () => {
    assert.equal(P.fmtNum('3.14159'), '3.1');
    assert.equal(P.fmtNum('7'), '7.0');
});

test('fmtNum: null/undefined/NaN/非数字 -> 0.0（界面不出现 NaN）', () => {
    assert.equal(P.fmtNum(null), '0.0');
    assert.equal(P.fmtNum(undefined), '0.0');
    assert.equal(P.fmtNum(NaN), '0.0');
    assert.equal(P.fmtNum(Infinity), '0.0');
    assert.equal(P.fmtNum('abc'), '0.0');
    assert.equal(P.fmtNum({}), '0.0');
});

test('fmtNum: digits=0 时回退 0 而非 0.0', () => {
    assert.equal(P.fmtNum(NaN, 0), '0');
    assert.equal(P.fmtNum(5.6, 0), '6');
});

/* ==================== 空列表渲染文案 ==================== */
test('emptyText: 5 个 Tab 各有空态文案', () => {
    assert.equal(P.emptyText('alerts'), '暂无告警记录');
    assert.equal(P.emptyText('logs'), '暂无运行日志');
    assert.equal(P.emptyText('device'), '暂无设备上报记录');
    assert.equal(P.emptyText('plans'), '暂无历史预案');
    assert.equal(P.emptyText('metrics'), '所选时段暂无数据');
});

test('emptyText: 未知 kind 回退「暂无数据」，文案非空', () => {
    assert.equal(P.emptyText('zzz'), '暂无数据');
    assert.equal(P.emptyText(null), '暂无数据');
    assert.ok(P.emptyText('alerts').length > 0);
});

/* ==================== metrics 指标卡 ==================== */
test('metricCards: 返回 4 张卡且数值保留 1 位小数', () => {
    const cards = P.metricCards({
        water_liters: 123.456, air_minutes: 90, ch4_saved_g: 1.2, co2e_saved_g: 33.6
    });
    assert.equal(cards.length, 4);
    assert.deepEqual(cards.map(c => c.key),
        ['water_liters', 'air_minutes', 'ch4_saved_g', 'co2e_saved_g']);
    assert.equal(cards[0].value, '123.5');
    assert.equal(cards[1].value, '90.0');
    assert.equal(cards[2].value, '1.2');
    assert.equal(cards[3].value, '33.6');
});

test('metricCards: 中文标签与单位正确', () => {
    const cards = P.metricCards({});
    assert.equal(cards[0].label, '灌溉用水量');
    assert.equal(cards[0].unit, 'L');
    assert.equal(cards[1].label, '增氧时长');
    assert.equal(cards[1].unit, 'min');
    assert.equal(cards[2].unit, 'g');
    assert.equal(cards[3].unit, 'g');
});

test('metricCards: 空对象/缺字段/null 全部回退 0.0 不抛异常', () => {
    P.metricCards({}).forEach(c => assert.equal(c.value, '0.0'));
    P.metricCards(null).forEach(c => assert.equal(c.value, '0.0'));
    P.metricCards(undefined).forEach(c => assert.equal(c.value, '0.0'));
    P.metricCards({ water_liters: NaN }).forEach(c => assert.equal(c.value, '0.0'));
});

/* ==================== metrics 逐日表格 ==================== */
test('metricRows: 逐行格式化且字段齐全', () => {
    const rows = P.metricRows([
        { day: '2026-10-18', water_liters: 10.55, pump_minutes: 3.2, air_minutes: 60, ch4_saved_g: 0.8, co2e_saved_g: 22.4 }
    ]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].day, '2026-10-18');
    assert.equal(rows[0].water_liters, '10.6');
    assert.equal(rows[0].pump_minutes, '3.2');
    assert.equal(rows[0].air_minutes, '60.0');
    assert.equal(rows[0].ch4_saved_g, '0.8');
    assert.equal(rows[0].co2e_saved_g, '22.4');
});

test('metricRows: 非数组入参返回空数组', () => {
    assert.deepEqual(P.metricRows(null), []);
    assert.deepEqual(P.metricRows(undefined), []);
    assert.deepEqual(P.metricRows({}), []);
    assert.deepEqual(P.metricRows('x'), []);
});

test('metricRows: 行内缺字段兜底 0.0，day 缺失兜底 --', () => {
    const rows = P.metricRows([{}]);
    assert.equal(rows[0].day, '--');
    assert.equal(rows[0].water_liters, '0.0');
    assert.equal(rows[0].co2e_saved_g, '0.0');
});

test('metricRows: null 行不抛异常', () => {
    const rows = P.metricRows([null, undefined]);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].day, '--');
});

/* ==================== 模块导出契约 ==================== */
test('InsightPure 导出的函数齐全（供浏览器与 node 共用）', () => {
    ['levelClass', 'levelText', 'sourceText', 'sourceClass', 'logLevelClass',
        'planStatusText', 'planStatusClass', 'actionText', 'deviceText',
        'fmtStamp', 'fmtSilent', 'fmtNum', 'pad2', 'emptyText',
        'metricCards', 'metricRows'].forEach(name => {
        assert.equal(typeof P[name], 'function', 'missing export: ' + name);
    });
});

test('在 node 下加载 insight.js 不会因缺少 DOM 而抛错', () => {
    assert.equal(typeof globalThis.document, 'undefined');
    assert.equal(typeof P.metricCards, 'function');
});
