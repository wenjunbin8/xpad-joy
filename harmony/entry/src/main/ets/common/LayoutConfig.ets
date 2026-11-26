import { BTN_A, BTN_B, BTN_X, BTN_Y, BTN_LB, BTN_RB, BTN_BACK, BTN_START, BTN_GUIDE, BTN_L3, BTN_R3, HAT_NEUTRAL } from './Protocol';
import { Point, Rect } from './Rect';

/** 槽的类型（安卓端靠 resId 区分，鸿蒙没有资源 ID，就用这个） */
export const KIND_BUTTON: number = 0;
export const KIND_HAT: number = 1;
export const KIND_STICK: number = 2;
export const KIND_TRIGGER: number = 3;
export const KIND_ACTION: number = 4;   // ✕ / 回正
export const KIND_BAR: number = 5;      // 体感条（只显示，不响应点击）

/** 和安卓端 LayoutConfig 同一批限制 */
export const MIN_SIZE: number = 24;
export const MAX_SIZE: number = 200;
export const MAX_SIDE: number = 240;
export const MAX_ANGLE: number = 359;
/** 滑条 1 格 = 5°，靠近 90° 整倍数就吸上去（0 / 90 / 180 / 270） */
export const SNAP_DEG: number = 5;

/**
 * 不在组里的槽：归一化中心 + 尺寸（单位 vp，和安卓端的 dp 等价）。
 * angle = 绕中心旋转，只有 canRotate 的槽（LT/RT）能用。
 */
export class Slot {
  name: string = '';
  kind: number = KIND_BUTTON;
  bit: number = -1;       // 按键位（-1 = 不是按键）
  pressBit: number = -1;  // 双击时的位（摇杆 L3/R3）
  action: string = '';    // 动作槽：'close' / 'recenter'
  circle: boolean = true;
  corner: boolean = false;   // 标签写在左上角（十字键、摇杆、扳机）
  cx: number = 0;
  cy: number = 0;
  w: number = 24;
  h: number = 24;
  group: string = '';
  rx: number = 0;   // 组内相对位置（单位 = 边长）
  ry: number = 0;
  angle: number = 0;
  canRotate: boolean = false;
  lockRatio: boolean = false;   // 等比例调（LT/RT）：只改长边，短边按 ratio 算
  ratio: number = 0;            // w / h
}

/** 正方形框：边长和框内按键大小锁定一起调整（按键大小 = 边长 × ratio） */
export class Group {
  name: string = '';
  cx: number = 0;
  cy: number = 0;
  side: number = 0;
  ratio: number = 0;

  keySize(): number {
    return this.side * this.ratio;
  }
}

/**
 * 可自定义布局：手柄屏和编辑器读同一份配置（默认值和安卓端 LayoutConfig.kt 一模一样）。
 * 保存到偏好 xpadjoy / layout_json，格式和安卓端一致（groups + slots，含 angle）。
 */
export class LayoutConfig {
  slots: Slot[] = [];
  groups: Group[] = [];

  constructor() {
    this.resetDefaults();
  }

