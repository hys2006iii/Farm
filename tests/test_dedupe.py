"""运行日志与告警的「重复消息抑制」测试。

问题：设备抖动或自动调控反复触发时，极短时间内会产生大量**相同或极其相似**
的消息（正文里只有数值在变），把日志/告警区刷屏，并反复推送 webhook。

后端两道闸门：
- `logbook.add_log()`：`(用户, 级别, 来源, 正文指纹)` 在
  `config.LOG_COOLDOWN_SECONDS` 内只放行第一条；`cooldown=0` 可关闭；
- `alert_center.push_alert()`：去重键改为 `(uid, code, 正文指纹)`，
  同一类型码下数值抖动不再每次都算新告警。
"""

import time

import pytest

from qinghe import alert_center, config, logbook

from helpers import login_session, make_user


@pytest.fixture()
def uid(flask_app):
    """一个普通用户。"""
    created = make_user('dedupe01', 'secret123')
    assert created
    return created


@pytest.fixture(autouse=True)
def _clean_state():
    """每个用例前后清空冷却表，避免相互污染。"""
    logbook.reset_recent_logs()
    alert_center._reset_dedupe()
    yield
    logbook.reset_recent_logs()
    alert_center._reset_dedupe()


# ---------------------------------------------------------------- 日志指纹

def test_log_key_ignores_numbers():
    """正文里的数字被抹掉：数值抖动视为同一条日志。"""
    a = logbook._log_key(1, 'auto', 'auto', '[自动] 水位 29.8mm < 下限 30mm，自动开启水泵灌水')
    b = logbook._log_key(1, 'auto', 'auto', '[自动] 水位 30.1mm < 下限 30mm，自动开启水泵灌水')
    assert a == b


def test_log_key_distinguishes_facts_and_owners():
    """不同事实 / 不同用户 / 不同来源都不应被误判成同一条。"""
    base = logbook._log_key(1, 'info', 'auto', '[自动] 水位 29.8mm 偏低')
    assert base != logbook._log_key(1, 'info', 'auto', '[自动] RORI 72 重度厌氧')
    assert base != logbook._log_key(2, 'info', 'auto', '[自动] 水位 29.8mm 偏低')
    assert base != logbook._log_key(1, 'error', 'auto', '[自动] 水位 29.8mm 偏低')


def test_log_key_collapses_whitespace():
    """多余空白不影响指纹。"""
    assert logbook._log_key(1, 'info', 'system', '系统已启动，   正在连接云平台') == \
        logbook._log_key(1, 'info', 'system', '系统已启动， 正在连接云平台')


# ---------------------------------------------------------------- 日志冷却

def test_add_log_suppresses_repeats(uid):
    """冷却窗口内重复内容只落库一条。"""
    assert logbook.add_log(uid, '水位 29.8mm 偏低，开启水泵') is True
    assert logbook.add_log(uid, '水位 29.9mm 偏低，开启水泵') is False
    assert logbook.add_log(uid, '水位 30.2mm 偏低，开启水泵') is False
    logbook.flush_logs()
    rows = logbook.query_logs(uid, limit=50)
    assert len(rows) == 1


def test_add_log_keeps_distinct_messages(uid):
    """不同内容各自留痕，不被互相抑制。"""
    assert logbook.add_log(uid, '云服务连接成功') is True
    assert logbook.add_log(uid, '水泵已开启') is True
    assert logbook.add_log(uid, 'RORI 72 重度厌氧，强制增氧') is True
    logbook.flush_logs()
    assert len(logbook.query_logs(uid, limit=50)) == 3


def test_add_log_cooldown_zero_disables_dedupe(uid):
    """`cooldown=0` 关闭去重（需要逐条留痕的调用方）。"""
    for _ in range(3):
        assert logbook.add_log(uid, '心跳正常', cooldown=0) is True
    logbook.flush_logs()
    assert len(logbook.query_logs(uid, limit=50)) == 3


def test_add_log_releases_after_cooldown(uid, monkeypatch):
    """超过冷却窗口后同一条内容可以再次落库。"""
    monkeypatch.setattr(config, 'LOG_COOLDOWN_SECONDS', 0.05)
    assert logbook.add_log(uid, '水位偏低，开启水泵') is True
    assert logbook.add_log(uid, '水位偏低，开启水泵') is False
    time.sleep(0.08)
    assert logbook.add_log(uid, '水位偏低，开启水泵') is True


def test_add_log_ignores_invalid_uid():
    """非法 uid 不入队、不抛异常。"""
    assert logbook.add_log(0, '测试') is False
    assert logbook.add_log('abc', '测试') is False


