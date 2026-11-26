import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

/**
 * 偏好存储 —— 和安卓端同一个文件、同一批 key（xpadjoy / layout_json、pc_ip、link、gyro、gyro_range、gyro_ref、compact、pc_port、qr_last）。
 * 所以两边的配置文件可以直接互换：安卓 SharedPreferences 写出来的 JSON，鸿蒙这边读得出来，反之也一样。
 */
export const PREFS: string = 'xpadjoy';

let cache: preferences.Preferences | null = null;

export async function openPrefs(ctx: common.Context): Promise<preferences.Preferences> {
  if (cache === null) {
    cache = await preferences.getPreferences(ctx, PREFS);
  }
  return cache;
}

/** ArkTS 不能把 JSON.parse 的结果当接口用，所以取值全部用显式的 typeof 判断 */
export async function getStr(p: preferences.Preferences, key: string, def: string): Promise<string> {
  const v = await p.get(key, def);
  if (typeof v === 'string') {
    return v;
  }
  return def;
}

export async function getNum(p: preferences.Preferences, key: string, def: number): Promise<number> {
  const v = await p.get(key, def);
  if (typeof v === 'number') {
    return v;
  }
  return def;
}

export async function getBool(p: preferences.Preferences, key: string, def: boolean): Promise<boolean> {
  const v = await p.get(key, def);
  if (typeof v === 'boolean') {
    return v;
  }
  return def;
}

export async function put(p: preferences.Preferences, key: string, value: string | number | boolean): Promise<void> {
  await p.put(key, value);
  await p.flush();
}
