import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { setAbilityCtx, syncBarColors } from '../common/AppCtx';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 页面里转屏要靠这个 context（见 common/AppCtx.ets）
    setAbilityCtx(this.context);
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        return;
      }
      // 启动时系统栏默认是白的（浅色主题），先刷成界面同一套颜色，免得第一屏先白一下
      syncBarColors().then((msg: string): void => {
        if (msg !== '') {
          console.warn('系统栏颜色没设置成功：' + msg);
        }
      });
    });
  }
}
