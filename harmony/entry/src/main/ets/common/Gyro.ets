import sensor from '@ohos.sensor';

/**
 * 体感 —— 绕屏幕法线转手机（"转方向盘"）= 左摇杆 X（Y 保持 0）。
 *
 * 轴：机身 Z（屏幕法线）。真机实测后定的：安卓端优先用 rotation vector，算的是绕 Z 的角度
 * （GamepadActivity 的 AXIS_AUTO -> axis=2），所以"转方向盘"的手感来自这条轴；
 * 原来这里抄的是安卓端"只有陀螺仪"退路里的"屏幕上看起来竖直那条轴"，手感对不上。
 * 符号：从屏幕正面看逆时针为正（= 摇杆往右），和安卓端 axisAngle() 的右手定则一致。
 *
 * 单位（真机 VYG-AL30 实测）：@ohos.sensor 的 gyroscope 报 rad/s，所以还要乘 57.29578；
 * 对照 ORIENTATION（报的是真度数）同一次转动的累计量，比值≈1.2（≈1，不是 57）→ 单位确认。
 * 没有绝对姿态，所以"基准"只能是进屏的第一个读数，回正 = 把当前当成 0 重新积分。
 */

/** 弧度 → 角度 */
const DEG: number = 57.29578;
/** 积分死区（rad/s），和安卓端 GYRO_DEADZONE_RATE 一致 */
const GYRO_DEADZONE_RATE: number = 0.02;
/** 发送节流，和安卓端 GYRO_SEND_INTERVAL_MS 一致 */
const GYRO_SEND_INTERVAL_MS: number = 30;
/**
 * 符号：真机定标结果。这台（VYG-AL30）的 gyroscope 轴方向和安卓端 axisAngle() 的右手定则相反，
 * 所以取 -1：俯视逆时针 = 摇杆往左（和安卓端在你手机上的实际手感一致）。
 * 如果哪天手感又反了，就把它改回 1。
 */
const ORIENTATION_SIGN: number = -1;
/** 真机实测用的开关：打开时订阅 ORIENTATION 当参照并打日志（定标已完成，平时关掉） */
const GYRO_DEBUG: boolean = false;

export type GyroValueFn = (value: number, degrees: number) => void;
export type GyroSendFn = () => void;

export class Gyro {
  enabled: boolean = false;
  /** 满量程 = 第一屏那个滑块（转满它 = 摇杆满量程），3–90° */
  rangeDeg: number = 8;
  /** 相对参照姿态的角度（度），正 = 向右 */
  angleDeg: number = 0;
  /** 当前摇杆值：-127 … 0 … 127 */
  lastValue: number = 0;

  onValue: GyroValueFn = (value: number, degrees: number): void => {};
  onSend: GyroSendFn = (): void => {};

  private lastEventAt: number = 0;
  private lastSendAt: number = 0;
  private subscribed: boolean = false;
  private refSubscribed: boolean = false;

  private listener: (data: sensor.GyroscopeResponse) => void = (data: sensor.GyroscopeResponse): void => {
    this.handle(data);
  };

  // ---- 实测用（GYRO_DEBUG 打开时才跑）：ORIENTATION 给度数，用来对单位和符号 ----
  private refBase: number = 0;
  private refDeg: number = 0;
  private refReady: boolean = false;
  private debugAccumDeg: number = 0;   // 不夹紧、不翻符号的原始积分（按 rad/s 假设换算成度）
  private logTick: number = 0;

  private refListener: (data: sensor.OrientationResponse) => void = (data: sensor.OrientationResponse): void => {
    // 我们准备用的轴 = 屏幕法线（和安卓端 AXIS_AUTO 的 axis=2 一致）：alpha 就是绕 Z 的角度，单位就是度
    const comp = data.alpha;
    if (!this.refReady) {
      this.refReady = true;
      this.refBase = comp;
      this.refDeg = 0;
      console.info('[GYRO_DEBUG] 参照基线（ORIENTATION 绕 Z，度）= ' + comp.toFixed(2));
      return;
    }
    this.refDeg = comp - this.refBase;
  };

