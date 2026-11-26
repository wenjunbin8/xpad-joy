/** 小工具类：ArkTS 没有 RectF，画布和判定都用这两个（单位 = vp，和安卓端的 dp 等价） */
export class Rect {
  left: number = 0;
  top: number = 0;
  right: number = 0;
  bottom: number = 0;

  constructor(left: number, top: number, right: number, bottom: number) {
    this.left = left;
    this.top = top;
    this.right = right;
    this.bottom = bottom;
  }

  width(): number {
    return this.right - this.left;
  }

  height(): number {
    return this.bottom - this.top;
  }

  cx(): number {
    return (this.left + this.right) / 2;
  }

  cy(): number {
    return (this.top + this.bottom) / 2;
  }

  contains(x: number, y: number): boolean {
    return x >= this.left && x <= this.right && y >= this.top && y <= this.bottom;
  }
}

export class Point {
  x: number = 0;
  y: number = 0;

  constructor(x: number, y: number) {
    this.x = x;
    this.y = y;
  }
}