  resetDefaults(): void {
    this.slots = [];
    this.groups = [];

    const lt = this.add('LT', KIND_TRIGGER, false, 0.055, 0.270, 70, 120);
    lt.canRotate = true;
    lt.lockRatio = true;
    lt.ratio = 70 / 120;
    lt.corner = true;

    this.add('LB', KIND_BUTTON, true, 0.140, 0.420, 54, 54).bit = BTN_LB;
    this.add('十字键', KIND_HAT, true, 0.170, 0.700, 110, 110).corner = true;
    const leftStick = this.add('左摇杆', KIND_STICK, true, 0.310, 0.820, 110, 110);
    leftStick.pressBit = BTN_L3;
    leftStick.corner = true;

    this.add('✕', KIND_ACTION, true, 0.500, 0.130, 44, 44).action = 'close';
    const center = this.add('回正', KIND_ACTION, false, 0.630, 0.130, 74, 42);
    center.action = 'recenter';
    this.add('体感条', KIND_BAR, false, 0.500, 0.560, 190, 40).corner = true;
    this.add('BACK', KIND_BUTTON, true, 0.425, 0.320, 46, 46).bit = BTN_BACK;
    this.add('GUIDE', KIND_BUTTON, true, 0.500, 0.320, 50, 50).bit = BTN_GUIDE;
    this.add('START', KIND_BUTTON, true, 0.575, 0.320, 46, 46).bit = BTN_START;

    const rt = this.add('RT', KIND_TRIGGER, false, 0.945, 0.270, 70, 120);
    rt.canRotate = true;
    rt.lockRatio = true;
    rt.ratio = 70 / 120;
    rt.corner = true;
    this.add('RB', KIND_BUTTON, true, 0.860, 0.420, 54, 54).bit = BTN_RB;
    const rightStick = this.add('右摇杆', KIND_STICK, true, 0.690, 0.820, 110, 110);
    rightStick.pressBit = BTN_R3;
    rightStick.corner = true;

    // ABXY = 一个正方形框（边长 120，按键 = 边长 × 0.383 ≈ 46）
    const abxy = new Group();
    abxy.name = 'ABXY';
    abxy.cx = 0.830;
    abxy.cy = 0.700;
    abxy.side = 120;
    abxy.ratio = 46 / 120;
    this.groups.push(abxy);

    this.addGrouped('Y', BTN_Y, 0, -0.30);
    this.addGrouped('A', BTN_A, 0, 0.30);
    this.addGrouped('X', BTN_X, -0.30, 0);
    this.addGrouped('B', BTN_B, 0.30, 0);
  }

  private add(name: string, kind: number, circle: boolean, cx: number, cy: number, w: number, h: number): Slot {
    const s = new Slot();
    s.name = name;
    s.kind = kind;
    s.circle = circle;
    s.cx = cx;
    s.cy = cy;
    s.w = w;
    s.h = h;
    this.slots.push(s);
    return s;
  }

  private addGrouped(name: string, bit: number, rx: number, ry: number): void {
    const s = new Slot();
    s.name = name;
    s.kind = KIND_BUTTON;
    s.circle = true;
    s.w = 46;
    s.h = 46;
    s.bit = bit;
    s.group = 'ABXY';
    s.rx = rx;
    s.ry = ry;
    this.slots.push(s);
  }

  slotByName(name: string): Slot | null {
    for (const s of this.slots) {
      if (s.name === name) {
        return s;
      }
    }
    return null;
  }

  groupByName(name: string): Group | null {
    for (const g of this.groups) {
      if (g.name === name) {
        return g;
      }
    }
    return null;
  }

  /** 靠近 90° 整倍数就吸上去，其它角度按滑条（滑条 1 格 = 5°，所以吸附窗口就是 5°） */
  snap(angle: number): number {
    let nearest = Math.round(angle / 90) * 90;
    if (nearest >= 360) {
      nearest = 0;
    }
    return Math.abs(angle - nearest) <= SNAP_DEG ? nearest : angle;
  }

  /** 等比例改大小（LT/RT）：value = 长边，短边按锁定的 ratio 算 */
  setSize(slot: Slot, value: number): void {
    if (!slot.lockRatio) {
      slot.w = clamp(value, MIN_SIZE, MAX_SIZE);
      if (slot.circle) {
        slot.h = slot.w;
      }
      return;
    }
    const r = slot.ratio > 0 ? slot.ratio : 1;
    const longSide = clamp(value, this.minLongSide(slot), MAX_SIZE);
    if (r >= 1) {
      slot.w = longSide;
      slot.h = longSide / r;
    } else {
      slot.h = longSide;
      slot.w = longSide * r;
    }
  }

  /** 等比例槽滑条的下限（长边）：短边不低于 MIN_SIZE */
  minLongSide(slot: Slot): number {
    const r = slot.ratio > 0 ? slot.ratio : 1;
    return MIN_SIZE / Math.min(1, r);
  }

  /** 面板滑条那一条画的是长边（等比例槽），其它槽还是宽 */
  longSide(slot: Slot): number {
    return slot.lockRatio ? Math.max(slot.w, slot.h) : slot.w;
  }

  /** 改边长时按键大小按锁定比例一起变 */
  setSide(group: Group, value: number): void {
    group.side = clamp(value, MIN_SIZE, MAX_SIDE);
  }

  /** 槽自己的尺寸（vp）：在组里的槽由正方形框决定 */
  ownW(slot: Slot): number {
    const g = slot.group === '' ? null : this.groupByName(slot.group);
    return g === null ? slot.w : g.keySize();
  }

