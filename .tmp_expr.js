(function () {
  var r = function (el) { if(!el) return null; var b = el.getBoundingClientRect(); return { t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) }; };
  var q = function (s) { return document.querySelector(s); };
  var sensor = q('#sensorPanel'), ctrl = q('#controlPanel');
  var names = [].map.call(document.querySelectorAll('.sensor-cell .sensor-name'), function (e) { return e.textContent.trim(); });
  var fills = [].map.call(document.querySelectorAll('.dual-range-container'), function (c) {
    var f = c.querySelector('.dual-range-fill');
    var d = c.querySelector('input.range-lo'), u = c.querySelector('input.range-hi');
    return { fillLeft: f ? f.style.left : null, fillWidth: f ? f.style.width : null,
      fillBg: f ? getComputedStyle(f).backgroundColor : null,
      down: d ? d.value : null, up: u ? u.value : null, downClass: d ? d.className : null, upClass: u ? u.className : null };
  });
  var logCard = q('.right-col .log-stretch'), fullSpan = q('.section.full-span');
  return { viewport: { w: innerWidth, h: innerHeight },
    mainWrap: r(q('.main-wrap')), mainWrapRows: getComputedStyle(q('.main-wrap')).gridTemplateRows,
    leftCol: r(q('.left-col')), rightCol: r(q('.right-col')),
    sensorPanel: r(sensor), controlPanel: r(ctrl),
    bottomAligned: Math.abs(r(sensor).b - r(ctrl).b) <= 1, deltaBottom: r(ctrl).b - r(sensor).b,
    sensorTitle: q('#sensorPanel .section-hd').textContent.trim(),
    sensorNames: names, airPumpIdx: names.indexOf('气泵'), waterPumpIdx: names.indexOf('水泵'),
    sensorGridCols: getComputedStyle(q('.sensor-grid')).gridTemplateColumns,
    fills: fills, logCard: r(logCard), logScrollH: Math.round(q('.log-stretch .log-scroll').getBoundingClientRect().height),
    logFlex: getComputedStyle(logCard).flex, fullSpan: r(fullSpan),
    applyBtnBottom: r(q('#autoThresholdArea .btn-wide:last-child')).b, ctrlBottomInner: r(q('#controlPanel .section-bd')).b,
    consoleErrors: (window.__probeErrors || []) };
})()
