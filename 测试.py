#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
青禾智灌 ESP32-E 设备模拟器
================================
在不接入实体硬件的情况下，模拟 ESP32-E 田间采集控制终端，
通过 MQTT 持续向华为云 IoTDA 上报合理数据，用于平台联调与演示。

上报内容（与真实固件 esp.txt 保持一致）：
  - waterlevel  : 渠道水位 ADC 原始值（0~4095，前端换算为 mm）
  - humidity    : 土壤湿度 ADC 原始值（0~4095，前端换算为 %RH）
  - do          : 根区溶解氧含量（mg/L，0~20）
  - eh          : 根区氧化还原电位（mV，-150~300）
  - water_pump  : 水泵状态 "on"/"off"
  - air_pump    : 气泵状态 "on"/"off"

数据模拟逻辑：
  - 水位 / 土壤湿度 / DO / Eh 在合理范围内缓慢波动
  - 水泵按水位上下限自动启停（低开高关）
  - 气泵按 RORI 缺氧风险分级自动启停
  - 上报周期默认 3 秒（与真实固件一致）

用法：
  python esp32_simulator.py            # 使用 esp.txt 中的接入参数
  python esp32_simulator.py --interval 5   # 自定义上报间隔（秒）

依赖：
  pip install paho-mqtt
