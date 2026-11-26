import { promptAction, router, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { controller } from '../common/Controller';
import { layout, Slot, KIND_ACTION, KIND_BAR, KIND_HAT, KIND_STICK, KIND_TRIGGER } from '../common/LayoutConfig';
import { BIT_NAMES, HAT_NEUTRAL } from '../common/Protocol';
import { gyro } from '../common/Gyro';
import { applyOrientation, hideSystemBars } from '../common/AppCtx';
import { openPrefs, getBool, getNum } from '../common/Prefs';
import { ACCENT, ARM, BG, DIM, INK, KNOB, LINE, PANEL } from '../common/Palette';

/** 和安卓端 ControlView 同一批常量（dp → vp 一比一） */
const TAP_MS: number = 250;
const DOUBLE_TAP_MS: number = 350;
/** 摇杆死区 */
const DEADZONE: number = 0.12;
/** 摇杆帽最大行程时用的判断（按下到抬起移动超过 18 就算拖动，不再当点击） */
const MOVE_THRESHOLD: number = 18;
/** 十字键中心死区 */
const HAT_DEADZONE: number = 16;
/** chevron 的方向角（度），索引 = hat 值 */
const DEGREES: number[] = [-90, -45, 0, 45, 90, 135, 180, -135];
/** chevron 两臂夹角用 140°（和安卓端 DpadView.ARM 一致） */
const ARM_ANGLE: number = 2.4435;

/** 每个槽的运行时状态（一根手指只管它按下的那个区域） */
class PadRt {
  /** 这个槽当前归哪根手指：别的手指按在同一个槽上不生效（和安卓端"一个控件只认第一个按在它上面的手指"一样） */
  owner: number = -1;
  isDown: boolean = false;
  downX: number = 0;
  downY: number = 0;
  downAt: number = 0;
  moved: boolean = false;
  dir: number = HAT_NEUTRAL;
  nx: number = 0;
  ny: number = 0;
  depth: number = 0;
  anchorY: number = 0;
  latched: boolean = false;
  lastTapAt: number = 0;
}

/**
 * 手柄屏（横屏、沉浸全屏）：用 Canvas 画整套布局（十字键、双摇杆、ABXY、LB/RB、LT/RT、
 * BACK/START/GUIDE、✕ 回正、体感条），多点触控按 TouchEvent.touches：
 * 每根手指分配它按下时所在的那个槽，手指抬起只释放它自己的槽。
 */
@Entry
@Component
struct Gamepad {
  private ctx: CanvasRenderingContext2D = new CanvasRenderingContext2D(new RenderingContextSettings(true));

  private rt: Map<string, PadRt> = new Map<string, PadRt>();
  /** 手指 id → 它按下时所在的槽 */
  private fingers: Map<number, string> = new Map<number, string>();

  private cw: number = 0;
  private ch: number = 0;

  private gyroOn: boolean = false;
  private gyroValue: number = 0;
  private gyroDeg: number = 0;
  private gyroRange: number = 8;
  private hint: string = '';
  private hintUntil: number = 0;

  aboutToAppear(): void {
    controller.notifyUi = (): void => {
      this.draw();
    };

    const host = this.getUIContext().getHostContext();
    this.initWindow();
    if (host !== undefined) {
      this.initPrefs(host);
    }

    gyro.onValue = (value: number, degrees: number): void => {
      this.gyroValue = value;
      this.gyroDeg = degrees;
      if (this.gyroOn) {
        const stick = layout.slotByName('左摇杆');
        if (stick !== null) {
          const r = this.rtOf(stick);
          controller.state.setStick(true, value, 0);
          r.nx = value / 127;
          r.ny = 0;
        }
      }
      this.draw();
    };
    gyro.onSend = (): void => {
      controller.send();
    };
  }

  onPageShow(): void {
    controller.notifyUi = (): void => {
      this.draw();
    };
    this.initWindow();
    if (this.gyroOn) {
      const err = gyro.start();
      if (err !== '') {
        this.hint = err;
      }
    }
    this.draw();
  }

  aboutToDisappear(): void {
    gyro.stop();
    this.fingers.clear();
  }

  /** 横屏 + 沉浸全屏（和安卓端 GamepadActivity 的 screenOrientation + Immersive 一样） */
  private async initWindow(): Promise<void> {
    const err = await applyOrientation(window.Orientation.LANDSCAPE);
    if (err !== '') {
      console.warn('转横屏失败：' + err);
      this.hint = '转横屏失败：' + err;
      this.draw();
    }
    const err2 = await hideSystemBars();
    if (err2 !== '') {
      console.warn('沉浸全屏失败：' + err2);
    }
  }

  private async initPrefs(host: common.Context): Promise<void> {
    try {
      const p = await openPrefs(host);
      this.gyroOn = await getBool(p, 'gyro', false);
      this.gyroRange = Math.min(Math.max(Math.round(await getNum(p, 'gyro_range', 8)), 3), 90);
      gyro.enabled = this.gyroOn;
      gyro.rangeDeg = this.gyroRange;
      this.gyroValue = 0;
      this.gyroDeg = 0;
      this.hint = this.gyroOn ? '体感 0°（参照 = 进屏第一个读数）' : '体感关';
      this.hintUntil = Date.now() + 1400;
      if (this.gyroOn) {
        const err = gyro.start();
        if (err !== '') {
          this.hint = err;
          console.warn(err);
        }
      }
      this.draw();
    } catch (e) {
      console.warn('读体感偏好失败：' + (e as Error).message);
    }
  }

  // ---------------- 触摸 ----------------

  private rtOf(slot: Slot): PadRt {
    let r = this.rt.get(slot.name);
    if (r === undefined) {
      r = new PadRt();
      this.rt.set(slot.name, r);
    }
    return r;
  }

  private handleTouch(event: TouchEvent): void {
    const w = this.cw;
    const h = this.ch;
    if (w <= 0 || h <= 0) {
      return;
    }
    const changed = event.changedTouches.length > 0 ? event.changedTouches : event.touches;
    for (const t of changed) {
      const id = t.id;
      if (event.type === TouchType.Down) {
        const slot = layout.hitSlot(t.x, t.y, w, h);
        if (slot === null) {
          continue;
        }
        const r = this.rtOf(slot);
        if (r.isDown && r.owner !== -1 && r.owner !== id) {
          // 这个槽已经被别的手指按着了：这根手指只负责它自己按下的那个区域
          continue;
        }
        const p = layout.toLocal(slot, t.x, t.y, w, h);
        this.fingers.set(id, slot.name);
        r.owner = id;
        r.isDown = true;
        r.moved = false;
        r.downAt = Date.now();
        r.downX = p.x;
        r.downY = p.y;
        if (slot.bit >= 0) {
          controller.state.setBit(slot.bit, true);
        }
        this.onPress(slot, r, p.x, p.y);
        this.onPointer(slot, r, p.x, p.y);
        this.changed();
      } else if (event.type === TouchType.Move) {
        const name = this.fingers.get(id);
        if (name === undefined) {
          continue;
        }
        const slot = layout.slotByName(name);
        if (slot === null) {
          continue;
        }
        const r = this.rtOf(slot);
        if (r.owner !== id) {
          continue;
        }
        const p = layout.toLocal(slot, t.x, t.y, w, h);
        const dx = p.x - r.downX;
        const dy = p.y - r.downY;
        if (Math.sqrt(dx * dx + dy * dy) > MOVE_THRESHOLD) {
          r.moved = true;
        }
        this.onPointer(slot, r, p.x, p.y);
        this.changed();
      } else if (event.type === TouchType.Up || event.type === TouchType.Cancel) {
        const name = this.fingers.get(id);
        if (name === undefined) {
          continue;
        }
        const slot = layout.slotByName(name);
        if (slot === null) {
          continue;
        }
        const r = this.rtOf(slot);
        if (r.owner !== id) {
          // 不是这个槽的主人：只把自己从映射里撤掉
          this.fingers.delete(id);
          continue;
        }
        const p = layout.toLocal(slot, t.x, t.y, w, h);
        if (!r.moved && Date.now() - r.downAt <= TAP_MS) {
          this.onTap(slot, r);
        }
        this.onReleased(slot, r);
        r.owner = -1;
        // 手指抬起只释放它自己的槽
        this.fingers.delete(id);
        this.changed();
      }
    }
  }

  /** 扳机：按下的那一刻输入 0，只有往「按到底」那个方向拖才涨（往回拖就降回 0） */
  private onPress(slot: Slot, r: PadRt, x: number, y: number): void {
    if (slot.kind === KIND_TRIGGER) {
      r.anchorY = y;
      r.depth = 0;
      controller.state.setTrigger(slot.name === 'LT', 0);
    }
  }

  private onPointer(slot: Slot, r: PadRt, x: number, y: number): void {
    const ownW = layout.ownW(slot);
    const ownH = layout.ownH(slot);
    if (slot.kind === KIND_HAT) {
      const cx = ownW / 2;
      const cy = ownH / 2;
      const dx = x - cx;
      const dy = y - cy;
      if (Math.sqrt(dx * dx + dy * dy) < HAT_DEADZONE) {
        r.dir = HAT_NEUTRAL;
        controller.state.applyHat(HAT_NEUTRAL);
        return;
      }
      const deg = Math.atan2(dy, dx) * 180 / Math.PI;
      let idx = Math.round((deg + 90) / 45);
      idx = ((idx % 8) + 8) % 8;
      r.dir = idx;
      controller.state.applyHat(idx);
      return;
    }
    if (slot.kind === KIND_STICK) {
      // 体感驱动时：手搓不生效、松手不回中，值由外部给
      if (this.gyroOn && slot.name === '左摇杆') {
        return;
      }
      const r0 = Math.min(ownW, ownH) / 2 - 4;
      if (r0 <= 0) {
        return;
      }
      let px = (x - ownW / 2) / r0;
      let py = (y - ownH / 2) / r0;
      const mag = Math.sqrt(px * px + py * py);
      if (mag > 1) {
        px = px / mag;
        py = py / mag;
      }
      if (mag < DEADZONE) {
        px = 0;
        py = 0;
      }
      r.nx = px;
      r.ny = py;
      controller.state.setStick(slot.name === '左摇杆', Math.round(px * 127), Math.round(py * 127));
      return;
    }
    if (slot.kind === KIND_TRIGGER) {
      if (ownH === 0) {
        return;
      }
      const span = Math.max(ownH - r.anchorY, 12);
      r.depth = Math.min(Math.max((y - r.anchorY) / span, 0), 1);
      controller.state.setTrigger(slot.name === 'LT', Math.round(r.depth * 255));
    }
  }

  /** 判定为「点击」：按下到抬起不超过 TAP_MS，且手指没有明显移动 */
  private onTap(slot: Slot, r: PadRt): void {
    if (slot.kind === KIND_STICK) {
      // 双击摇杆 = L3/R3（再双击取消）
      if (slot.pressBit < 0) {
        return;
      }
      const now = Date.now();
      if (now - r.lastTapAt <= DOUBLE_TAP_MS) {
        r.latched = !r.latched;
        controller.state.setBit(slot.pressBit, r.latched);
        r.lastTapAt = 0;
      } else {
        r.lastTapAt = now;
      }
      return;
    }
    if (slot.kind === KIND_ACTION) {
      if (slot.action === 'recenter') {
        this.recenter();
      } else if (slot.action === 'close') {
        router.back();
      }
    }
  }

  private onReleased(slot: Slot, r: PadRt): void {
    r.isDown = false;
    if (slot.bit >= 0) {
      controller.state.setBit(slot.bit, false);
    }
    if (slot.kind === KIND_HAT) {
      r.dir = HAT_NEUTRAL;
      controller.state.applyHat(HAT_NEUTRAL);
      return;
    }
    if (slot.kind === KIND_STICK) {
      if (this.gyroOn && slot.name === '左摇杆') {
        return;
      }
      r.nx = 0;
      r.ny = 0;
      controller.state.setStick(slot.name === '左摇杆', 0, 0);
      return;
    }
    if (slot.kind === KIND_TRIGGER) {
      r.depth = 0;
      r.anchorY = 0;
      controller.state.setTrigger(slot.name === 'LT', 0);
    }
  }

  private changed(): void {
    controller.send();
    this.draw();
  }

  /** 回正（只有陀螺仪：把当前当成 0，从这儿开始重新积分） */
  private recenter(): void {
    if (!this.gyroOn) {
      this.showHint('体感没开，先在第一屏打开「体感→左摇杆」');
      return;
    }
    gyro.recenter();
    this.gyroValue = 0;
    this.gyroDeg = 0;
    this.showHint('已回正（当前姿态 = 0）');
    controller.send();
    this.draw();
  }

  private showHint(text: string): void {
    this.hint = text;
    this.hintUntil = Date.now() + 1400;
    promptAction.showToast({ message: text });
  }

  // ---------------- 画 ----------------

  private draw(): void {
    const c = this.ctx;
    const w = this.cw;
    const h = this.ch;
    if (w <= 0 || h <= 0) {
      return;
    }
    c.clearRect(0, 0, w, h);
    c.fillStyle = BG;
    c.fillRect(0, 0, w, h);

    for (const slot of layout.slots) {
      this.drawSlot(c, slot, w, h);
    }
  }

  private drawSlot(c: CanvasRenderingContext2D, slot: Slot, w: number, h: number): void {
    const r = this.rtOf(slot);
    const ownW = layout.ownW(slot);
    const ownH = layout.ownH(slot);
    if (ownW <= 0 || ownH <= 0) {
      return;
    }
    const center = layout.centerOf(slot, w, h);

    c.save();
    c.translate(center.x, center.y);
    if (slot.angle !== 0) {
      c.rotate(slot.angle * Math.PI / 180);
    }
    // 之后都在槽自己的坐标系里画（0..ownW, 0..ownH），所以"顶边"就是键自己的顶边（跟着键一起转）
    c.translate(-ownW / 2, -ownH / 2);

    this.drawBackground(c, slot, r, ownW, ownH);
    this.drawExtra(c, slot, r, ownW, ownH);
    this.drawLabel(c, slot, r, ownW, ownH);
    c.restore();
  }

  private drawBackground(c: CanvasRenderingContext2D, slot: Slot, r: PadRt, ownW: number, ownH: number): void {
    const pad = 4;
    const highlight = slot.kind !== KIND_STICK && slot.kind !== KIND_BAR && r.isDown;
    c.fillStyle = highlight ? ACCENT : PANEL;
    c.strokeStyle = LINE;
    c.lineWidth = 2;
    if (slot.circle) {
      const radius = Math.min(ownW, ownH) / 2 - pad;
      if (radius <= 0) {
        return;
      }
      c.beginPath();
      c.arc(ownW / 2, ownH / 2, radius, 0, Math.PI * 2);
      c.fill();
      c.stroke();
    } else {
      const corner = Math.min(10, Math.min(ownW, ownH) / 2);
      c.beginPath();
      c.roundRect(pad, pad, ownW - 2 * pad, ownH - 2 * pad, corner);
      c.fill();
      c.stroke();
    }
  }

  private drawExtra(c: CanvasRenderingContext2D, slot: Slot, r: PadRt, ownW: number, ownH: number): void {
    if (slot.kind === KIND_HAT) {
      const radius = Math.min(ownW, ownH) / 2 - 4;
      if (radius <= 0) {
        return;
      }
      const cx = ownW / 2;
      const cy = ownH / 2;
      const t = 15;
      const reach = radius - 10;   // 十字臂在圆内，不顶到描边
      c.fillStyle = r.isDown ? ACCENT : ARM;
      c.beginPath();
      c.roundRect(cx - reach, cy - t / 2, reach * 2, t, t / 2);
      c.fill();
      c.beginPath();
      c.roundRect(cx - t / 2, cy - reach, t, reach * 2, t / 2);
      c.fill();
      for (const d of [0, 2, 4, 6]) {
        this.drawChevron(c, r, d, ownW, ownH);
      }
      return;
    }

    if (slot.kind === KIND_STICK) {
      const radius = Math.min(ownW, ownH) / 2 - 4;
      if (radius <= 0) {
        return;
      }
      const kr = radius * 0.42;
      const reach = radius > kr ? radius - kr : 0;
      const cx = ownW / 2;
      const cy = ownH / 2;
      c.fillStyle = KNOB;
      c.beginPath();
      c.arc(cx + r.nx * reach, cy + r.ny * reach, kr, 0, Math.PI * 2);
      c.fill();
      if (r.latched) {
        c.strokeStyle = ACCENT;
        c.lineWidth = 2;
        c.beginPath();
        c.arc(cx + r.nx * reach, cy + r.ny * reach, kr + 3, 0, Math.PI * 2);
        c.stroke();
        if (slot.pressBit >= 0) {
          c.font = '12vp sans-serif';
          c.fillStyle = ACCENT;
          c.textAlign = 'left';
          c.textBaseline = 'bottom';
          c.fillText(BIT_NAMES[slot.pressBit], 8, ownH - 8);
        }
      }
      return;
    }

    if (slot.kind === KIND_TRIGGER) {
      const pad = 4;
      c.fillStyle = r.isDown ? '#FFFFFF' : DIM;
      // 行程条固定从键的顶边开始画，长度 = 当前值（不按按下点画）
      const end = pad + (ownH - 2 * pad) * r.depth;
      if (end > pad) {
        c.beginPath();
        c.roundRect(pad, pad, ownW - pad, end, 6);
        c.fill();
      }
      return;
    }

    if (slot.kind === KIND_BAR) {
      this.drawGyroBar(c, ownW, ownH);
    }
  }

  private drawChevron(c: CanvasRenderingContext2D, r: PadRt, hatDir: number, ownW: number, ownH: number): void {
    const radius = Math.min(ownW, ownH) / 2 - 4;
    const cr = radius - 20;
    if (cr <= 0) {
      return;
    }
    const cx = ownW / 2;
    const cy = ownH / 2;
    const angle = DEGREES[hatDir] * Math.PI / 180;
    const px = cx + cr * Math.cos(angle);
    const py = cy + cr * Math.sin(angle);
    c.strokeStyle = r.dir === hatDir ? '#FFFFFF' : DIM;
    c.lineWidth = 2.5;
    c.lineCap = 'round';
    const size = 9;
    c.beginPath();
    c.moveTo(px + size * Math.cos(angle + ARM_ANGLE), py + size * Math.sin(angle + ARM_ANGLE));
    c.lineTo(px, py);
    c.lineTo(px + size * Math.cos(angle - ARM_ANGLE), py + size * Math.sin(angle - ARM_ANGLE));
    c.stroke();
  }

  /** 体感进度条：从中心往左或往右填，下面写「左 11°（-93）」 */
  private drawGyroBar(c: CanvasRenderingContext2D, ownW: number, ownH: number): void {
    const barH = 12;
    if (ownH < barH + 18) {
      return;
    }
    c.globalAlpha = this.gyroOn ? 0.43 : 0.24;
    c.fillStyle = DIM;
    c.beginPath();
    c.roundRect(0, 0, ownW, barH, barH / 2);
    c.fill();
    c.globalAlpha = 1;

    const cx = ownW / 2;
    c.strokeStyle = INK;
    c.globalAlpha = 0.6;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(cx, 0);
    c.lineTo(cx, barH);
    c.stroke();
    c.globalAlpha = 1;

    if (this.gyroOn && this.gyroValue !== 0) {
      const half = ownW / 2 - barH / 2;
      const pos = cx + (this.gyroValue / 127) * half;
      const left = pos < cx ? pos : cx;
      const right = pos < cx ? cx : pos;
      c.fillStyle = ACCENT;
      c.beginPath();
      c.roundRect(left, 0, right - left, barH, barH / 2);
      c.fill();
    }

    let label = '';
    if (this.hint !== '' && Date.now() < this.hintUntil) {
      label = this.hint;
    } else if (!this.gyroOn) {
      label = '体感关';
    } else if (this.gyroValue === 0) {
      label = '体感 0°（参照 = 进屏第一个读数）';
    } else {
      label = (this.gyroValue < 0 ? '左' : '右') + Math.round(this.gyroDeg) + '°/' + this.gyroRange + '°（' + this.gyroValue + '）';
    }
    c.font = '13vp sans-serif';
    c.fillStyle = INK;
    c.textAlign = 'center';
    c.textBaseline = 'top';
    c.fillText(label, ownW / 2, barH + 4);
  }

  private drawLabel(c: CanvasRenderingContext2D, slot: Slot, r: PadRt, ownW: number, ownH: number): void {
    if (slot.name === '') {
      return;
    }
    if (slot.corner) {
      c.font = '12vp sans-serif';
      c.fillStyle = DIM;
      c.textAlign = 'left';
      c.textBaseline = 'top';
      c.fillText(slot.name, 8, 8);
      return;
    }
    const size = Math.min(ownW, ownH) * 0.34;
    c.font = size.toFixed(1) + 'vp sans-serif';
    c.fillStyle = (slot.kind !== KIND_STICK && r.isDown) ? '#FFFFFF' : INK;
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    c.fillText(slot.name, ownW / 2, ownH / 2);
  }

  build() {
    Stack() {
      Canvas(this.ctx)
        .width('100%')
        .height('100%')
        .onReady((): void => {
          this.draw();
        })
        .onAreaChange((oldValue: Area, newValue: Area): void => {
          if (typeof newValue.width === 'number') {
            this.cw = newValue.width;
          }
          if (typeof newValue.height === 'number') {
            this.ch = newValue.height;
          }
          this.draw();
        })
        .onTouch((event: TouchEvent): void => {
          this.handleTouch(event);
        })
    }
    .width('100%')
    .height('100%')
    .backgroundColor(BG)
  }
}
