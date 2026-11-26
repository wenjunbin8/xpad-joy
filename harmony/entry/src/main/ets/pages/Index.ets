import { promptAction, router, window, display } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { controller, LINK_WIFI, LINK_HDC, RETRY_INTERVAL_MS } from '../common/Controller';
import { layout } from '../common/LayoutConfig';
import { UDP_PORT } from '../common/Protocol';
import { openPrefs, getStr, getNum, getBool, put } from '../common/Prefs';
import { BG, CARD, PANEL, ACCENT, LINE, INK, DIM } from '../common/Palette';
import { applyOrientation } from '../common/AppCtx';

/** 体感幅度：转多少度 = 摇杆满量程，和安卓端同一批限制 */
const MIN_DEG: number = 3;
const MAX_DEG: number = 90;
const DEFAULT_DEG: number = 8;

/**
 * 第一屏：连接状态（只显示已连接 / 未连接）、走哪条路（hdc（USB） / Wi-Fi）、手输电脑 IP、
 * 扫码连接入口、当前布局的状态图、体感开关和幅度滑条、跳转布局页。
 */
@Entry
@Component
struct Index {
  private ctx: CanvasRenderingContext2D = new CanvasRenderingContext2D(new RenderingContextSettings(true));

  @State connected: boolean = false;
  @State ip: string = '';
  @State link: number = LINK_WIFI;
  @State port: number = UDP_PORT;
  @State gyroOn: boolean = false;
  @State gyroRange: number = DEFAULT_DEG;
  @State compact: boolean = true;
  @State desc: string = '';
  @State hint: string = '';
  @State cw: number = 0;
  @State ch: number = 0;

  private retryBusy: boolean = false;
  private retryTimer: number = -1;
  private renderTimer: number = -1;

  aboutToAppear(): void {
    controller.notifyUi = (): void => {
      this.render();
    };
    this.init();
  }

  /** 从手柄屏/布局页退回来时重新挂上刷新回调（aboutToAppear 只在第一次创建时跑） */
  onPageShow(): void {
    controller.notifyUi = (): void => {
      this.render();
    };
    this.initWindow();
    this.startRetryTimer();   // 从手柄页退回来时这里原来没把它重新跑起来
    this.render();
  }

  /** 转屏要用 EntryAbility 存的 ability context（页面里那个 host context 真机上会失败） */
  private async initWindow(): Promise<void> {
    const err = await applyOrientation(window.Orientation.PORTRAIT);
    if (err !== '') {
      console.warn('设置方向失败：' + err);
      this.say('竖屏没设置成功：' + err);
    }
  }

  aboutToDisappear(): void {
    if (this.renderTimer >= 0) {
      clearInterval(this.renderTimer);
      this.renderTimer = -1;
    }
    if (this.retryTimer >= 0) {
      clearInterval(this.retryTimer);
      this.retryTimer = -1;
    }
  }

  private async init(): Promise<void> {
    const host = this.getUIContext().getHostContext();
    if (host === undefined) {
      return;
    }
    await this.initWindow();

    const p = await openPrefs(host);
    this.ip = await getStr(p, 'pc_ip', '');
    this.link = controller.link = await getNum(p, 'link', LINK_WIFI);
    this.port = controller.port = await getNum(p, 'pc_port', UDP_PORT);
    this.gyroOn = await getBool(p, 'gyro', false);
    this.gyroRange = clampDeg(await getNum(p, 'gyro_range', DEFAULT_DEG));
    this.compact = controller.compact = await getBool(p, 'compact', true);
    this.hint = '电脑上要跑 hdc rport tcp:' + this.port + ' tcp:' + this.port +
      '（方向跟 adb reverse 一致）';

    this.render();
    // 每 3 秒刷一次：不然"电脑没回复"这种状态只有等下一次 pong 才会变
    this.renderTimer = setInterval((): void => {
      this.render();
    }, 3000);
    this.startRetryTimer();
    setTimeout((): void => {
      this.tryRetry();
    }, 200);
  }

  // ---------------- 连接 ----------------

  /** 走 hdc 时 target 一律 127.0.0.1，输入框里的 IP 只给 Wi-Fi 用 */
  private currentTarget(): string {
    if (controller.link === LINK_HDC) {
      return '127.0.0.1';
    }
    const ip = this.ip.trim();
    if (ip === '') {
      this.say('填入电脑 IP（Wi-Fi 用同一网段的 IP）');
      return '';
    }
    this.savePrefs('pc_ip', ip);
    return ip;
  }