  ownH(slot: Slot): number {
    const g = slot.group === '' ? null : this.groupByName(slot.group);
    return g === null ? slot.h : g.keySize();
  }

  /** 槽的中心（画布坐标，vp） */
  centerOf(slot: Slot, width: number, height: number): Point {
    const g = slot.group === '' ? null : this.groupByName(slot.group);
    if (g === null) {
      return new Point(slot.cx * width, slot.cy * height);
    }
    const side = g.side;
    return new Point(g.cx * width + slot.rx * side, g.cy * height + slot.ry * side);
  }

  /**
   * 槽的实际矩形（外接框）：转了角度的槽要变大，不然转 90° 会画到框外。
   * 和安卓端 rectFor 完全一样（dp → vp 一比一）。
   */
  rectFor(slot: Slot, width: number, height: number): Rect {
    const c = this.centerOf(slot, width, height);
    const pw = this.ownW(slot);
    const ph = this.ownH(slot);
    if (slot.canRotate && slot.angle !== 0) {
      const rad = slot.angle * Math.PI / 180;
      const c2 = Math.abs(Math.cos(rad));
      const s2 = Math.abs(Math.sin(rad));
      const bw = pw * c2 + ph * s2;
      const bh = pw * s2 + ph * c2;
      return new Rect(c.x - bw / 2, c.y - bh / 2, c.x + bw / 2, c.y + bh / 2);
    }
    return new Rect(c.x - pw / 2, c.y - ph / 2, c.x + pw / 2, c.y + ph / 2);
  }

  rectForGroup(group: Group, width: number, height: number): Rect {
    const cx = group.cx * width;
    const cy = group.cy * height;
    return new Rect(cx - group.side / 2, cy - group.side / 2, cx + group.side / 2, cy + group.side / 2);
  }

  /** 画布坐标 → 槽自己的坐标系（0..ownW, 0..ownH），和安卓端 ControlView.toLocal 一样 */
  toLocal(slot: Slot, x: number, y: number, width: number, height: number): Point {
    const c = this.centerOf(slot, width, height);
    const ownW = this.ownW(slot);
    const ownH = this.ownH(slot);
    const dx = x - c.x;
    const dy = y - c.y;
    if (slot.angle === 0) {
      return new Point(ownW / 2 + dx, ownH / 2 + dy);
    }
    const rad = slot.angle * Math.PI / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    // canvas.rotate(正角度) 是屏幕上的顺时针，所以逆变换是反号
    return new Point(ownW / 2 + dx * cos + dy * sin, ownH / 2 - dx * sin + dy * cos);
  }

  /** 转了角度以后外接框的四个角不在形状上：按在角上不判定 */
  inside(slot: Slot, x: number, y: number, width: number, height: number): boolean {
    if (slot.angle === 0) {
      return this.rectFor(slot, width, height).contains(x, y);
    }
    const p = this.toLocal(slot, x, y, width, height);
    const ownW = this.ownW(slot);
    const ownH = this.ownH(slot);
    if (slot.circle) {
      const r = Math.min(ownW, ownH) / 2 - 4;
      if (r <= 0) {
        return false;
      }
      const dx = p.x - ownW / 2;
      const dy = p.y - ownH / 2;
      return Math.sqrt(dx * dx + dy * dy) <= r;
    }
    return p.x >= 0 && p.y >= 0 && p.x <= ownW && p.y <= ownH;
  }

