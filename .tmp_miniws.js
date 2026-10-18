const net = require('net');
const crypto = require('crypto');
class MiniWS {
    constructor(url) {
        const m = url.match(/^ws:\/\/([^:/]+):(\d+)(\/.*)$/);
        this.host = m[1]; this.port = +m[2]; this.path = m[3];
        this.buf = Buffer.alloc(0);
        this.handlers = { message: [], open: [] };
        this.sock = net.connect(this.port, this.host, () => {
            const key = crypto.randomBytes(16).toString('base64');
            this.sock.write('GET ' + this.path + ' HTTP/1.1\r\nHost: ' + this.host + ':' + this.port +
                '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key +
                '\r\nSec-WebSocket-Version: 13\r\n\r\n');
        });
        this.sock.on('data', (d) => this._onData(d));
        this.sock.on('error', () => {});
    }
    on(ev, fn) { this.handlers[ev].push(fn); return this; }
    _onData(d) {
        this.buf = Buffer.concat([this.buf, d]);
        if (!this.upgraded) {
            const i = this.buf.indexOf('\r\n\r\n');
            if (i < 0) return;
            this.upgraded = true; this.buf = this.buf.slice(i + 4);
            this.handlers.open.forEach((f) => f());
        }
        while (this.buf.length >= 2) {
            const b0 = this.buf[0], b1 = this.buf[1];
            let len = b1 & 0x7f, off = 2;
            if (len === 126) { if (this.buf.length < 4) return; len = this.buf.readUInt16BE(2); off = 4; }
            else if (len === 127) { if (this.buf.length < 10) return; len = Number(this.buf.readBigUInt64BE(2)); off = 10; }
            if (this.buf.length < off + len) return;
            const payload = this.buf.slice(off, off + len);
            this.buf = this.buf.slice(off + len);
            if ((b0 & 0x0f) === 1) this.handlers.message.forEach((f) => f(payload.toString('utf8')));
        }
    }
    send(str) {
        const data = Buffer.from(str, 'utf8');
        const mask = crypto.randomBytes(4);
        let head;
        if (data.length < 126) head = Buffer.from([0x81, 0x80 | data.length]);
        else if (data.length < 65536) { head = Buffer.alloc(4); head[0] = 0x81; head[1] = 0xfe; head.writeUInt16BE(data.length, 2); }
        else { head = Buffer.alloc(10); head[0] = 0x81; head[1] = 0xff; head.writeBigUInt64BE(BigInt(data.length), 2); }
        const masked = Buffer.alloc(data.length);
        for (let i = 0; i < data.length; i++) masked[i] = data[i] ^ mask[i % 4];
        this.sock.write(Buffer.concat([head, mask, masked]));
    }
    close() { try { this.sock.destroy(); } catch (e) {} }
}
module.exports = { MiniWS };