def test_add_log_burst_is_bounded(uid, monkeypatch):
    """一轮高频刷屏只留少量条目（冷却窗口内重复内容不落库）。

    直接调 `_should_log` 而不是 `add_log`：本用例要断言的是**冷却闸门**本身，
    不应依赖全局队列的批处理时序（后台线程与 flush 的竞态会让计数不确定）。
    """
    cooldown = 3600.0
    now = time.monotonic()
    table = {}
    accepted = 0
    for i in range(200):
        if logbook._should_log(uid, 'info', 'auto',
                               '[自动] 水位 %.1fmm < 下限 30mm，自动开启水泵灌水' % (29.0 + i * 0.01),
                               cooldown):
            accepted += 1
        if logbook._should_log(uid, 'info', 'device', '[设备] 心跳正常', cooldown):
            accepted += 1
    assert accepted == 2, '200 轮重复刷屏应只放行 2 类条目，实际 %d' % accepted
    # 冷却表本身有界
    assert len(logbook._recent_logs) <= logbook._RECENT_MAX


def test_add_log_burst_writes_few_rows(uid, monkeypatch):
    """端到端：高频刷屏后落库条数很少（允许后台线程在途造成的少量偏差）。"""
    monkeypatch.setattr(config, 'LOG_COOLDOWN_SECONDS', 3600)
    for i in range(100):
        logbook.add_log(uid, '[自动] 水位 %.1fmm < 下限 30mm，自动开启水泵灌水' % (29.0 + i * 0.01))
    logbook.flush_logs()
    rows = logbook.query_logs(uid, limit=500)
    assert len(rows) <= 3, '100 轮重复刷屏后落库条数应极少，实际 %d' % len(rows)
    assert len(rows) >= 1


def test_reset_recent_logs_clears_cooldown(uid):
    """重置后同一条内容可以立刻再次落库（测试隔离用）。"""
    assert logbook.add_log(uid, '重复内容') is True
    assert logbook.add_log(uid, '重复内容') is False
    logbook.reset_recent_logs()
    assert logbook.add_log(uid, '重复内容') is True


# ---------------------------------------------------------------- 告警去重

def test_alert_dedupe_ignores_numeric_drift(uid):
    """同一类型码下数值抖动不再每次都算新告警。"""
    first = alert_center.push_alert(uid, 'warning', 'soil_low', '土壤湿度过低 20.1% < 下限 40%，建议补灌')
    second = alert_center.push_alert(uid, 'warning', 'soil_low', '土壤湿度过低 19.8% < 下限 40%，建议补灌')
    assert first['deduped'] is False
    assert second['deduped'] is True, '数值抖动应被冷却挡下'
    assert len(alert_center.list_alerts(uid, limit=50)) == 1


def test_normalize_alert_text_strips_numbers_and_whitespace():
    """指纹归一化：数字抹成 `#`，连续空白压成一个空格。"""
    assert alert_center.normalize_alert_text('水位 29.8mm   偏低') == '水位 #mm 偏低'
    assert alert_center.normalize_alert_text(None) == ''
    assert alert_center.normalize_alert_text('RORI 72 重度厌氧') == \
        alert_center.normalize_alert_text('RORI 75 重度厌氧')


def test_alert_dedupe_keeps_different_codes(uid):
    """不同类型码各自独立，不被互相抑制。"""
    assert alert_center.push_alert(uid, 'warning', 'soil_low', '土壤湿度过低')['deduped'] is False
    assert alert_center.push_alert(uid, 'danger', 'rori_high', 'RORI 75 重度厌氧')['deduped'] is False
    assert alert_center.push_alert(uid, 'warning', 'water_high', '水位过高')['deduped'] is False
    assert len(alert_center.list_alerts(uid, limit=50)) == 3


def test_alert_dedupe_is_per_user(uid):
    """冷却按用户隔离，一个账号的重复不影响另一个账号。"""
    other = make_user('dedupe02', 'secret123')
    assert other
    assert alert_center.push_alert(uid, 'warning', 'soil_low', '土壤湿度过低')['deduped'] is False
    assert alert_center.push_alert(other, 'warning', 'soil_low', '土壤湿度过低')['deduped'] is False


def test_alert_burst_is_bounded(uid, monkeypatch):
    """阈值附近抖动 100 次只落一条告警。"""
    monkeypatch.setattr(config, 'ALERT_COOLDOWN_SECONDS', 3600)
    for i in range(100):
        alert_center.push_alert(uid, 'warning', 'water_low',
                                '渠道水位偏低（%.1f mm，低于下限 30 mm）' % (29.9 - i * 0.01))
    assert len(alert_center.list_alerts(uid, limit=500)) == 1


def test_evaluate_and_push_burst_is_bounded(client, registered, monkeypatch):
    """evaluate_and_push 连续抖动评估也只落一条同类告警。"""
    monkeypatch.setattr(config, 'ALERT_COOLDOWN_SECONDS', 3600)
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    added = 0
    for i in range(30):
        result = alert_center.evaluate_and_push(
            uid,
            soil_pct=20.0 + i * 0.1,     # 一直低于下限
            water_mm=100.0,
            rori=10.0,
            humi_lower=40.0,
            humi_upper=80.0,
            water_lower=30.0,
            water_upper=150.0,
        )
        added += len(result)
    assert added == 1, '连续 30 次评估应只产生 1 条 soil_low 告警，实际 %d' % added
