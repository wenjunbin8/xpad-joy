import { common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';

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

/** 手柄页 / 布局页要沉浸全屏：状态栏和导航条都关掉 */
export async function hideSystemBars(): Promise<string> {
  if (abilityCtx === null) {
    return '没有 ability context';
  }
  try {
    const win = await window.getLastWindow(abilityCtx);
    await win.setWindowSystemBarEnable([]);
    return '';
  } catch (e) {
    return (e as Error).message;
  }
}