  /** 重连目标：走 hdc 只能 127.0.0.1；走 Wi-Fi 用存着的 pc_ip（空的就不自动连） */
  private retryTarget(): string {
    return controller.link === LINK_HDC ? '127.0.0.1' : this.ip.trim();
  }

  private startRetryTimer(): void {
    if (this.retryTimer >= 0) {
      return;
    }
    // 没连上就每隔 4 秒再试一次（只在第一屏）
    this.retryTimer = setInterval((): void => {
      this.tryRetry();
    }, RETRY_INTERVAL_MS);
  }

  private stopRetryTimer(): void {
    if (this.retryTimer >= 0) {
      clearInterval(this.retryTimer);
      this.retryTimer = -1;
    }
  }

  private async tapConnect(): Promise<void> {
    if (this.connected) {
      controller.disconnect();
      // 用户主动断开：自动重连关掉，并把排着的重连撤掉（不然过几秒那个 4 秒循环又把它连回来）
      controller.autoConnect = false;
      this.stopRetryTimer();
      this.say('已断开：自动重连已关闭（点「连接」或扫码会恢复）');
      this.render();
      return;
    }
    const target = this.currentTarget();
    if (target === '') {
      return;
    }
    controller.autoConnect = true;
    const ok = await controller.connect(target, controller.port, controller.link);
    if (!ok) {
      if (controller.link === LINK_HDC) {
        this.say('连不上 127.0.0.1:' + controller.port +
          '：电脑上客户端要开着，而且先跑 hdc rport tcp:' + controller.port + ' tcp:' + controller.port);
      } else {
        this.say('连不上 ' + target + ':' + controller.port + '：' + controller.lastStatus);
      }
    } else if (controller.link === LINK_WIFI) {
      // UDP 没有握手，连上不等于电脑收到了包：过一会儿再刷新一次状态
      setTimeout((): void => {
        this.render();
      }, 6000);
    }
    this.startRetryTimer();
    this.render();
  }

  private async tryRetry(): Promise<void> {
    if (!controller.autoConnect || controller.alive() || this.retryBusy) {
      return;
    }
    const target = this.retryTarget();
    if (target === '') {
      return;
    }
    this.retryBusy = true;
    const ok = await controller.connect(target, controller.port, controller.link);
    this.retryBusy = false;
    if (ok) {
      console.info('自动重连成功（' + controller.modeName() + ' → ' + target + '）');
    } else {
      console.warn('自动重连失败（' + controller.modeName() + ' → ' + target + '）：' + controller.lastStatus);
    }
    this.render();
  }

  private setLink(newLink: number): void {
    controller.link = newLink;
    this.link = newLink;
    this.savePrefs('link', newLink);
    this.render();
    this.tryRetry();
  }

  private toggleGyro(): void {
    const on = !this.gyroOn;
    this.gyroOn = on;
    this.savePrefs('gyro', on);
    this.say(on
      ? '体感已开：手柄屏里左右转动 = 左摇杆 X（Y 保持 0），回正用手柄屏那个「回正」键'
      : '体感已关：左摇杆回到手搓');
    this.render();
  }

  private savePrefs(key: string, value: string | number | boolean): void {
    const host = this.getUIContext().getHostContext();
    if (host === undefined) {
      return;
    }
    openPrefs(host).then((p) => {
      put(p, key, value).then(() => {
      }).catch((e: Error) => {
        console.warn('存偏好失败 ' + key + '：' + e.message);
      });
    }).catch((e: Error) => {
      console.warn('打开偏好失败：' + e.message);
    });
  }

  // ---------------- 界面刷新 ----------------

  /** 状态行：只有「已连接」和「未连接」两个状态（判据是电脑真的回复过 pong / XACK） */
  private render(): void {
    this.connected = controller.alive();
    this.desc = controller.state.describe();
    this.drawPreview();
  }

  private say(message: string): void {
    promptAction.showToast({ message: message });
  }

  /**
   * 胶囊按钮全部改成写在 build() 里的 Button（不再用 @Builder 传参数）：
   * 模拟器上实测 —— 带参数的 @Builder 里的 Button 点了没反应（同页面其它 Button 正常），
   * 参数直接写在按钮里就有反应。
   */

