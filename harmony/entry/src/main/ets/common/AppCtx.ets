import { common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { BG, INK } from './Palette';

/**
 * EntryAbility 把 UIAbilityContext 存到这里。
 * 原因：setPreferredOrientation 要的是 ability context；页面里 getUIContext().getHostContext()
 * 拿到的是基类 Context，真机上转屏会失败（手柄页/布局页变竖向就是这么来的）。
 * 失败原因会被页面显示出来，好知道是哪一步不对。
 */
export let abilityCtx: common.UIAbilityContext | null = null;

export function setAbilityCtx(ctx: common.UIAbilityContext): void {
  abilityCtx = ctx;
}

async function getWin(): Promise<window.Window | null> {
  if (abilityCtx === null) {
    return null;
  }
  return await window.getLastWindow(abilityCtx);
}

/** 返回 '' = 成功；否则是失败原因 */
export async function applyOrientation(orientation: window.Orientation): Promise<string> {
  if (abilityCtx === null) {
    return '没有 ability context（EntryAbility 没跑到 onCreate）';
  }
  try {
    const win = await window.getLastWindow(abilityCtx);
    await win.setPreferredOrientation(orientation);
    return '';
  } catch (e) {
    return (e as Error).message;
  }
}

/**
 * 第一屏的系统栏：状态栏留着（刷成深色），导航条关掉。
 * 导航条那块是系统自己画的（浅色主题下是白的），深色界面底下就看着像一条白边；
 * 关掉它 + 页面背景 expandSafeArea 到最底，白条就没了。
 * 手柄页/布局页传 []（两个都关，沉浸式）。
 */
export async function setSystemBars(names: Array<'status' | 'navigation'>): Promise<string> {
  try {
    const win = await getWin();
    if (win === null) {
      return '没有 ability context';
    }
    await win.setWindowSystemBarEnable(names);
    return '';
  } catch (e) {
    return (e as Error).message;
  }
}

/** 手柄页 / 布局页要沉浸全屏：状态栏和导航条都关掉 */
export async function hideSystemBars(): Promise<string> {
  return setSystemBars([]);
}

/**
 * 系统栏默认是白的（浅色主题），界面是深色 → 第一屏上下看着像两条白边。
 * 把系统栏刷成界面同一套颜色（状态栏还在，只是变深色），上边那条就没了。
 * 底下那条靠关导航条 + 页面 expandSafeArea 解决（见 Index.ets）。
 */
export async function syncBarColors(): Promise<string> {
  try {
    const win = await getWin();
    if (win === null) {
      return '没有 ability context';
    }
    const props: window.SystemBarProperties = {
      statusBarColor: BG,
      statusBarContentColor: INK,
      navigationBarColor: BG,
      navigationBarContentColor: INK
    };
    await win.setWindowSystemBarProperties(props);
    return '';
  } catch (e) {
    return (e as Error).message;
  }
}
