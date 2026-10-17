const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, AlignmentType, ShadingType, BorderStyle, PageOrientation,
} = require('docx');

const GREEN = '1F6B45';
const DARK = '174D32';
const SUB = '6B7A72';

// 表头单元格
const hCell = (text) => new TableCell({
  width: { size: 25, type: WidthType.PERCENTAGE },
  shading: { type: ShadingType.CLEAR, fill: 'E7F3EB' },
  children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: DARK })] })],
});
const tCell = (text) => new TableCell({
  width: { size: 25, type: WidthType.PERCENTAGE },
  children: [new Paragraph({ children: [new TextRun({ text })] })],
});

const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300, after: 160 }, children: [new TextRun({ text: t, color: DARK })] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 220, after: 120 }, children: [new TextRun({ text: t, color: GREEN })] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 160, after: 80 }, children: [new TextRun({ text: t })] });
const P = (t) => new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t })] });
const B = (t) => new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: '• ' + t })] });

const twoCol = (rows) => new Table({
  columnWidths: [4000, 4000],
  width: { size: 100, type: WidthType.PERCENTAGE },
  rows: rows.map((r, i) => new TableRow({ children: [hCell(r[0]), tCell(r[1])] })),
});

const doc = new Document({
  styles: {
    default: { document: { run: { font: 'Microsoft YaHei', size: 21 } } },
  },
  sections: [{
    properties: { page: { margin: { top: 1000, bottom: 1000, left: 1200, right: 1200 } } },
    children: [
      // ===== 封面 =====
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400, after: 300 }, children: [new TextRun({ text: '青禾智灌', bold: true, size: 72, color: DARK })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: '智能灌溉与水利控制系统', size: 36, color: GREEN })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: '用户手册', size: 44, color: SUB })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 800 }, children: [new TextRun({ text: '版本 V1.0', size: 24, color: SUB })] }),

      // ===== 目录说明 =====
      H1('一、系统简介'),
      P('青禾智灌是一套面向农业灌溉与水利管理的智能监控系统。系统通过 ESP32-E 传感器设备采集田间渠道水位与土壤湿度数据，经华为云 IoTDA 物联网平台实时上报，在 Web 端看板呈现可视化趋势，并支持对水泵、气泵的远程控制与基于根区缺氧风险指数（RORI）的自动调控。'),
      P('系统包含以下能力：实时数据监测、降雨量预测与动态阈值、根区缺氧风险评估、设备手动/自动调控、告警推送、AI 智能问答、历史趋势分析等。'),

      // ===== 登录 =====
      H1('二、账号与登录'),
      H2('2.1 登录系统'),
      B('打开浏览器，访问系统地址（默认本机 http://localhost:5000）。'),
      B('在登录页输入「账号」和「密码」，点击「登录」。'),
      B('登录成功后进入主看板。'),
      H2('2.2 注册新账号'),
      P('登录页点击「注册新账号」，填写账号（3-20 字符）和密码（6-64 字符），确认密码后注册。注册成功自动返回登录。'),
      H2('2.3 修改密码'),
      P('登录后点击右上角「系统设置」→「修改密码」，输入原密码与新密码即可。修改成功后需重新登录。'),
      H2('2.4 退出登录'),
      P('点击「系统设置」→「退出登录」。'),

      // ===== 主界面 =====
      H1('三、主界面概览'),
      P('主看板分为三大区域：左侧（气象/传感器/降雨/告警）、右侧（设备调控/运行日志）、底部（实时趋势）。顶部栏显示系统时间、云平台连接状态、设备连接状态，并提供「AI 助手」「系统设置」入口。'),
      twoCol([
        ['顶部状态', '华为云连接状态（云朵点）、传感器连接状态、当前系统时间'],
        ['左侧栏', '田间气象、传感器实时数据、RORI 风险、未来降雨预测、告警记录'],
        ['右侧栏', '手动/自动调控面板、阈值设定、运行日志'],
        ['底部', '水位/土壤湿度/RORI 实时趋势图'],
      ]),

      // ===== 气象 =====
      H1('四、田间气象显示'),
      P('「田间区域气象」卡片显示农场当前位置、实时温度与空气湿度。数据来自 Open-Meteo 免费天气接口。'),
      B('位置：自动按配置的经纬度反查地名；未配置坐标时显示农场名称。'),
      B('天气：实时温度（°C）与相对湿度（%）。'),

      // ===== 传感器 =====
      H1('五、传感器实时数据'),
      H2('5.1 数据卡片'),
      P('「传感器实时数据」面板显示四个核心指标：'),
      twoCol([
        ['渠道水位', '水位传感器原始 ADC 换算为毫米（mm）'],
        ['土壤湿度', '土壤湿度传感器换算为 0~100% 湿润度'],
        ['气泵状态', '运行中 / 待机关闭'],
        ['水泵状态', '运行中 / 待机关闭'],
      ]),
      H2('5.2 数据更新频率'),
      P('ESP32-E 设备每约 3 秒上报一次传感器数据，经华为云转发到网页实时刷新。'),
      H2('5.3 设备连接状态'),
      P('顶部栏「传感器：已连接/未连接」反映设备实时连通性。系统采用冗余判定：连续约 40 秒未收到数据才判定离线，避免偶发网络抖动造成误报。'),

      // ===== RORI =====
      H1('六、根区缺氧风险指数（RORI）'),
      P('RORI 是系统核心的自动调控依据，综合评估根区缺氧风险，范围 0~100。'),
      H2('6.1 RORI 分级'),
      twoCol([
        ['RORI < 40', '安全运行 — 根区有氧环境优良，加气机低耗待机'],
        ['40 ≤ RORI < 70', '中度缺氧 — 根区微量缺氧，周期性脉冲加气补氧'],
        ['RORI ≥ 70', '重度厌氧 — 加气机全满载强制增氧'],
      ]),
      H2('6.2 RORI 计算来源'),
      P('当前接入水位与土壤湿度实测数据，融合计算 RORI。将来接入氧化还原电位（Eh）和溶解氧（DO）传感器后可进一步提升精度。'),

      // ===== 降雨 =====
      H1('七、未来降雨预测与动态阈值'),
      H2('7.1 降雨预测'),
      P('「未来6日降雨量预测」展示未来 6 天逐日降雨量（mm）。数据经后端代理调用和风天气接口，避免浏览器跨域限制。'),
      H2('7.2 动态阈值（降雨前馈）'),
      P('系统根据 6 日滚动降雨量 P6d 动态调整土壤湿度阈值，实现"前馈控水等雨"：'),
      B('预测有雨：下调灌溉触发下限，暂缓补水、留存天然降雨。'),
      B('强降雨（P6d≥15mm）：放宽蓄水上限，蓄雨型控灌。'),
      P('「阈值设定」区域会显示当前动态阈值的计算提示。'),

      // ===== 告警 =====
      H1('八、告警记录与推送'),
      H2('8.1 告警类型'),
      B('土壤湿度低于/高于动态阈值。'),
      B('渠道水位超过上限。'),
      B('RORI 达中度缺氧（40）或重度厌氧（70）。'),
      H2('8.2 告警展示'),
      P('告警在「告警记录」面板按时间倒序展示（保留最近 24 小时），触发时页面顶部会显示预警横幅并弹窗提示。'),
      H2('8.3 Webhook 推送'),
      P('系统可配置钉钉/企业微信/飞书机器人 Webhook，告警触发时自动推送。推送消息以「【青禾智灌系统】」开头，满足钉钉机器人关键词安全设置。'),

      // ===== 设备调控 =====
      H1('九、设备调控'),
      H2('9.1 手动 / 自动模式切换'),
      P('「手动 / 自动调控」面板顶部有模式切换按钮：'),
      B('自动智能调控模式（默认）：系统根据 RORI 与水位阈值自动开关水泵、气泵。'),
      B('手动接管模式：关闭自动调控，由用户手动控制设备启停。'),
      H2('9.2 手动控制'),
      P('手动模式下，可分别点击水泵、气泵的「启动」「停止」按钮远程控制设备。'),
      H2('9.3 自动调控逻辑'),
      P('自动模式下，系统按以下逻辑自动控制：'),
      B('气泵：RORI 达中度缺氧即开启增氧，重度厌氧全功率增氧；预测降雨时提前一级增氧。'),
      B('水泵：水位低于下限自动开泵灌水，高于上限自动关泵；预测降雨时暂缓补水留存雨水。'),
      H2('9.4 阈值设定'),
      P('「应用全套设定参数」按钮将当前滑杆设定保存到服务器，供自动调控逻辑使用，刷新页面后依然保留。'),
      twoCol([
        ['土壤湿度阈值', '下限 ~ 上限（%RH），超出触发告警与调控'],
        ['渠道水位阈值', '下限 ~ 上限（mm），水位越限触发补水/排水'],
      ]),

      // ===== 趋势图 =====
      H1('十、实时趋势图'),
      P('底部「实时趋势」区以图表呈现三个指标的历史变化：渠道水位（mm）、土壤湿度（%）、RORI 风险指数。'),
      B('图表类型：可在「折线图」和「柱状图」之间切换。'),
      B('历史跨度：本地保存最近 3 天趋势，按分钟聚合。'),
      B('横轴：跨天时自动标注日期（MM-DD HH:MM）。'),

      // ===== 日志 =====
      H1('十一、运行日志'),
      P('「运行日志」面板实时记录系统运行事件，包括：模式切换、阈值保存、自动调控动作、设备连接状态变化、指令发送等。日志保留最近 24 小时（最多 200 条），刷新页面不丢失。'),

      // ===== AI 助手 =====
      H1('十二、AI 智能助手'),
      P('点击顶部「AI 助手」打开智能问答面板，可咨询灌溉调控、设备操作、土壤管理等农业水利问题。'),
      B('需要先在「系统设置」中配置 AI 接口域名与 API Key（默认支持 DeepSeek）。'),
      B('未配置时，助手会提示先配置 AI Key。'),

      // ===== 系统设置 =====
      H1('十三、系统设置'),
      P('点击顶部「系统设置」进入配置界面。所有配置按账号保存，登录后自动加载。'),
      H2('13.1 账号信息'),
      B('当前账户：显示登录账号。'),
      B('修改密码：更新登录密码。'),
      H2('13.2 农场信息'),
      B('农场名称：显示在气象卡片。'),
      B('经度/纬度：用于天气查询与位置反查。'),
      H2('13.3 华为云 MQTT 接入'),
      P('配置网页端连接华为云 IoTDA 的参数，用于接收设备数据与下发控制指令。'),
      twoCol([
        ['MQTT 接入 Host', 'IoTDA 设备接入地址'],
        ['客户端设备 ID', 'app 客户端设备标识（client）'],
        ['田间设备 ID', 'ESP32-E 传感器设备标识'],
        ['MQTT Client ID', '客户端连接标识'],
        ['MQTT User / Password', '接入鉴权账号密码'],
        ['M2M 数据转发 Topic', '传感器数据转发主题（默认 /esp32e/data）'],
        ['命令下行转发 Topic', '控制指令转发主题（默认 /esp32e/cmd）'],
      ]),
      H2('13.4 天气 / AI / Webhook 配置'),
      B('降雨预测平台接口 + Weather API Key：和风天气接口。'),
      B('AI 助手接口 + AI API Key：大模型问答接口。'),
      B('告警 Webhook：钉钉/企业微信/飞书机器人地址，告警自动推送。'),

      // ===== 数据流转 =====
      H1('十四、系统数据流转原理'),
      P('数据在设备、云平台、网页端之间流转：'),
      B('传感器上行：ESP32-E 每 3s 上报水位/湿度/泵状态 → 华为云物模型 → 数据转发规则 → 网页实时显示。'),
      B('控制下行：网页点按钮 → app（client 身份）发布命令到命令转发 Topic → 华为云转发 → ESP32-E 订阅执行 → 回发状态。'),
      P('系统需在华为云配置两条数据转发规则：传感器数据转发（/esp32e/source → /esp32e/data）与命令下行转发（→ /esp32e/cmd）。'),

      // ===== 常见问题 =====
      H1('十五、常见问题（FAQ）'),
      H2('15.1 网页一直显示"华为云：未连接"'),
      B('检查系统设置中的华为云 MQTT 接入参数是否正确（Host、Client ID、User、Password）。'),
      B('确认设备（ESP32-E）与 app 客户端均已注册在华为云 IoTDA。'),
      B('检查网络能否访问华为云地址。'),
      H2('15.2 传感器数据不刷新'),
      B('确认 ESP32-E 已上电并联网。'),
      B('确认华为云数据转发规则已配置且指向正确主题。'),
      B('观察设备约 40 秒未上报才会判定离线，可稍作等待。'),
      H2('15.3 手动控制设备无响应'),
      B('确认设备在线。'),
      B('确认命令下行转发 Topic 与系统设置中的「命令下行转发 Topic」一致。'),
      B('确认 ESP32-E 固件已订阅对应命令主题。'),
      H2('15.4 忘记密码'),
      B('联系系统管理员，或使用已登录账号在设置中修改。'),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync('D:/AI/Farm/青禾智灌用户手册.docx', buf);
  console.log('手册已生成: 青禾智灌用户手册.docx');
});
