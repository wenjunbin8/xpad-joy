import vibrator from '@ohos.vibrator';   // 和 Gyro 同一个原因：kit 的命名空间在真机上可能取到 undefined

/**
 * 收到 {"t":"rumble","left":..,"right":..} 时震马达。
 *
 * 注意：HarmonyOS 的 vibrator 只支持"按时长 / preset 震"（VibrateTime / VibratePreset），
 * 没有左右两个马达，也没有强度参数 —— 电脑端传来的 left/right（0..255 的强度）不能原样传过来。
 * 这里把 max(left, right) 换算成时长：强度越大震得越久（1..255 → 约 20..140ms），
 * 强度本身只能靠系统默认强度 + 时长近似，左右分不清。这是鸿蒙做不到和安卓端一样的地方之一。
 */
const MAX_MS: number = 140;
const MIN_MS: number = 20;
/** 限流：和安卓端一样，120ms 内不重复震 */
const THROTTLE_MS: number = 120;

let lastAt = 0;
let rumbleCount = 0;

export function rumbleTotal(): number {
  return rumbleCount;
}

export function rumble(left: number, right: number): void {
  const strongest = Math.max(left, right);
  if (strongest <= 0) {
    return;
  }
  const now = Date.now();
  if (now - lastAt < THROTTLE_MS) {
    return;
  }
  lastAt = now;
  rumbleCount++;

  // 强度 → 时长：这就是鸿蒙能做到的极限（见上面注释）
  const duration = Math.round(MAX_MS * strongest / 255);
  const ms = Math.max(MIN_MS, Math.min(MAX_MS, duration));
  const effect: vibrator.VibrateTime = { type: 'time', duration: ms };
  const attribute: vibrator.VibrateAttribute = { usage: 'physicalFeedback' };
  try {
    vibrator.startVibration(effect, attribute).then(() => {
    }).catch((e: Error) => {
      // 这台机器可能没有马达 / 不允许震：算了，不影响手柄
      console.warn('震动失败：' + e.message);
    });
  } catch (e) {
    console.warn('震动失败：' + (e as Error).message);
  }
}
