# 前端第三方库（本地化）

校园网/内网环境常出现 `cdn.jsdelivr.net` 连接被重置，导致图表与地图在页面上静默失效。
这里把运行时依赖固化到仓库，`templates/index.html` 只引用本地文件，页面不再依赖外网 CDN。

| 文件 | 版本 | 来源 | 用途 | 许可证 |
| --- | --- | --- | --- | --- |
| `socket.io.min.js` | 4.7.1 | https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.1/socket.io.min.js | 浏览器与服务端 Socket.IO 长连接（实时读数/告警/日志） | MIT |
| `chart.umd.min.js` | 4.4.1 | https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js | 实时趋势折线/柱状图 | MIT |
| `leaflet/leaflet.js`、`leaflet/leaflet.css`、`leaflet/images/*` | 1.9.4 | https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/ | 系统设置里的地图选点 / 圈地 | BSD-2-Clause |

说明：

- 三个库均从 cdnjs 原样下载，未做代码改动；升级时同步替换并更新本表。
- `leaflet.css` 里的 `url(images/...)` 依赖同目录 `images/`，移动文件时两者必须一起移动。
- 地图瓦片仍来自高德（`webst0{s}.is.autonavi.com`），由 CSP `img-src ... https:` 放行；
  瓦片不可达时前端降级为手填经纬度，不影响保存地块。
