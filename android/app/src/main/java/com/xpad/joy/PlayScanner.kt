package com.xpad.joy

import android.content.Context
import android.content.pm.PackageManager
import android.media.Image
import android.util.Log
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage

/**
 * 主解码器：请求 Google Play 服务代为扫（MLS —— 模型和推理都在 `com.google.android.gms` 进程里跑，
 * APK 里只有接口，所以这块只有几十 KB，而且比 zxing 快、对斜拍/模糊更稳）。
 *
 * 请求失败（没装 Google Play 服务 / 版本太旧 / MLS 模块没下载 / 处理这帧出错）→ `active` 变 false，
 * 调用方改用 `QrScanner`（本机相机 + zxing）。这就是"Play 服务请求失败才调用原相机"。
 */
class PlayScanner(
    private val context: Context,
    private val onHit: (String) -> Unit,
    private val onFrameDone: () -> Unit,
) {

    /** true = 这帧走 Play 服务；false = 走本机相机（zxing） */
    var active = false
        private set

    var playVersion = 0
        private set

    // 界面要读这些计数，QrScanner 那条也要记数，所以这几个不设 private set
    var reason = ""

    var framesPlay = 0
        private set

    var framesCamera = 0

    var hitsPlay = 0
        private set

    private var scanner: BarcodeScanner? = null

    /**
     * 请求 Google Play 服务。返回 true = 用 Play 服务；返回 false = 请求失败，调用方走相机那条。
     * 失败原因存进 `reason`，界面会显示。失败还会记进 prefs（`qr_force_camera`）：
     * 下次进这一页直接跳过 Play 服务，免得每次进来都在同一步上出错。
     */
    fun start(): Boolean {
        try {
            playVersion = playServicesVersion()
            if (playVersion == 0) {
                markUnavailable("这台机器没有 Google Play 服务（找不到 com.google.android.gms）→ 用本机相机")
                active = false
                return false
            }
            val options = BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
            scanner = BarcodeScanning.getClient(options)
            active = true
            reason = "Google Play 服务版本 $playVersion（MLS 代为解码）"
            return true
        } catch (t: Throwable) {
            Log.e(TAG, "请求 Google Play 服务失败", t)
            markUnavailable("请求 Google Play 服务失败：${t.message ?: t.javaClass.simpleName} → 改用本机相机（zxing）")
            return false
        }
    }

    /**
     * 处理一帧。返回 true = 这帧 Play 服务接了（异步，Image 由这里 close）；
     * 返回 false = 没接，调用方要用 zxing 解，并自己 close。
     * 这里不能往外抛：调用方在后台线程上，抛出去就是闪退。
     */
    fun scan(image: Image, rotationDegrees: Int): Boolean {
        val client = scanner ?: return false
        val input = try {
            InputImage.fromMediaImage(image, rotationDegrees)
        } catch (t: Throwable) {
            markUnavailable("Play 服务收不了这帧（${t.message ?: t.javaClass.simpleName}）→ 改用本机相机（zxing）")
            Log.e(TAG, "InputImage 失败", t)
            return false
        }
        val task = try {
            client.process(input)
        } catch (t: Throwable) {
            markUnavailable("Play 服务处理不了这帧（${t.message ?: t.javaClass.simpleName}）→ 改用本机相机（zxing）")
            Log.e(TAG, "process() 失败", t)
            return false
        }
        framesPlay++
        task.addOnCompleteListener { completed ->
            try {
                if (completed.isSuccessful) {
                    val barcodes = completed.result
                    if (barcodes != null) {
                        for (barcode in barcodes) {
                            val text = barcode.rawValue ?: barcode.displayValue
                            if (!text.isNullOrEmpty()) {
                                hitsPlay++
                                try {
                                    onHit(text)
                                } catch (inner: Throwable) {
                                    Log.e(TAG, "onHit 出错", inner)
                                }
                                break
                            }
                        }
                    }
                } else {
                    val ex = completed.exception
                    markUnavailable("Play 服务处理这帧失败：${ex?.message ?: ex?.javaClass?.simpleName ?: "未知"}（改用本机相机 zxing）")
                    Log.w(TAG, reason, ex)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "Play 服务回调出错", t)
                reason = "Play 服务回调出错：${t.message ?: t.javaClass.simpleName}"
            } finally {
                try {
                    image.close()
                } catch (ignored: Exception) {
                    // 图片可能已经被 close 过
                }
                try {
                    onFrameDone()
                } catch (inner: Throwable) {
                    Log.e(TAG, "onFrameDone 出错", inner)
                }
            }
        }
        return true
    }

    fun close() {
        try {
            scanner?.close()
        } catch (ignored: Exception) {
            // 关不上就算了
        }
        scanner = null
    }

    private fun playServicesVersion(): Int {
        return try {
            val info = context.packageManager.getPackageInfo("com.google.android.gms", 0)
            info.versionCode
        } catch (t: Throwable) {
            0
        }
    }

    /** 记原因 + 记住"这台机器上 Play 服务这条路走不通"，下次进来直接用相机 */
    private fun markUnavailable(message: String) {
        active = false
        reason = message
        try {
            context.getSharedPreferences("xpadjoy", Context.MODE_PRIVATE).edit()
                .putBoolean("qr_force_camera", true)
                .apply()
        } catch (ignored: Exception) {
            // 存不了就算了，这一局照样退回相机
        }
    }

    companion object {
        private const val TAG = "XjoyQR"
    }
}
