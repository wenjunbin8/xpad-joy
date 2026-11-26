import { BIT_NAMES, HAT_NAMES, HAT_NEUTRAL } from './Protocol';

/**
 * 手柄当前状态。所有触控区共用同一个实例，任何变化都会触发一次上报。
 */
export class GameState {
  buttons: number = 0;
  hat: number = HAT_NEUTRAL;
  lx: number = 0;
  ly: number = 0;
  rx: number = 0;
  ry: number = 0;
  lt: number = 0;
  rt: number = 0;
  /** 最后一次 ping→pong 的往返延迟（毫秒），只用于 JSON */
  rtt: number = -1;
  /** 输入路径往返：手机发 state → 电脑回 ack 的时间（毫秒），只用于 JSON */
  stateRtt: number = -1;
  /** 发这个 state 包的时刻（毫秒），电脑收到后原样回传 */
  ts: number = 0;

  setBit(bit: number, on: boolean): void {
    if (bit < 0 || bit > 15) {
      return;
    }
    this.buttons = on ? (this.buttons | (1 << bit)) : (this.buttons & ~(1 << bit));
  }

  applyHat(value: number): void {
    this.hat = Math.min(Math.max(value, 0), 8);
  }

  setStick(left: boolean, x: number, y: number): void {
    const cx = Math.min(Math.max(x, -128), 127);
    const cy = Math.min(Math.max(y, -128), 127);
    if (left) {
      this.lx = cx;
      this.ly = cy;
    } else {
      this.rx = cx;
      this.ry = cy;
    }
  }

  setTrigger(left: boolean, value: number): void {
    const v = Math.min(Math.max(value, 0), 255);
    if (left) {
      this.lt = v;
    } else {
      this.rt = v;
    }
  }

  /**
   * 紧凑包（20 字节，UDP 用）：
   * 0 'X' | 1-2 buttons(大端) | 3 hat | 4-7 lx,ly,rx,ry | 8-9 lt,rt | 10-17 ts(大端) | 18-19 srtt(大端, 0xFFFF=没测到)
   */
  toCompact(): ArrayBuffer {
    const out = new Uint8Array(20);
    out[0] = 0x58; // 'X'
    const b = this.buttons & 0xFFFF;
    out[1] = (b >> 8) & 0xFF;
    out[2] = b & 0xFF;
    out[3] = this.hat & 0xFF;
    out[4] = this.lx & 0xFF;
    out[5] = this.ly & 0xFF;
    out[6] = this.rx & 0xFF;
    out[7] = this.ry & 0xFF;
    out[8] = this.lt & 0xFF;
    out[9] = this.rt & 0xFF;
    const t = this.ts;
    for (let i = 0; i < 8; i++) {
      out[10 + i] = Math.floor(t / Math.pow(2, 56 - 8 * i)) % 256;
    }
    const s = this.stateRtt < 0 ? 0xFFFF : (this.stateRtt & 0xFFFF);
    out[18] = (s >> 8) & 0xFF;
    out[19] = s & 0xFF;
    return out.buffer as ArrayBuffer;
  }

  /** JSON（和 pc-receiver 一致） */
  toJson(): string {
    let s = '{"t":"state","buttons":' + (this.buttons & 0x7FF);
    s += ',"hat":' + this.hat;
    s += ',"lx":' + this.lx;
    s += ',"ly":' + this.ly;
    s += ',"rx":' + this.rx;
    s += ',"ry":' + this.ry;
    s += ',"lt":' + this.lt;
    s += ',"rt":' + this.rt;
    if (this.rtt >= 0) {
      s += ',"rtt":' + this.rtt;
    }
    if (this.stateRtt >= 0) {
      s += ',"srtt":' + this.stateRtt;
    }
    if (this.ts > 0) {
      s += ',"ts":' + this.ts;
    }
    return s + '}';
  }

  /** 用于界面上的状态展示 */
  describe(): string {
    const pressed: string[] = [];
    for (let i = 0; i <= 10; i++) {
      if (((this.buttons >> i) & 1) === 1) {
        pressed.push(BIT_NAMES[i]);
      }
    }
    const pct = (v: number): string => Math.round(v * 100 / 127).toString();
    return '按键: ' + (pressed.length === 0 ? '—' : pressed.join('/')) + '\n' +
      '十字键: ' + HAT_NAMES[this.hat] + '\n' +
      '左摇杆: ' + pct(this.lx) + ',' + pct(this.ly) + '   右摇杆: ' + pct(this.rx) + ',' + pct(this.ry) + '\n' +
      '扳机: LT ' + Math.round(this.lt * 100 / 255) + '%  RT ' + Math.round(this.rt * 100 / 255) + '%';
  }
}
