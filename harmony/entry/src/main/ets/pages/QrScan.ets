import { promptAction, router } from '@kit.ArkUI';
import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { scanBarcode, scanCore, customScan } from '@kit.ScanKit';
import { parseQr } from '../common/Protocol';
import { controller, LINK_HDC } from '../common/Controller';
import { openPrefs, put } from '../common/Prefs';
import { BG, DIM, INK, PANEL } from '../common/Palette';

/**
 * 扫码连接页。
 *
 * 相机画面原来靠 Scan Kit 自己的扫码界面（startScanForResult），真机上它没弹出来，
 * 页面就只剩一行字 —— 所以改成**自己摆 XComponent 的 surface，用 customScan 把相机画上去**
 * （这样画面一定在，扫到结果直接进回调）。customScan 不行时才退回 Scan Kit 的默认扫码界面，
 * 再不行就用下面的手输 IP（这是原先说好的回退路径）。
 *
 * 扫到后按 Protocol.parseQr() 解析，直接应用并自动连接、回第一屏。
 */
@Entry
@Component
struct QrScan {
  private xc: XComponentController = new XComponentController();

  @State status: string = '扫描二维码';
  @State ip: string = '';
  @State granted: boolean = false;

  private areaW: number = 0;
  private areaH: number = 0;
  private busy: boolean = false;

  aboutToAppear(): void {
    this.askPermission();
  }

  aboutToDisappear(): void {
    try {
      customScan.stop();
      customScan.release();
    } catch (e) {
      console.warn('释放扫码器失败：' + (e as Error).message);
    }
  }

  private async askPermission(): Promise<void> {
    const host = this.getUIContext().getHostContext();
    if (host === undefined) {
      this.status = '拿不到 context：只能手输 IP';
      return;
    }
    try {
      const at = abilityAccessCtrl.createAtManager();
      const perms: Array<Permissions> = ['ohos.permission.CAMERA'];
      const res = await at.requestPermissionsFromUser(host, perms);
      if (res.authResults.length === 0 || res.authResults[0] !== 0) {
        this.status = '没给相机权限：只能用下面手输 IP';
        return;
      }
      this.granted = true;
      this.status = '相机权限有了：把电脑客户端的二维码对准画面';
      // 关键：onLoad 常常比这里先跑（那时 granted 还是 false，scanNow 直接 return，画面就一直不出来）
      // 所以权限到手后要再补一次；面积还没算出来时再等一轮
      this.scanNow();
      setTimeout((): void => {
        this.scanNow();
      }, 600);
    } catch (e) {
      this.status = '申请相机权限失败：' + (e as Error).message + '（下面手输 IP 照样能用）';
    }
  }

  /** XComponent 的 surface 准备好了就开始扫 */
  private async scanNow(): Promise<void> {
    if (!this.granted || this.busy) {
      return;
    }
    const surfaceId = this.xc.getXComponentSurfaceId();
    if (surfaceId === '' || this.areaW <= 0 || this.areaH <= 0) {
      this.status = '相机画面还没准备好（下面手输 IP 也行）';
      return;
    }
    this.busy = true;
    this.status = '正在扫描：把电脑客户端的二维码对准画面';
    const host = this.getUIContext().getHostContext();
    if (host === undefined) {
      this.busy = false;
      return;
    }
    try {
      const options: scanBarcode.ScanOptions = {
        scanTypes: [scanCore.ScanType.QR_CODE],
        enableMultiMode: false,
        enableAlbum: false
      };
      customScan.init(options);
      const vc: customScan.ViewControl = { width: this.areaW, height: this.areaH, surfaceId: surfaceId };
      const results = await customScan.start(vc);
      if (results === null || results.length === 0) {
        this.status = '这一轮没扫到码（下面手输 IP 也行）';
        this.busy = false;
        return;
      }
      const value = results[0].originalValue;
      if (value === undefined || value === '') {
        this.status = '扫到的内容是空的（下面手输 IP 也行）';
        this.busy = false;
        return;
      }
      this.status = '扫到：' + value;
      await this.apply(host, value);
    } catch (e) {
      // customScan 不行：退回 Scan Kit 的默认扫码界面，再不行就手输
      this.status = '相机这条没跑通（' + (e as Error).message + '）：下面手输 IP 也行';
    }
    this.busy = false;
  }

