import { socket } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { GameState } from './GameState';
import { PING_INTERVAL_MS } from './Protocol';

export type StatusFn = (msg: string) => void;
export type RumbleFn = (left: number, right: number) => void;

const ENCODER = new util.TextEncoder();
const DECODER = util.TextDecoder.create('utf-8');

/** 从 JSON 里取一个字段（自己写的极简取值，不用 JSON.parse 的类型转换） */
function jsonField(text: string, key: string): string {
  const k = '"' + key + '"';
  const at = text.indexOf(k);
  if (at < 0) {
    return '';
  }
  const colon = text.indexOf(':', at + k.length);
  if (colon < 0) {
    return '';
  }
  let i = colon + 1;
  while (i < text.length && (text[i] === ' ' || text[i] === '"')) {
    i++;
  }
  let end = i;
  while (end < text.length && text[end] !== ',' && text[end] !== '}' && text[end] !== '"') {
    end++;
  }
  return text.substring(i, end);
}

/**
 * 两条路共用的部分：拼包、只留最新一帧、每秒一次 ping、解析电脑端的回复。
 * 子类只写"怎么送出去"：UDP 一个数据报一个包；TCP（hdc 隧道）2 字节大端长度 + 原始包字节。
 */
export abstract class BaseTransport {
  protected state: GameState;
  protected onStatus: StatusFn;
  protected onRumble: RumbleFn;
  readonly port: number;

  protected connectedFlag = false;
  protected lastError = '';
  protected host = '';
  private pongAt = 0;
  private lastPingAt = 0;
  private pending: ArrayBuffer | null = null;
  private pumping = false;
  /** 连上之后每秒 ping 一次（安卓端的发送线程是常驻的，不点也会 ping；这里用定时器补上） */
  private pingTimer: number = -1;
  compact = true;

  constructor(state: GameState, onStatus: StatusFn, onRumble: RumbleFn, port: number) {
    this.state = state;
    this.onStatus = onStatus;
    this.onRumble = onRumble;
    this.port = port;
  }

  /** 界面显示的路名（Wi-Fi UDP / hdc 隧道） */
  abstract channelName(): string;

  protected abstract open(target: string): Promise<boolean>;
  protected abstract write(data: ArrayBuffer): Promise<boolean>;
  protected abstract closeTransport(): void;

  get isConnected(): boolean {
    return this.connectedFlag;
  }

  get target(): string {
    return this.host;
  }

  get lastPongAt(): number {
    return this.pongAt;
  }

  get lastRtt(): number {
    return this.state.rtt;
  }

  statusLine(): string {
    return this.channelName() + ' → ' + this.host + ':' + this.port;
  }

  markDisconnected(reason: string): void {
    if (!this.connectedFlag) {
      return;
    }
    this.connectedFlag = false;
    this.stopPingTimer();
    this.lastError = reason;
    this.onStatus(reason);
  }

  async start(target: string): Promise<boolean> {
    this.stop();
    if (target.length === 0) {
      this.onStatus('请输入电脑 IP（Wi-Fi 填电脑 IP；走 hdc 隧道就填 127.0.0.1）');
      return false;
    }
    this.host = target;
    this.connectedFlag = true;
    this.lastError = '';
    this.lastPingAt = 0;
    this.pongAt = 0;
    this.pending = null;
    this.state.rtt = -1;
    this.state.stateRtt = -1;
    const ok = await this.open(target);
    if (!ok) {
      this.connectedFlag = false;
      return false;
    }
    this.onStatus(this.statusLine() + '（已连上）');
    // 连上就马上 ping 一次：不然用户不按任何东西就没有包发出去，状态行会一直停在「未连接」
    this.maybePing();
    this.startPingTimer();
    return true;
  }

  private startPingTimer(): void {
    this.stopPingTimer();
    this.pingTimer = setInterval((): void => {
      this.maybePing();
    }, PING_INTERVAL_MS);
  }

  private stopPingTimer(): void {
    if (this.pingTimer >= 0) {
      clearInterval(this.pingTimer);
      this.pingTimer = -1;
    }
  }

  stop(): void {
    this.stopPingTimer();
    this.closeTransport();
    this.pending = null;
    this.connectedFlag = false;
  }

  send(gamepad: GameState): void {
    if (!this.connectedFlag) {
      return;
    }
    gamepad.ts = Date.now();
    const data = this.compact ? gamepad.toCompact() : ENCODER.encodeInto(gamepad.toJson()).buffer as ArrayBuffer;
    this.deliver(data);
    this.lastError = '';
    this.maybePing();
  }

  /** 只留最新一帧：输入数据旧包没意义，不能被排后面的旧包堵住 */
  private deliver(data: ArrayBuffer): void {
    this.pending = data;
    if (!this.pumping) {
      this.pump();
    }
  }

  private async pump(): Promise<void> {
    this.pumping = true;
    try {
      while (this.pending !== null && this.connectedFlag) {
        const data = this.pending;
        this.pending = null;
        const ok = await this.write(data);
        if (!ok) {
          break;
        }
      }
    } catch (e) {
      // 发送中途出错也不能把泵卡住：泵卡住之后 deliver() 的包永远不会发出去（"再点连接就连不上"就是这个）
      this.markDisconnected('发送中断：' + (e as Error).message);
    } finally {
      this.pumping = false;
    }
  }

  /** 每秒一次 ping：电脑回 pong 就是"包真能进电脑"的证据，RTT 也是这么测的 */
  private maybePing(): void {
    if (!this.connectedFlag) {
      return;
    }
    const now = Date.now();
    if (now - this.lastPingAt < PING_INTERVAL_MS) {
      return;
    }
    this.lastPingAt = now;
    this.deliver(ENCODER.encodeInto('{"t":"ping","ts":' + now + '}').buffer as ArrayBuffer);
  }