  /** 返回 '' = 成功；否则是失败原因（模拟器没有陀螺仪也会走到这条） */
  start(): string {
    // 进手柄屏时 initPrefs 和 onPageShow 都会调这里：没有守卫的话同一个回调会被订阅两遍，积分跑两倍
    if (this.subscribed) {
      return '';
    }
    try {
      sensor.on(sensor.SensorId.GYROSCOPE, this.listener);
      this.subscribed = true;
    } catch (e) {
      return '体感开不了：' + (e as Error).message;
    }
    // 参照：ORIENTATION 给的是度数，用它核对陀螺仪的单位（rad/s 还是 deg/s）和符号
    // 参照只用于定标（对单位/符号），平时不订阅：这样也不依赖"应用获取设备方向"那条权限
    if (GYRO_DEBUG) {
      try {
        sensor.on(sensor.SensorId.ORIENTATION, this.refListener);
        this.refSubscribed = true;
      } catch (e) {
        console.warn('拿不到 ORIENTATION 参照：' + (e as Error).message);
      }
    }
    return '';
  }

  stop(): void {
    if (!this.subscribed) {
      return;
    }
    this.subscribed = false;
    try {
      sensor.off(sensor.SensorId.GYROSCOPE, this.listener);
    } catch (e) {
      console.warn('取消陀螺仪监听失败：' + (e as Error).message);
    }
    if (this.refSubscribed) {
      this.refSubscribed = false;
      try {
        sensor.off(sensor.SensorId.ORIENTATION, this.refListener);
      } catch (e) {
        console.warn('取消参照监听失败：' + (e as Error).message);
      }
    }
    this.refReady = false;
  }

  /** 回正：只有陀螺仪时没有绝对姿态，把当前当成 0，从这儿开始重新积分 */
  recenter(): void {
    this.angleDeg = 0;
    this.lastEventAt = 0;
    this.lastValue = 0;
  }

  /**
   * 用哪条轴：屏幕法线（机身 Z）。安卓端走 rotation vector 时（AXIS_AUTO -> axis=2）用的就是这条，
   * 所以"转方向盘"的手感 = 绕屏幕法线转。原来这里用的是"屏幕上看起来竖直那条轴"，手感不一样。
   * 屏幕法线相对机身不变，转屏时也不需要翻符号。
   */
  private gyroAxis(): number {
    return 2;
  }

  private axisComponent(data: sensor.GyroscopeResponse, axis: number): number {
    if (axis === 0) {
      return data.x;
    }
    if (axis === 1) {
      return data.y;
    }
    return data.z;
  }

  private handle(data: sensor.GyroscopeResponse): void {
    if (!this.enabled) {
      return;
    }
    const raw = this.axisComponent(data, this.gyroAxis());
    const rate = raw * ORIENTATION_SIGN;
    // 这里拿不到传感器时间戳（kit 导出的 GyroscopeResponse 只有 x/y/z），所以用本地时钟算 dt
    const nowMs = Date.now();
    if (this.lastEventAt !== 0) {
      const dt = (nowMs - this.lastEventAt) / 1000;
      if (dt > 0 && dt < 0.2 && Math.abs(rate) >= GYRO_DEADZONE_RATE) {
        // rate 已经带符号了，这里不能再乘一次（乘两次 = 负负得正，翻符号就没效果了）
        this.angleDeg += rate * dt * DEG;
      }
      if (GYRO_DEBUG && dt > 0 && dt < 0.2 && Math.abs(data.z) > 0.05) {
        this.debugAccumDeg += data.z * dt * DEG;
      }
      if (GYRO_DEBUG && this.refReady) {
        this.logTick++;
        if (this.logTick % 10 === 0) {
          const ratio = this.refDeg === 0 ? '-' : (this.debugAccumDeg / this.refDeg).toFixed(1);
          console.info('[GYRO_DEBUG] 我们积分(按rad/s)=' + this.debugAccumDeg.toFixed(1) + '° 参照(真度数)=' +
            this.refDeg.toFixed(1) + '° 比值=' + ratio);
        }
      }
    }
    this.lastEventAt = nowMs;

    const deadzoneDeg = Math.max(this.rangeDeg * 0.04, 0.05);
    if (Math.abs(this.angleDeg) < deadzoneDeg) {
      this.angleDeg = 0;
    }
    this.angleDeg = Math.min(Math.max(this.angleDeg, -this.rangeDeg), this.rangeDeg);

    const x = Math.round(this.angleDeg / this.rangeDeg * 127);
    if (x === this.lastValue) {
      return;
    }
    this.lastValue = x;
    this.onValue(x, this.angleDeg);

    const now = Date.now();
    if (now - this.lastSendAt < GYRO_SEND_INTERVAL_MS) {
      return;
    }
    this.lastSendAt = now;
    this.onSend();
  }
}

/** 手柄屏用的单例（第一屏只管开关和幅度，手柄屏负责读） */
export const gyro = new Gyro();
