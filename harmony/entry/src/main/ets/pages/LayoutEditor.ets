import { promptAction, router, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { Group, Slot, layout, MAX_ANGLE, MAX_SIDE, MAX_SIZE, MIN_SIZE } from '../common/LayoutConfig';
import { getStr, openPrefs, put } from '../common/Prefs';
import { ACCENT, BG, CARD, DIM, INK, LINE, PANEL } from '../common/Palette';
import { applyOrientation, hideSystemBars } from '../common/AppCtx';

/**
 * 布局页（横屏）：画布就是手柄屏的实际区域。
 * 单个槽 → 点选后拖动移位 + 改宽/高；正方形框（ABXY）→ 点框内任意位置选中整组，拖动移动整组，
 * 改边长（按键大小按锁定比例一起变）。
 * 角度（只有 LT/RT）：滑条只做粗调（1 格 = 5°），靠近 90° 整倍数自动吸附；精确落定用 0/90/180/270，微调 -5/-1/+1/+5。
 * 保存到偏好 xpadjoy / layout_json（和安卓端同一份格式，两边文件可互换）。
 */
@Entry
@Component
struct LayoutEditor {
  private ctx: CanvasRenderingContext2D = new CanvasRenderingContext2D(new RenderingContextSettings(true));

  private cw: number = 0;
  private ch: number = 0;

  @State selName: string = '';
  @State selGroup: string = '';
  @State expanded: boolean = false;
  @State barW: number = MIN_SIZE;
  @State barH: number = MIN_SIZE;
  @State barAngle: number = 0;
  @State angleText: string = '';
  @State hint: string = '未选择';

  private grabDX: number = 0;
  private grabDY: number = 0;

  aboutToAppear(): void {
    const host = this.getUIContext().getHostContext();
    this.initWindow();
    if (host === undefined) {
      return;
    }
    this.loadSaved(host);
  }

  onPageShow(): void {
    this.initWindow();
    this.draw();
  }

  private async initWindow(): Promise<void> {
    const err = await applyOrientation(window.Orientation.LANDSCAPE);
    if (err !== '') {
      this.hint = '转横屏失败：' + err;
      console.warn('转横屏失败：' + err);
    }
    const err2 = await hideSystemBars();
    if (err2 !== '') {
      console.warn('沉浸全屏失败：' + err2);
    }
    this.draw();
  }

  private async loadSaved(host: common.Context): Promise<void> {
    try {
      const p = await openPrefs(host);
      layout.load(await getStr(p, 'layout_json', ''));
      this.refreshPanel();
      this.draw();
    } catch (e) {
      console.warn('读布局存档失败：' + (e as Error).message);
    }
  }

  private selectedSlot(): Slot | null {
    return this.selName === '' ? null : layout.slotByName(this.selName);
  }

  private selectedGroup(): Group | null {
    return this.selGroup === '' ? null : layout.groupByName(this.selGroup);
  }

  // ---------------- 选中 / 拖动 ----------------

  private onPadTouch(event: TouchEvent): void {
    const w = this.cw;
    const h = this.ch;
    if (w <= 0 || h <= 0 || event.touches.length === 0) {
      return;
    }
    const t = event.touches[0];

    if (event.type === TouchType.Down) {
      // 按键在框之上，先逆序命中按键，再命中框
      const hit = layout.hitSlot(t.x, t.y, w, h);
      let group: Group | null = null;
      if (hit !== null && hit.group !== '') {
        group = layout.groupByName(hit.group);
      }
      if (group === null) {
        group = layout.hitGroup(t.x, t.y, w, h);
      }

      if (group !== null) {
        this.selGroup = group.name;
        this.selName = '';
        const r = layout.rectForGroup(group, w, h);
        this.grabDX = t.x - r.cx();
        this.grabDY = t.y - r.cy();
      } else if (hit !== null) {
        this.selName = hit.name;
        this.selGroup = '';
        const r = layout.rectFor(hit, w, h);
        this.grabDX = t.x - r.cx();
        this.grabDY = t.y - r.cy();
      } else {
        return;
      }
      this.refreshPanel();
      this.draw();
    } else if (event.type === TouchType.Move) {
      const g = this.selectedGroup();
      if (g !== null) {
        g.cx = clamp01((t.x - this.grabDX) / w);
        g.cy = clamp01((t.y - this.grabDY) / h);
      } else {
        const s = this.selectedSlot();
        if (s === null) {
          return;
        }
        s.cx = clamp01((t.x - this.grabDX) / w);
        s.cy = clamp01((t.y - this.grabDY) / h);
      }
      this.draw();
    }
  }

  // ---------------- 滑条 / 按钮 ----------------

  private refreshPanel(): void {
    const g = this.selectedGroup();
    if (g !== null) {
      this.hint = g.name + '（正方形框）';
      this.barW = Math.round(g.side);
      return;
    }
    const s = this.selectedSlot();
    if (s === null) {
      this.hint = '未选择';
      return;
    }
    this.hint = s.name;
    this.barW = Math.round(layout.longSide(s));
    this.barH = Math.round(s.h);
    if (s.canRotate) {
      this.barAngle = Math.round(s.angle);
      this.angleText = angleLabel(s.angle);
    }
  }

  private widthLabel(): string {
    const g = this.selectedGroup();
    if (g !== null) {
      return '边长';
    }
    const s = this.selectedSlot();
    if (s !== null && s.lockRatio) {
      return '大小';
    }
    return '宽';
  }

  private widthMax(): number {
    return this.selectedGroup() !== null ? MAX_SIDE : MAX_SIZE;
  }

  private showHeight(): boolean {
    const s = this.selectedSlot();
    return this.selectedGroup() === null && s !== null && !s.lockRatio;
  }

  private showAngle(): boolean {
    const s = this.selectedSlot();
    return s !== null && s.canRotate;
  }

  private ratioText(): string {
    const s = this.selectedSlot();
    if (s === null) {
      return '';
    }
    return '比例 ' + Math.round(s.ratio * 100) + '%';
  }

  private setWidth(value: number): void {
    const g = this.selectedGroup();
    if (g !== null) {
      layout.setSide(g, value);
    } else {
      const s = this.selectedSlot();
      if (s === null) {
        return;
      }
      layout.setSize(s, value);
    }
    this.refreshPanel();
    this.draw();
  }

  private setHeight(value: number): void {
    const s = this.selectedSlot();
    if (s === null || s.lockRatio) {
      return;
    }
    s.h = clampNum(value, MIN_SIZE, MAX_SIZE);
    if (s.circle) {
      s.w = s.h;
    }
    this.refreshPanel();
    this.draw();
  }

  private setAngle(value: number): void {
    const s = this.selectedSlot();
    if (s === null || !s.canRotate) {
      return;
    }
    // 滑条 1 格 = 5°：靠近 90° 整倍数就吸上去
    s.angle = layout.snap(clampNum(Math.round(value), 0, MAX_ANGLE));
    this.refreshPanel();
    this.draw();
  }

  private nudgeAngle(delta: number): void {
    const s = this.selectedSlot();
    if (s === null || !s.canRotate) {
      return;
    }
    const a = ((s.angle + delta) % 360 + 360) % 360;
    s.angle = layout.snap(a);
    this.refreshPanel();
    this.draw();
  }

  private save(): void {
    const host = this.getUIContext().getHostContext();
    if (host === undefined) {
      return;
    }
    this.saveTo(host);
  }

  private async saveTo(host: common.Context): Promise<void> {
    try {
      const p = await openPrefs(host);
      await put(p, 'layout_json', layout.toJson());
      promptAction.showToast({ message: '已保存（手柄屏按同一份配置摆放）' });
    } catch (e) {
      promptAction.showToast({ message: '保存失败：' + (e as Error).message });
    }
  }

  private resetDefaults(): void {
    layout.resetDefaults();
    this.selName = '';
    this.selGroup = '';
    this.refreshPanel();
    this.draw();
    promptAction.showToast({ message: '已恢复默认（还没保存）' });
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

    c.setLineDash([10, 8]);
    c.strokeStyle = ACCENT;
    c.lineWidth = 2;
    for (const g of layout.groups) {
      const r = layout.rectForGroup(g, w, h);
      const corner = Math.min(8, r.width() / 6);
      c.beginPath();
      c.roundRect(r.left, r.top, r.width(), r.height(), corner);
      c.stroke();
    }
    c.setLineDash([]);

    c.textAlign = 'center';
    c.textBaseline = 'middle';
    for (const s of layout.slots) {
      const r = layout.rectFor(s, w, h);
      const ownW = layout.ownW(s);
      const ownH = layout.ownH(s);
      const corner = Math.min(ownW, ownH) / 2;
      const inGroup = s.group !== '' && s.group === this.selGroup;
      c.fillStyle = inGroup ? CARD : PANEL;
      c.strokeStyle = LINE;
      c.lineWidth = 2;
      if (s.canRotate && s.angle !== 0) {
        // 能转的槽（LT/RT）：按旋转后的形状画，线指向按到底那一头
        c.save();
        c.translate(r.cx(), r.cy());
        c.rotate(s.angle * Math.PI / 180);
        c.beginPath();
        c.roundRect(-ownW / 2, -ownH / 2, ownW, ownH, corner);
        c.fill();
        c.stroke();
        c.strokeStyle = ACCENT;
        c.lineWidth = 2.5;
        c.beginPath();
        c.moveTo(0, 0);
        c.lineTo(0, ownH / 2 - corner / 2);
        c.stroke();
        c.restore();
      } else {
        c.beginPath();
        c.roundRect(r.left, r.top, r.width(), r.height(), corner);
        c.fill();
        c.stroke();
      }
      if (s.name === this.selName) {
        c.strokeStyle = ACCENT;
        c.lineWidth = 3;
        c.beginPath();
        c.roundRect(r.left, r.top, r.width(), r.height(), corner);
        c.stroke();
      }
      c.font = '11vp sans-serif';
      c.fillStyle = INK;
      c.fillText(s.name, r.cx(), r.cy());
    }
  }

  @Builder
  angleButton(label: string, value: number, fine: boolean) {
    Text(label)
      .fontSize(13)
      .fontColor(INK)
      .padding({ left: 10, right: 10, top: 6, bottom: 6 })
      .backgroundColor(PANEL)
      .borderRadius(6)
      .border({ width: 1, color: LINE })
      .onClick((): void => {
        if (fine) {
          this.nudgeAngle(value);
        } else {
          this.setAngle(value);
        }
      })
  }

  build() {
    Column() {
      Canvas(this.ctx)
        .width('100%')
        .layoutWeight(1)
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
          this.onPadTouch(event);
        })

      Column({ space: 8 }) {
        Row({ space: 8 }) {
          Text(this.hint)
            .fontSize(14)
            .fontColor(INK)
            .layoutWeight(1)
          Button(this.expanded ? '收起' : '展开')
            .fontSize(13)
            .backgroundColor(PANEL)
            .fontColor(INK)
            .onClick((): void => {
              this.expanded = !this.expanded;
            })
        }
        .width('100%')

        if (this.expanded) {
          Row({ space: 8 }) {
            Text(this.widthLabel())
              .fontSize(13)
              .fontColor(DIM)
              .width(48)
            Slider({ value: this.barW, min: MIN_SIZE, max: this.widthMax(), step: 1 })
              .layoutWeight(1)
              .selectedColor(ACCENT)
              .onChange((value: number): void => {
                this.setWidth(value);
              })
          }
          .width('100%')

          if (this.showHeight()) {
            Row({ space: 8 }) {
              Text('高')
                .fontSize(13)
                .fontColor(DIM)
                .width(48)
              Slider({ value: this.barH, min: MIN_SIZE, max: MAX_SIZE, step: 1 })
                .layoutWeight(1)
                .selectedColor(ACCENT)
                .onChange((value: number): void => {
                  this.setHeight(value);
                })
            }
            .width('100%')
          }

          if (this.showAngle()) {
            Row({ space: 8 }) {
              Text('旋转 ' + this.angleText)
                .fontSize(13)
                .fontColor(DIM)
                .width(90)
              Slider({ value: this.barAngle, min: 0, max: MAX_ANGLE, step: 5 })
                .layoutWeight(1)
                .selectedColor(ACCENT)
                .onChange((value: number): void => {
                  this.setAngle(value);
                })
            }
            .width('100%')

            Row({ space: 6 }) {
              this.angleButton('0°', 0, false)
              this.angleButton('90°', 90, false)
              this.angleButton('180°', 180, false)
              this.angleButton('270°', 270, false)
            }
            .width('100%')

            Row({ space: 6 }) {
              this.angleButton('-5°', -5, true)
              this.angleButton('-1°', -1, true)
              this.angleButton('+1°', 1, true)
              this.angleButton('+5°', 5, true)
            }
            .width('100%')

            Text(this.ratioText())
              .fontSize(12)
              .fontColor(DIM)
          }

          Row({ space: 8 }) {
            Button('保存')
              .fontSize(13)
              .backgroundColor(ACCENT)
              .fontColor('#FFFFFF')
              .onClick((): void => {
                this.save();
              })
            Button('恢复默认')
              .fontSize(13)
              .backgroundColor(PANEL)
              .fontColor(INK)
              .onClick((): void => {
                this.resetDefaults();
              })
            Button('退出')
              .fontSize(13)
              .backgroundColor(PANEL)
              .fontColor(INK)
              .onClick((): void => {
                router.back();
              })
          }
          .width('100%')
        }
      }
      .width('100%')
      .padding(12)
      .backgroundColor(CARD)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(BG)
    .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
  }
}

function clamp01(v: number): number {
  return Math.min(Math.max(v, 0), 1);
}

function clampNum(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

function angleLabel(angle: number): string {
  const snapped = angle % 90 === 0;
  return Math.round(angle) + '°' + (snapped ? '（吸附）' : '');
}