  // ---------------- 当前布局的状态图 ----------------

  private drawPreview(): void {
    const w = this.cw;
    const h = this.ch;
    if (w <= 0 || h <= 0) {
      return;
    }
    const c = this.ctx;
    c.clearRect(0, 0, w, h);

    // 按手柄（横屏）的实际比例等比缩放，居中：之前直接把归一化坐标映射到卡片尺寸（竖屏比例），
    // 所以按键全部叠在一起。
    let longPx = 1;
    let shortPx = 1;
    try {
      const d = display.getDefaultDisplaySync();
      longPx = Math.max(d.width, d.height);
      shortPx = Math.min(d.width, d.height);
    } catch (e) {
      longPx = 2400;
      shortPx = 1080;
    }
    const longVp = px2vp(longPx);
    const shortVp = px2vp(shortPx);
    const scale = Math.min(w / longVp, h / shortVp);
    if (scale <= 0) {
      return;
    }
    const drawW = longVp * scale;
    const drawH = shortVp * scale;
    const ox = (w - drawW) / 2;
    const oy = (h - drawH) / 2;

    c.strokeStyle = LINE;
    c.lineWidth = 1.5;
    c.strokeRect(ox, oy, drawW, drawH);

    for (const g of layout.groups) {
      const side = g.side * scale;
      const cx = ox + g.cx * drawW;
      const cy = oy + g.cy * drawH;
      const corner = Math.min(6, side / 6);
      c.beginPath();
      c.setLineDash([8, 6]);
      c.strokeStyle = ACCENT;
      c.lineWidth = 1.5;
      c.roundRect(cx - side / 2, cy - side / 2, side, side, corner);
      c.stroke();
      c.setLineDash([]);
    }

    c.textAlign = 'center';
    c.textBaseline = 'middle';
    for (const s of layout.slots) {
      const pw = s.w * scale;
      const ph = s.h * scale;
      const cx = ox + s.cx * drawW;
      const cy = oy + s.cy * drawH;
      const corner = Math.min(pw, ph) / 2;
      c.fillStyle = PANEL;
      c.strokeStyle = LINE;
      c.lineWidth = 1.5;
      if (s.canRotate && s.angle !== 0) {
        c.save();
        c.translate(cx, cy);
        c.rotate(s.angle * Math.PI / 180);
        c.beginPath();
        c.roundRect(-pw / 2, -ph / 2, pw, ph, corner);
        c.fill();
        c.stroke();
        // 按到底那一头
        c.beginPath();
        c.setLineDash([]);
        c.strokeStyle = ACCENT;
        c.lineWidth = 1.5;
        c.moveTo(0, 0);
        c.lineTo(0, ph / 2 - corner / 2);
        c.stroke();
        c.restore();
      } else {
        c.beginPath();
        c.roundRect(cx - pw / 2, cy - ph / 2, pw, ph, corner);
        c.fill();
        c.stroke();
      }

      const size = Math.min(14, Math.min(pw, ph) * 0.34);
      if (size < 6) {
        continue;   // 太小就不写字，避免糊
      }
      c.font = size.toFixed(1) + 'vp sans-serif';
      c.fillStyle = INK;
      c.fillText(s.name, cx, cy);
    }
  }