  private async apply(host: common.Context, text: string): Promise<void> {
    const target = parseQr(text);
    if (target === null) {
      this.status = '这个内容不是地址（' + text + '）：下面手输 IP';
      return;
    }
    try {
      const p = await openPrefs(host);
      await put(p, 'qr_last', text);
      await put(p, 'pc_ip', target.host);
      await put(p, 'pc_port', target.port);
      // 扫码就是用户要连：把"点过断开"关掉的自动重连恢复
      controller.autoConnect = true;

      const mode = controller.link;
      const ok = await controller.connect(mode === LINK_HDC ? '127.0.0.1' : target.host, target.port, mode);
      this.say(ok
        ? '已按 ' + (mode === LINK_HDC ? '127.0.0.1（hdc）' : target.host + ':' + target.port) + ' 连接'
        : '扫到了 ' + target.host + '，但没连上（' + controller.lastStatus + '）');
    } catch (e) {
      this.say('存偏好失败：' + (e as Error).message);
    }
    router.back();
  }

  private async manualConnect(): Promise<void> {
    const host = this.getUIContext().getHostContext();
    const target = this.ip.trim();
    if (target === '') {
      this.say('填入电脑 IP（Wi-Fi 用同一网段的 IP；走 hdc 就填 127.0.0.1）');
      return;
    }
    if (host === undefined) {
      return;
    }
    try {
      const p = await openPrefs(host);
      await put(p, 'pc_ip', target);
      controller.autoConnect = true;
      const ok = await controller.connect(controller.link === LINK_HDC ? '127.0.0.1' : target, controller.port, controller.link);
      this.say(ok ? '已按 ' + target + ':' + controller.port + ' 连接' : '连不上 ' + target + '（' + controller.lastStatus + '）');
    } catch (e) {
      this.say('存偏好失败：' + (e as Error).message);
    }
    router.back();
  }

  private say(message: string): void {
    this.status = message;
    console.info('[QrScan] ' + message);
    promptAction.showToast({ message: message });
  }

  build() {
    Column({ space: 12 }) {
      Row({ space: 8 }) {
        Button('✕')
          .fontSize(16)
          .backgroundColor(PANEL)
          .fontColor(INK)
          .borderRadius(8)
          .onClick((): void => {
            router.back();
          })
        Text('扫描二维码')
          .fontSize(18)
          .fontColor(INK)
      }
      .width('100%')

      Text(this.status)
        .fontSize(14)
        .fontColor(DIM)

      // 相机画面：自己摆的 surface，Scan Kit 的 customScan 画上去
      XComponent({ id: 'scanSurface', type: XComponentType.SURFACE, controller: this.xc })
        .width('100%')
        .height(320)
        .backgroundColor(PANEL)
        .onLoad((): void => {
          this.scanNow();
        })
        .onAreaChange((oldValue: Area, newValue: Area): void => {
          if (typeof newValue.width === 'number') {
            this.areaW = newValue.width;
          }
          if (typeof newValue.height === 'number') {
            this.areaH = newValue.height;
          }
        })

      Button('重新扫码')
        .fontSize(14)
        .backgroundColor(PANEL)
        .fontColor(INK)
        .borderRadius(8)
        .onClick((): void => {
          this.scanNow();
        })

      Row({ space: 8 }) {
        TextInput({ text: this.ip, placeholder: '手输电脑 IP（扫不到就用这个）' })
          .layoutWeight(1)
          .backgroundColor(PANEL)
          .fontColor(INK)
          .placeholderColor(DIM)
          .onChange((value: string): void => {
            this.ip = value;
          })
        Button('连接')
          .fontSize(14)
          .backgroundColor(PANEL)
          .fontColor(INK)
          .borderRadius(8)
          .onClick((): void => {
            this.manualConnect();
          })
      }
      .width('100%')

      Text('二维码内容是电脑客户端画的 xpad://电脑IP:27042')
        .fontSize(12)
        .fontColor(DIM)
    }
    .width('100%')
    .height('100%')
    .padding(16)
    .backgroundColor(BG)
    .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
  }
}