  protected onPacket(data: Uint8Array): void {
    if (data.length >= 12 && data[0] === 0x58 && data[1] === 0x41 && data[2] === 0x43 && data[3] === 0x4B) {
      let t = 0;
      for (let i = 0; i < 8; i++) {
        t = t * 256 + (data[4 + i] & 0xFF);
      }
      if (t > 0) {
        this.state.stateRtt = Math.max(Date.now() - t, 0);
        this.pongAt = Date.now();
        this.onStatus(this.statusLine() + '（输入路径往返 ' + this.state.stateRtt + 'ms）');
      }
      return;
    }
    const text = DECODER.decodeToString(data);
    const type = jsonField(text, 't');
    if (type === '') {
      this.lastError = '非法 JSON';
      return;
    }
    const tsText = jsonField(text, 'ts');
    const ts = tsText === '' ? 0 : Number.parseInt(tsText, 10);
    if (type === 'ack') {
      if (ts > 0) {
        this.state.stateRtt = Math.max(Date.now() - ts, 0);
        this.pongAt = Date.now();
        this.onStatus(this.statusLine() + '（输入路径往返 ' + this.state.stateRtt + 'ms）');
      }
    } else if (type === 'pong') {
      if (ts > 0) {
        this.state.rtt = Math.max(Date.now() - ts, 0);
        this.pongAt = Date.now();
        this.onStatus(this.statusLine() + '（电脑已回复，RTT ' + this.state.rtt + 'ms）');
        // 回一帧当前状态：电脑端要看到收包/延迟/按键，光有 ping 不够
        this.send(this.state);
      }
    } else if (type === 'rumble') {
      const leftText = jsonField(text, 'left');
      const rightText = jsonField(text, 'right');
      this.onRumble(leftText === '' ? 0 : Number.parseInt(leftText, 10), rightText === '' ? 0 : Number.parseInt(rightText, 10));
    }
  }
}

export class UdpTransport extends BaseTransport {
  private sock = socket.constructUDPSocketInstance();
  private bound = false;

  channelName(): string {
    return 'Wi-Fi UDP';
  }

  protected async open(target: string): Promise<boolean> {
    try {
      await this.sock.bind({ address: '0.0.0.0', port: 0, family: 1 });
      this.bound = true;
      this.sock.on('message', (info: socket.SocketMessageInfo) => {
        this.onPacket(new Uint8Array(info.message));
      });
      this.sock.on('close', () => this.markDisconnected('UDP 通道关闭'));
      this.sock.on('error', (err: Error) => this.markDisconnected('UDP 错误：' + err.message));
      return true;
    } catch (e) {
      this.onStatus('UDP 打不开：' + (e as Error).message);
      return false;
    }
  }

  protected async write(data: ArrayBuffer): Promise<boolean> {
    if (!this.bound) {
      return false;
    }
    try {
      await this.sock.send({
        data: data,
        address: { address: this.target, port: this.port, family: 1 }
      });
      return true;
    } catch (e) {
      this.markDisconnected('UDP 发送失败：' + (e as Error).message);
      return false;
    }
  }

  protected closeTransport(): void {
    if (this.bound) {
      this.bound = false;
      this.sock.close();
    }
  }
}

export class TcpTransport extends BaseTransport {
  private sock = socket.constructTCPSocketInstance();
  private opened = false;
  private buf: Uint8Array = new Uint8Array(0);

  channelName(): string {
    return 'hdc 隧道';
  }

  protected async open(target: string): Promise<boolean> {
    try {
      this.buf = new Uint8Array(0);
      this.sock.on('message', (info: socket.SocketMessageInfo) => {
        this.read(new Uint8Array(info.message));
      });
      this.sock.on('connect', () => {
        this.onStatus(this.statusLine() + '（已连上）');
      });
      this.sock.on('close', () => this.markDisconnected('TCP 通道关闭'));
      this.sock.on('error', (err: Error) => this.markDisconnected('TCP 错误：' + err.message));
      await this.sock.connect({ address: { address: target, port: this.port, family: 1 } });
      this.opened = true;
      return true;
    } catch (e) {
      this.onStatus('连不上 ' + target + ':' + this.port + '（' + (e as Error).message + '）');
      return false;
    }
  }

  /** TCP 上：2 字节大端长度 + 原始包 */
  private read(chunk: Uint8Array): void {
    const merged = new Uint8Array(this.buf.length + chunk.length);
    merged.set(this.buf, 0);
    merged.set(chunk, this.buf.length);
    this.buf = merged;
    while (this.buf.length >= 2) {
      const len = ((this.buf[0] & 0xFF) << 8) | (this.buf[1] & 0xFF);
      if (this.buf.length < len + 2) {
        break;
      }
      this.onPacket(this.buf.subarray(2, 2 + len));
      this.buf = this.buf.subarray(2 + len);
    }
  }

  protected async write(data: ArrayBuffer): Promise<boolean> {
    if (!this.opened) {
      return false;
    }
    const bytes = new Uint8Array(data);
    const framed = new Uint8Array(bytes.length + 2);
    framed[0] = (bytes.length >> 8) & 0xFF;
    framed[1] = bytes.length & 0xFF;
    framed.set(bytes, 2);
    try {
      await this.sock.send({ data: framed.buffer as ArrayBuffer });
      return true;
    } catch (e) {
      this.markDisconnected('TCP 发送失败：' + (e as Error).message);
      return false;
    }
  }

  protected closeTransport(): void {
    if (this.opened) {
      this.opened = false;
      this.sock.close();
    }
  }
}