  build() {
    Column({ space: 12 }) {
      Text('Xpad-joy')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor(INK)

      Row({ space: 10 }) {
        Text(this.connected ? '已连接' : '未连接')
          .fontSize(16)
          .fontColor(this.connected ? ACCENT : DIM)
        Blank()
        Button(this.connected ? '断开' : '连接')
          .fontSize(15)
          .backgroundColor(ACCENT)
          .fontColor('#FFFFFF')
          .onClick((): void => {
            this.tapConnect();
          })
      }
      .width('100%')

      Text('电脑上要跑 hdc rport tcp:' + this.port + ' tcp:' + this.port + '（方向跟 adb reverse 一致）')
        .fontSize(13)
        .fontColor(DIM)

      Row({ space: 8 }) {
        Text('链路：')
          .fontSize(14)
          .fontColor(DIM)
        Button('hdc（USB）')
          .fontSize(14)
          .fontColor(this.link === LINK_HDC ? '#FFFFFF' : INK)
          .backgroundColor(this.link === LINK_HDC ? ACCENT : PANEL)
          .borderRadius(8)
          .border({ width: 1, color: this.link === LINK_HDC ? ACCENT : LINE })
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .onClick((): void => {
            this.setLink(LINK_HDC);
          })
        Button('Wi-Fi')
          .fontSize(14)
          .fontColor(this.link === LINK_WIFI ? '#FFFFFF' : INK)
          .backgroundColor(this.link === LINK_WIFI ? ACCENT : PANEL)
          .borderRadius(8)
          .border({ width: 1, color: this.link === LINK_WIFI ? ACCENT : LINE })
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .onClick((): void => {
            this.setLink(LINK_WIFI);
          })
      }
      .width('100%')

      Row({ space: 8 }) {
        TextInput({ text: this.ip, placeholder: '电脑 IP（Wi-Fi）/ 127.0.0.1（走 hdc）' })
          .layoutWeight(1)
          .backgroundColor(CARD)
          .fontColor(INK)
          .placeholderColor(DIM)
          .onChange((value: string): void => {
            this.ip = value;
          })
        Button('扫码连接')
          .fontSize(14)
          .backgroundColor(PANEL)
          .fontColor(INK)
          .onClick((): void => {
            router.pushUrl({ url: 'pages/QrScan' });
          })
      }
      .width('100%')

      Text('当前布局的状态图')
        .fontSize(14)
        .fontColor(DIM)

      Canvas(this.ctx)
        .width('100%')
        .height(180)
        .backgroundColor(CARD)
        .onReady((): void => {
          this.drawPreview();
        })
        .onAreaChange((oldValue: Area, newValue: Area): void => {
          if (typeof newValue.width === 'number') {
            this.cw = newValue.width;
          }
          if (typeof newValue.height === 'number') {
            this.ch = newValue.height;
          }
          this.drawPreview();
        })

      Text(this.desc)
        .fontSize(13)
        .fontColor(INK)

      Row({ space: 8 }) {
        Button('进入手柄')
          .fontSize(14)
          .backgroundColor(ACCENT)
          .fontColor('#FFFFFF')
          .onClick((): void => {
            router.pushUrl({ url: 'pages/Gamepad' });
          })
        Button('调整布局')
          .fontSize(14)
          .backgroundColor(PANEL)
          .fontColor(INK)
          .onClick((): void => {
            router.pushUrl({ url: 'pages/LayoutEditor' });
          })
      }
      .width('100%')

      Text('排布按参考图；双击摇杆 = L3/R3（再双击取消）')
        .fontSize(12)
        .fontColor(DIM)

      Row({ space: 8 }) {
        Button('体感→左摇杆')
          .fontSize(14)
          .fontColor(this.gyroOn ? '#FFFFFF' : INK)
          .backgroundColor(this.gyroOn ? ACCENT : PANEL)
          .borderRadius(8)
          .border({ width: 1, color: this.gyroOn ? ACCENT : LINE })
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .onClick((): void => {
            this.toggleGyro();
          })
        Text('体感幅度 ' + this.gyroRange + '°')
          .fontSize(13)
          .fontColor(INK)
      }
      .width('100%')

      Slider({
        value: this.gyroRange,
        min: MIN_DEG,
        max: MAX_DEG,
        step: 1
      })
        .selectedColor(ACCENT)
        .blockColor(INK)
        .onChange((value: number): void => {
          const deg = clampDeg(value);
          if (deg !== this.gyroRange) {
            this.gyroRange = deg;
            this.savePrefs('gyro_range', deg);
          }
        })

      Row({ space: 8 }) {
        Button('紧凑包（20 字节）')
          .fontSize(14)
          .fontColor(this.compact ? '#FFFFFF' : INK)
          .backgroundColor(this.compact ? ACCENT : PANEL)
          .borderRadius(8)
          .border({ width: 1, color: this.compact ? ACCENT : LINE })
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .onClick((): void => {
            this.compact = !this.compact;
            controller.setCompact(this.compact);
            this.savePrefs('compact', this.compact);
            this.say(this.compact ? '已切到紧凑包（20 字节）' : '已切到 JSON');
          })
      }
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .padding(16)
    .backgroundColor(BG)
  }
}

function clampDeg(value: number): number {
  return Math.min(Math.max(Math.round(value), MIN_DEG), MAX_DEG);
}

// 原来这里是个带函数参数的全局 @Builder（pill(label, on, onTap)）：真机上点了没反应，
// 已经改成 struct 里的 pillItem + pillTap（见上面），不再用函数参数。