"""

import json
import math
import os
import random
import re
import sys
import time

import paho.mqtt.client as mqtt

# ============================================================
# 一、华为云 IoTDA 接入参数
#    优先读取同目录 esp.txt 中的设备参数；也可通过环境变量覆盖
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ESP_FILE = os.path.join(SCRIPT_DIR, 'esp.txt')


def _load_from_esp():
    """从 esp.txt 解析华为云接入参数（与真实设备一致）。"""
    params = {}
    try:
        with open(ESP_FILE, encoding='utf-8') as f:
            content = f.read()
        # 匹配  const char* NAME = "value";
        for name in ('MQTT_SERVER', 'MQTT_PORT', 'DEVICE_ID', 'CLIENT_ID', 'MQTT_USER', 'MQTT_PASS',
                     'TOPIC_M2M_SOURCE', 'TOPIC_CMD_RECV'):
            m = re.search(r'const\s+(?:char\s*\*|int\s+)\s*' + name + r'\s*=\s*"?([^";]+)"?', content)
            if m:
                params[name] = m.group(1)
    except Exception:
        pass
    return params


ESP = _load_from_esp()

# 接入参数（环境变量 > esp.txt > 默认值）
MQTT_HOST = os.environ.get('SIM_HOST') or ESP.get('MQTT_SERVER') or 'xxxxxxxx.iotda-device.cn-north-4.myhuaweicloud.com'
MQTT_PORT = int(os.environ.get('SIM_PORT') or ESP.get('MQTT_PORT') or 1883)
DEVICE_ID = os.environ.get('SIM_DEVICE_ID') or ESP.get('DEVICE_ID') or 'your_device_id'
CLIENT_ID = os.environ.get('SIM_CLIENT_ID') or ESP.get('CLIENT_ID') or ''
MQTT_USER = os.environ.get('SIM_USER') or ESP.get('MQTT_USER') or ''
MQTT_PASS = os.environ.get('SIM_PASS') or ESP.get('MQTT_PASS') or ''

# 上报 Topic（与真实固件一致）
TOPIC_REPORT = f'$oc/devices/{DEVICE_ID}/sys/properties/report'
# M2M 自定义 Topic：华为云数据转发规则将其转发到 /esp32e/data 供网页端读取
TOPIC_M2M = ESP.get('TOPIC_M2M_SOURCE') or '/esp32e/source'

# 默认上报间隔（秒），与固件一致
DEFAULT_INTERVAL = 3

# ============================================================
# 二、田间状态模拟器
# ============================================================

ADC_MAX = 4095.0
WATER_FS_MM = 300.0       # 水位满量程对应 300mm
SOIL_RANGE = 100.0        # 土壤湿度满量程 100%


class FieldSimulator:
    """模拟田间水位、土壤湿度、DO、Eh 的合理变化，并联动泵控。"""

    def __init__(self):
        # 初始状态取合理中值
        self.water_mm = 72.0          # 渠道水位 mm
        self.soil_pct = 55.0          # 土壤湿度 %RH
        self.do_mgl = 5.5             # 根区溶解氧 mg/L
        self.eh_mv = 120.0            # 根区氧化还原电位 mV
        self.water_pump = 'off'       # 水泵
        self.air_pump = 'off'         # 气泵
        self._t = 0.0                 # 模拟时间

    # ---- 物理量 -> ADC ----
    def water_adc(self):
        return int(max(0, min(self.water_mm / WATER_FS_MM * ADC_MAX, ADC_MAX)))

    def soil_adc(self):
        # 越湿润 ADC 越低
        return int(max(0, min((100 - self.soil_pct) / SOIL_RANGE * ADC_MAX, ADC_MAX)))

    # ---- RORI 分级（与前端 computeRori 一致）----
    def rori(self):
        W_EH, W_DO, W_WATER_SOIL, GAMMA = 0.35, 0.35, 0.30, 0.5
        sEh = max(0.0, min((300 - self.eh_mv) / 450.0, 1.0))
        sDo = max(0.0, min((8.0 - self.do_mgl) / 8.0, 1.0))
        risk_water = max(0.0, min((self.water_mm - 5) / 100.0, 1.0)) if self.water_mm > 5 else 0.0
        risk_soil = max(0.0, min(self.soil_pct / 100.0, 1.0))
        p_risk = (W_EH * sEh + W_DO * sDo
                  + W_WATER_SOIL * max(risk_water, risk_soil)
                  + GAMMA * risk_water * risk_soil)
        return max(0.0, min(p_risk, 1.0)) * 100

    # ---- 状态推进 ----
    def step(self, dt):
        self._t += dt
        period = 300.0  # 水位周期波动时长（秒），约 5 分钟一个周期

        # 水位：周期波动 + 随机扰动，35~108mm 之间变化
        # 低水位相对安全，高水位淹水越深、根区缺氧风险越高
        base = 70 + 38 * math.sin(2 * math.pi * self._t / period)
        self.water_mm += (base - self.water_mm) * 0.03 + random.gauss(0, 0.4)

        # 水泵自动控制：水位低开、高关（带滞回）
        if self.water_pump == 'off' and self.water_mm < 54:
            self.water_pump = 'on'
        elif self.water_pump == 'on' and self.water_mm > 86:
            self.water_pump = 'off'

        # 水泵开启时水位上升
        if self.water_pump == 'on':
            self.water_mm += 1.0 * dt
        self.water_mm = max(35, min(self.water_mm, 108))

        # 土壤湿度：与水位相关缓慢变化（灌溉/蒸发）
        wet_drive = (self.water_mm - 70) * 0.004 + (1.0 if self.water_pump == 'on' else -0.2)
        self.soil_pct += (wet_drive + random.gauss(0, 0.5)) * dt * 0.8
        self.soil_pct = max(40, min(self.soil_pct, 80))

        # DO / Eh：随淹水程度与加气而变化
        # 水位越高，淹水越深，DO 越低、Eh 越低
        water_effect = (self.water_mm - 72) / 70.0          # -0.49 ~ +0.54
        self.do_mgl += (-0.5 * water_effect + random.gauss(0, 0.15)) * dt
        self.eh_mv += (-18 * water_effect + random.gauss(0, 6)) * dt

        # 气泵自动控制：按 RORI 分级，中/重度缺氧开启增氧
        rori = self.rori()
        if self.air_pump == 'off' and rori >= 45:
            self.air_pump = 'on'
        elif self.air_pump == 'on' and rori <= 32:
            self.air_pump = 'off'

        # 气泵开启时 DO / Eh 回升
        if self.air_pump == 'on':
            self.do_mgl += 0.15 * dt
            self.eh_mv += 4.0 * dt

        self.do_mgl = max(2.5, min(self.do_mgl, 9.0))
        self.eh_mv = max(-40, min(self.eh_mv, 220))

    # ---- 生成物模型上报 payload ----
    def report_properties(self):
        return {
            'services': [{
                'service_id': 'esp',
                'properties': {
                    'waterlevel': self.water_adc(),
                    'humidity': self.soil_adc(),
                    'do': round(self.do_mgl, 1),
                    'eh': int(round(self.eh_mv)),
                    'water_pump': self.water_pump,
                    'air_pump': self.air_pump,
                },
            }]
        }

    # ---- 生成 M2M 上报 payload（自定义 Topic）----
    def m2m_payload(self):
        return {
            'waterlevel': self.water_adc(),
            'humidity': self.soil_adc(),
            'do': round(self.do_mgl, 1),
            'eh': int(round(self.eh_mv)),
            'water_pump': self.water_pump,
            'air_pump': self.air_pump,
        }

    def status_line(self):
        return (f'水位 {self.water_mm:5.1f}mm | 湿度 {self.soil_pct:5.1f}% | '
                f'DO {self.do_mgl:4.1f}mg/L | Eh {self.eh_mv:6.0f}mV | '
                f'RORI {self.rori():5.1f} | 水泵 {self.water_pump} | 气泵 {self.air_pump}')


# ============================================================
# 三、MQTT 客户端
# ============================================================

sim = FieldSimulator()


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print('[MQTT] 已连接华为云 IoTDA，设备:', DEVICE_ID)
        print('[MQTT] 物模型上报 Topic:', TOPIC_REPORT)
        print('[MQTT] M2M 转发 Topic  :', TOPIC_M2M)
    else:
        print(f'[MQTT] 连接失败，rc={rc}（0=成功，5=未授权，4=错误用户名/密码）')


def on_disconnect(client, userdata, rc, properties=None, reason_code=None):
    print('[MQTT] 连接断开，rc=', rc)


def main():
    # 解析命令行参数
    interval = DEFAULT_INTERVAL
    if '--interval' in sys.argv:
        i = sys.argv.index('--interval')
        if i + 1 < len(sys.argv):
            interval = max(1, int(sys.argv[i + 1]))

    print('==========================================')
    print(' 青禾智灌 ESP32-E 设备模拟器')
    print('==========================================')
    print('华为云 Host:', MQTT_HOST)
    print('设备 ID    :', DEVICE_ID)
    print('上报间隔   :', interval, '秒')
    print('------------------------------------------')
    print('未连接硬件，以下为模拟数据：')
    print('------------------------------------------')

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID or None)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
    except Exception as e:
        print(f'[MQTT] 连接异常: {e}')
        print('请检查网络与华为云接入参数（可编辑脚本顶部，或用环境变量 SIM_HOST 等覆盖）。')
        sys.exit(1)

    client.loop_start()

    next_report = time.time()
    try:
        while True:
            now = time.time()
            if now >= next_report:
                sim.step(interval)
                # 物模型上报（华为云标准）
                payload = json.dumps(sim.report_properties(), ensure_ascii=False)
                client.publish(TOPIC_REPORT, payload)
                # M2M 自定义 Topic（触发转发到 /esp32e/data 供网页端）
                client.publish(TOPIC_M2M, json.dumps(sim.m2m_payload(), ensure_ascii=False))
                print('[上报]', sim.status_line())
                next_report = now + interval
            time.sleep(0.2)
    except KeyboardInterrupt:
        print('\n模拟器已停止')
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
