(function () {
  var r = function (el) { if(!el) return null; var b = el.getBoundingClientRect(); return { t: Math.round(b.top), b: Math.round(b.bottom), h: Math.round(b.height) }; };
  var left = document.querySelector('.left-col'), right = document.querySelector('.right-col');
  var kids = function (col) { return [].map.call(col.children, function (c) { return { cls: c.className, id: c.id, ...r(c) }; }); };
  return { vw: innerWidth,
    leftRows: getComputedStyle(left).gridTemplateRows, rightRows: getComputedStyle(right).gridTemplateRows,
    leftKids: kids(left), rightKids: kids(right) };
})()
