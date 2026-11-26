import { GameState } from './GameState';
import { BaseTransport, UdpTransport, TcpTransport, StatusFn, RumbleFn } from './Transport';
import { UDP_PORT } from './Protocol';
import { rumble, rumbleTotal } from './Rumble';

/** 两条路：Wi-Fi 走 UDP；USB 走 hdc 隧道（电脑先 `hdc rport tcp:27042 tcp:27042`，手机连 127.0.0.1 的 TCP） */
export const LINK_WIFI: number = 0;
export const LINK_HDC: number = 1;

/** "已连接"的判据是电脑真的回复过（pong / XACK），不是 socket 连上了：10 秒没回复就算没连上 */
export const PONG_MAX_AGE_SEC: number = 10;
/** 没连上就每隔 4 秒再试一次（只在第一屏） */
export const RETRY_INTERVAL_MS: number = 4000;

/**
 * 全局共享的手柄状态与连接：第一屏负责连接与参数，手柄屏只负责按键。
 * 两个界面用同一份状态，切屏不会断连接。
 */
export class Controller {
  state: GameState = new GameState();

  link: number = LINK_WIFI;
  port: number = UDP_PORT;
  /** 紧凑包开关（默认 true，走偏好 compact） */
  compact: boolean = true;

  /** 改了开关要马上作用到正在用的通道（不然要重连才生效） */
  setCompact(on: boolean): void {
    this.compact = on;
    const t = this.transport;
    if (t !== null) {
      t.compact = on;
    }
  }

  packetsSent: number = 0;
  lastStatus: string = '未连接';
  lastRumble: number = 0;
  transport: BaseTransport | null = null;

  /**
   * 用户在第一屏点「断开」就置 false：自动重连循环不再自己连回来（点「连接」或扫码连会恢复 true）。
   * 被动断线（电脑客户端重启、网断了、10 秒没回复）不受影响：那时还是 true，会自己连回来。
   */
  autoConnect: boolean = true;

  onStatus: StatusFn = (msg: string): void => {
    this.lastStatus = msg;
  };

  onRumble: RumbleFn = (left: number, right: number): void => {
    this.lastRumble = left + right;
    rumble(left, right);
  };

  /** 界面刷新回调（页面挂上来） */
  notifyUi: () => void = (): void => {};

  private eventCount: number = 0;

  modeName(): string {
    return this.link === LINK_HDC ? 'hdc（USB）' : 'Wi-Fi';
  }

  /** 收到过多少次震动包（>0 就是电脑端确实回传到手机了） */
  rumbleCount(): number {
    return rumbleTotal();
  }

  /** 控件状态变化 → 发一次报告；UI 每 8 次事件刷新一次，避免刷屏 */
  send(): void {
    const t = this.transport;
    if (t === null) {
      this.lastStatus = '发送失败（未连接）';
      return;
    }
    t.send(this.state);
    this.packetsSent++;
    this.eventCount++;
    if (this.eventCount % 8 === 0) {
      this.notifyUi();
    }
  }

  /** 电脑真回复过才算连上 */
  alive(): boolean {
    const t = this.transport;
    if (t === null || !t.isConnected) {
      return false;
    }
    if (t.lastPongAt === 0) {
      return false;
    }
    return (Date.now() - t.lastPongAt) / 1000 <= PONG_MAX_AGE_SEC;
  }

  async connect(host: string, port: number, mode: number): Promise<boolean> {
    this.disconnect();
    if (host === '') {
      this.lastStatus = '请输入电脑 IP（Wi-Fi 填电脑 IP；走 hdc 就填 127.0.0.1）';
      return false;
    }
    this.link = mode;
    this.port = port;
    const t: BaseTransport = mode === LINK_HDC
      ? new TcpTransport(this.state, this.onStatus, this.onRumble, port)
      : new UdpTransport(this.state, this.onStatus, this.onRumble, port);
    t.compact = this.compact;
    this.transport = t;
    return await t.start(host);
  }

  disconnect(): void {
    const t = this.transport;
    if (t !== null) {
      t.stop();
    }
    this.transport = null;
    this.notifyUi();
  }
}

/** 全局共享的手柄（第一屏、手柄屏、扫码页都用这一个） */
export const controller = new Controller();
