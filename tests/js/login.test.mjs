/* 登录页纯函数测试：地块列表归一化、摘要文案、登录后分支判定。
 * 这些函数决定「多地块账号是否弹选择层」，逻辑错会让用户永远进不去或永远看到选择层。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const login = require('../../static/js/login.js');

test('normalizeFarms 过滤非法项并保留有效地块', () => {
    const raw = [
        { id: 3, name: 'A', lat: 23.1, lon: 113.2, area_m2: 500 },
        { id: '4', name: 'B' },
        { id: 0, name: 'bad' },
        { id: -1, name: 'bad' },
        { id: 'x', name: 'bad' },
        null,
        'nope'
    ];
    const out = login.normalizeFarms(raw);
    assert.equal(out.length, 2);
    assert.equal(out[0].id, 3);
    assert.equal(out[1].id, 4);
});

test('normalizeFarms 对非数组返回空数组', () => {
    assert.deepEqual(login.normalizeFarms(null), []);
    assert.deepEqual(login.normalizeFarms(undefined), []);
    assert.deepEqual(login.normalizeFarms({}), []);
});

test('farmMetaText 面积与坐标都有时拼接', () => {
    assert.equal(
        login.farmMetaText({ area_m2: 6667, lat: 23.1291, lon: 113.2644 }),
        '6667 m² · 23.1291, 113.2644'
    );
});

test('farmMetaText 大面积用公顷', () => {
    assert.equal(
        login.farmMetaText({ area_m2: 20000, lat: 23, lon: 113 }),
        '2.00 公顷 · 23.0000, 113.0000'
    );
});

test('farmMetaText 未标定时给出占位文案而不是 0,0', () => {
    assert.equal(login.farmMetaText({ area_m2: 0, lat: null, lon: null }), '面积与坐标待标定');
    assert.equal(login.farmMetaText({}), '面积与坐标待标定');
});

test('farmMetaText 经纬度 0 是合法值，不应被当成缺失', () => {
    assert.equal(login.farmMetaText({ lat: 0, lon: 0 }), '0.0000, 0.0000');
});

test('decideAfterLogin 单地块直接进入', () => {
    const r = login.decideAfterLogin({ farms: [{ id: 1, name: 'only' }], active_farm_id: 1 });
    assert.equal(r.action, 'enter');
    assert.equal(r.farms.length, 1);
});

test('decideAfterLogin 多地块弹选择层', () => {
    const r = login.decideAfterLogin({
        farms: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
        active_farm_id: 2
    });
    assert.equal(r.action, 'choose');
    assert.equal(r.farms.length, 2);
});

test('decideAfterLogin 无 farms 字段按进入处理（兼容旧响应）', () => {
    assert.equal(login.decideAfterLogin({ status: 'success' }).action, 'enter');
});

test('pickActiveFarmId 兼容 active_farm_id 与 active_id', () => {
    assert.equal(login.pickActiveFarmId({ active_farm_id: 5 }), 5);
    assert.equal(login.pickActiveFarmId({ active_id: 7 }), 7);
    assert.equal(login.pickActiveFarmId({ active_farm_id: 0 }), null);
    assert.equal(login.pickActiveFarmId({}), null);
});