  /** 读偏好里的 JSON（不用 JSON.parse，手工取值，和 Transport.ets 一个路子） */
  load(json: string): void {
    if (json === '') {
      return;
    }
    for (const chunk of objectChunks(arrayRegion(json, 'groups'))) {
      const g = this.groupByName(fieldOf(chunk, 'name'));
      if (g === null) {
        continue;
      }
      g.cx = numOr(fieldOf(chunk, 'cx'), g.cx);
      g.cy = numOr(fieldOf(chunk, 'cy'), g.cy);
      g.side = numOr(fieldOf(chunk, 'side'), g.side);
      if (hasField(chunk, 'ratio')) {
        g.ratio = numOr(fieldOf(chunk, 'ratio'), g.ratio);
      } else if (hasField(chunk, 'keySize') && g.side > 0) {
        // 兼容旧存档：用旧的按键大小反推锁定比例
        g.ratio = clamp(numOr(fieldOf(chunk, 'keySize'), g.keySize()) / g.side, 0.10, 0.60);
      }
    }

    for (const chunk of objectChunks(arrayRegion(json, 'slots'))) {
      const name = fieldOf(chunk, 'name');
      const s = this.slotByName(name);
      if (s === null || s.group !== '') {
        continue;
      }
      s.cx = numOr(fieldOf(chunk, 'cx'), s.cx);
      s.cy = numOr(fieldOf(chunk, 'cy'), s.cy);
      s.w = numOr(fieldOf(chunk, 'w'), s.w);
      s.h = numOr(fieldOf(chunk, 'h'), s.h);
      if (s.lockRatio) {
        // 老存档里宽高可能已经偏离锁定比例，按长边拉回比例
        this.setSize(s, Math.max(s.w, s.h));
      }
      if (s.canRotate) {
        s.angle = this.snap(numOr(fieldOf(chunk, 'angle'), s.angle));
      }
    }
  }

  /** 保存：格式和安卓端 LayoutConfig.save 一致（groups + slots，含 angle），两边文件可互换 */
  toJson(): string {
    let s = '{"groups":[';
    for (let i = 0; i < this.groups.length; i++) {
      if (i > 0) {
        s += ',';
      }
      const g = this.groups[i];
      s += '{"name":' + quote(g.name) + ',"cx":' + num(g.cx) + ',"cy":' + num(g.cy) +
        ',"side":' + num(g.side) + ',"ratio":' + num(g.ratio) + '}';
    }
    s += '],"slots":[';
    let first = true;
    for (const slot of this.slots) {
      if (slot.group !== '') {
        continue;
      }
      if (!first) {
        s += ',';
      }
      first = false;
      s += '{"name":' + quote(slot.name) + ',"cx":' + num(slot.cx) + ',"cy":' + num(slot.cy) +
        ',"w":' + num(slot.w) + ',"h":' + num(slot.h);
      if (slot.canRotate) {
        s += ',"angle":' + num(slot.angle);
      }
      s += '}';
    }
    return s + ']}';
  }

  /** 画布上的命中：逆序（按键在框之上，先命中按键再命中框） */
  hitSlot(x: number, y: number, width: number, height: number): Slot | null {
    for (let i = this.slots.length - 1; i >= 0; i--) {
      const s = this.slots[i];
      if (this.inside(s, x, y, width, height)) {
        return s;
      }
    }
    return null;
  }

  hitGroup(x: number, y: number, width: number, height: number): Group | null {
    for (let i = this.groups.length - 1; i >= 0; i--) {
      const g = this.groups[i];
      if (this.rectForGroup(g, width, height).contains(x, y)) {
        return g;
      }
    }
    return null;
  }
}

/** 全局共享的布局（手柄屏和编辑器读同一份） */
export const layout = new LayoutConfig();

/** 中性十字键值，给编辑器/画布用 */
export const HAT_CENTER = HAT_NEUTRAL;

// ---- 手工 JSON 取值（ArkTS 不能把 JSON.parse 的结果当接口用） ----

function fieldOf(text: string, key: string): string {
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

function hasField(text: string, key: string): boolean {
  return fieldOf(text, key) !== '';
}

function numOr(text: string, def: number): number {
  if (text === '') {
    return def;
  }
  const v = Number.parseFloat(text);
  return Number.isNaN(v) ? def : v;
}

function arrayRegion(text: string, key: string): string {
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
  while (i < text.length && text[i] !== '[') {
    i++;
  }
  if (i >= text.length) {
    return '';
  }
  const end = text.indexOf(']', i);
  if (end < 0) {
    return '';
  }
  return text.substring(i + 1, end);
}

/** 存档里的对象都是平铺的，所以 { 到 } 就是一段 */
function objectChunks(region: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < region.length) {
    const open = region.indexOf('{', i);
    if (open < 0) {
      break;
    }
    const close = region.indexOf('}', open);
    if (close < 0) {
      break;
    }
    out.push(region.substring(open, close + 1));
    i = close + 1;
  }
  return out;
}

function quote(s: string): string {
  return '"' + s + '"';
}

function num(v: number): string {
  return '' + Math.round(v * 1000000) / 1000000;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}
