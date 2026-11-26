/**
 * 手柄字段定义 —— 和安卓端、电脑端必须完全一致（pc-receiver/client.py、receiver.py）。
 * 一个字节都不能改：20 字节紧凑包、JSON 字段名、XACK、2 字节大端长度、端口 27042。
 */

export const UDP_PORT: number = 27042;
export const PING_INTERVAL_MS: number = 1000;
export const QR_SCHEME: string = 'xpad://';

/** 二维码内容：电脑客户端画的是 xpad://<电脑 IP>:<端口> */
export class QrTarget {
  host: string;
  port: number;

  constructor(host: string, port: number) {
    this.host = host;
    this.port = port;
  }
}

/**
 * 解析扫到的内容：`xpad://ip:port`、`ip:port`、裸 `ip` 都认。
 * 端口没写就用 UDP_PORT。认不出地址返回 null。
 */
export function parseQr(text: string): QrTarget | null {
  let body = text.trim();
  if (body.startsWith(QR_SCHEME)) {
    body = body.substring(QR_SCHEME.length);
  }
  const schemeEnd = body.indexOf('://');
  if (schemeEnd >= 0) {
    body = body.substring(schemeEnd + 3);
  }
  const cut = body.split('/');
  body = cut[0];
  body = body.split('?')[0];
  body = body.split('#')[0];
  body = body.split(' ')[0];
  body = body.split('\n')[0];
  const host = body.split(':')[0].trim();
  if (!new RegExp('[0-9A-Za-z.\\-_]{2,64}').test(host)) {
    return null;
  }
  const rest = body.split(':')[1];
  let port = UDP_PORT;
  if (rest !== undefined && rest.length > 0) {
    const p = Number.parseInt(rest, 10);
    if (!Number.isNaN(p)) {
      port = Math.min(Math.max(p, 1), 65535);
    }
  }
  return new QrTarget(host, port);
}

// ---- 按钮位（bit 序号，从 bit0 开始）----
export const BTN_A = 0;
export const BTN_B = 1;
export const BTN_X = 2;
export const BTN_Y = 3;
export const BTN_LB = 4;
export const BTN_RB = 5;
export const BTN_BACK = 6;
export const BTN_START = 7;
export const BTN_GUIDE = 8;
export const BTN_L3 = 9;
export const BTN_R3 = 10;

// ---- 十字键（HID hat switch 取值）----
export const HAT_N = 0;
export const HAT_NE = 1;
export const HAT_E = 2;
export const HAT_SE = 3;
export const HAT_S = 4;
export const HAT_SW = 5;
export const HAT_W = 6;
export const HAT_NW = 7;
export const HAT_NEUTRAL = 8;

export const REPORT_ID_INPUT = 1;
export const REPORT_ID_RUMBLE = 2;

export const BIT_NAMES: string[] = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'BACK', 'START', 'GUIDE', 'L3', 'R3'];
export const HAT_NAMES: string[] = ['上', '右上', '右', '右下', '下', '左下', '左', '左上', '中立'];
