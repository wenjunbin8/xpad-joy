package com.xpad.joy

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.StreamConfigurationMap
import android.media.Image
import android.media.Image.Plane
import android.media.ImageReader
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.util.Range
import android.util.Size
import android.view.Surface
import android.widget.Button
import android.widget.Toast

/**
 * 扫码连接页 —— 这一页只放相机画面（别的都按你的要求删了）。
 *
 * 画面由 Activity 自己画：每帧把 Y 平面按 sensor 角度转成 320×240 灰度小图贴到 ImageView。
 * 不走 SurfaceView / TextureView：这台机器硬件加速关着（TextureView 一 inflate 就抛 InflateException），
 * SurfaceView 的画面又在窗口下面、被背景挡住，所以那一块是黑的。自己画那条不依赖硬件加速。
 *
 * 解码先请求 Google Play 服务（`PlayScanner`，MLS）；Play 服务请求失败（没装 / 版本太旧 /
 * MLS 模块没下好 / 处理这帧出错）才退回本机相机 + zxing（`QrScanner`）。所以相机权限是两条都要用的。
 *
 * 扫到之后：存 prefs（`qr_last`）→ 自动连接 → 回第一屏（第一屏状态行只显示已连接 / 未连接；扫码记录进 logcat）。
 * 走 ADB 时不能直接用扫来的 IP —— adb reverse 只把电脑端口转发到手机的 127.0.0.1，所以这条只能用
 * 127.0.0.1，扫到的地址只作为 Wi-Fi 那条的候选。
 */
class QrScanActivity : Activity() {

    private val TAG = "XjoyQR"
    private val PERMISSION_REQUEST = 1
    private val MIN_FRAME_MS = 150L        // 解码这条：zxing 一帧 10–80ms，再快就只是发热
    private val PREVIEW_MS = 33L           // 画面这条：33ms = 30 帧/秒（相机预览流一般也就 30 帧，60 要 HAL 支持）

    private lateinit var prefs: SharedPreferences
    private lateinit var preview: ScanPreviewView
    private lateinit var flashButton: Button

    private val ui = Handler(Looper.getMainLooper())
    private var bgThread: HandlerThread? = null
    private var bgHandler: Handler? = null
    private var decodeThread: HandlerThread? = null
    private var decodeHandler: Handler? = null

    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null            // 解码那条流（大：1280×720）
    private var previewReader: ImageReader? = null     // 画面那条流（小：640×480，转得快才跑得满 30 帧）
    private var cameraManager: CameraManager? = null
    private var characteristics: CameraCharacteristics? = null
    private var cameraId = ""
    private var sensorOrientation = 0
    private var frameWidth = 640
    private var frameHeight = 480
    private var drawWidth = 640
    private var drawHeight = 480
    private var flashAvailable = false
    private var torchOn = false
    private var requestBuilder: CaptureRequest.Builder? = null

    @Volatile
    private var busy = false
    private var lastFrameAt = 0L
    private var forceCamera = false        // prefs `qr_force_camera`：上次 Play 服务出过错 → 这次直接走 zxing

    private var lastText = ""
    private var hitsCamera = 0
    private var lastHitAt = 0L

    private var previewPixels = IntArray(0)
    private var previewBitmap: Bitmap? = null
    private var yBuf = ByteArray(0)
    private var uBuf = ByteArray(0)
    private var vBuf = ByteArray(0)
    private var lastPreviewAt = 0L
    private var pendingUi = false

    // 30 帧/秒的预算只有 33ms：把每像素的乘法换成查表，色度按 2×2 块算一次
    private val lutY = IntArray(256)      // 1192 * (Y - 16)
    private val lutUg = IntArray(256)     // -400 * (U - 128)
    private val lutUb = IntArray(256)     // 2065 * (U - 128)
    private val lutVr = IntArray(256)     // 1634 * (V - 128)
    private val lutVg = IntArray(256)     // -832 * (V - 128)
    private val clampTbl = IntArray(1024) // 索引 = (值 shr 10) + 320，可能落到的范围是 -275..480

    init {
        for (i in 0 until 256) {
            lutY[i] = 1192 * (i - 16)
            lutUg[i] = -400 * (i - 128)
            lutUb[i] = 2065 * (i - 128)
            lutVr[i] = 1634 * (i - 128)
            lutVg[i] = -832 * (i - 128)
        }
        for (i in clampTbl.indices) {
            val value = i - 320
            clampTbl[i] = if (value < 0) 0 else if (value > 255) 255 else value
        }
    }

    private val play = PlayScanner(this, ::onHit, ::onFrameDone)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashLog.install(this)
        try {
            setContentView(R.layout.activity_qr)
            prefs = getSharedPreferences("xpadjoy", Context.MODE_PRIVATE)
            preview = findViewById(R.id.qr_preview) as ScanPreviewView
            flashButton = findViewById(R.id.qr_flash) as Button

            preview.setBackgroundColor(0xFF1B2128.toInt())

            forceCamera = prefs.getBoolean("qr_force_camera", false)
            torchOn = prefs.getBoolean("qr_torch", false)
            flashButton.text = "闪光灯 " + (if (torchOn) "开" else "关")

            findViewById<Button>(R.id.qr_close).setOnClickListener { finish() }
            flashButton.setOnClickListener {
                torchOn = !torchOn
                try {
                    prefs.edit().putBoolean("qr_torch", torchOn).apply()
                } catch (t: Throwable) {
                    toast("存不了闪光灯开关：${t.message ?: t.javaClass.simpleName}")
                }
                flashButton.text = "闪光灯 " + (if (torchOn) "开" else "关")
                applyTorch()
            }

            if (hasCameraPermission()) {
                startScan()
            } else {
                requestPermissions(arrayOf(Manifest.permission.CAMERA), PERMISSION_REQUEST)
            }
        } catch (t: Throwable) {
            // 进这一页就出错：以前这里直接抛出去 = 闪退
            Log.e(TAG, "扫码页打不开", t)
            CrashLog.record(this, t)
            toast("扫码页打不开：${t.message ?: t.javaClass.simpleName}")
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        try {
            if (requestCode == PERMISSION_REQUEST && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startScan()
            } else {
                toast("相机权限被拒：设置 → 应用 → Xpad-joy → 权限 → 相机，再进来这一页，或者回第一屏手输地址")
            }
        } catch (t: Throwable) {
            Log.e(TAG, "权限回调出错", t)
            CrashLog.record(this, t)
            toast("权限回调出错：${t.message ?: t.javaClass.simpleName}")
        }
    }

    override fun onDestroy() {
        try {
            session?.close()
        } catch (ignored: Exception) {
            // 已经关了
        }
        session = null
        try {
            camera?.close()
        } catch (ignored: Exception) {
            // 已经关了
        }
        camera = null
        try {
            reader?.close()
        } catch (ignored: Exception) {
            // 已经关了
        }
        reader = null
        try {
            previewReader?.close()
        } catch (ignored: Exception) {
            // 已经关了
        }
        previewReader = null
        pendingUi = false
        requestBuilder = null
        play.close()
        decodeThread?.quitSafely()
        decodeThread = null
        bgThread?.quitSafely()
        bgThread = null
        ui.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    // ---------------- 取帧 ----------------

    private fun hasCameraPermission(): Boolean =
        checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun startScan() {
        if (bgThread != null) return
        try {
            bgThread = HandlerThread("xjoy-qr")
            bgThread?.start()
            bgHandler = Handler(bgThread?.looper ?: Looper.getMainLooper())
            decodeThread = HandlerThread("xjoy-decode")
            decodeThread?.start()
            decodeHandler = Handler(decodeThread?.looper ?: Looper.getMainLooper())
            if (!forceCamera) play.start()      // 上次 Play 服务出过错 → 这次连请求都不发，直接走相机
            openCamera()
        } catch (t: Throwable) {
            Log.e(TAG, "启动扫码失败", t)
            CrashLog.record(this, t)
            toast("启动扫码失败：${t.message ?: t.javaClass.simpleName}")
        }
    }

    private fun openCamera() {
        try {
            val manager = getSystemService(CameraManager::class.java)
            if (manager == null) {
                toast("读不到相机服务（CameraManager）")
                return
            }
            cameraManager = manager
            val ids = manager.cameraIdList
            if (ids.isEmpty()) {
                toast("这台机器没有可用摄像头")
                return
            }
            var picked: String? = null
            for (id in ids) {
                val characteristics = manager.getCameraCharacteristics(id)
                val facing = characteristics.get(CameraCharacteristics.LENS_FACING) as Int?
                if (facing == CameraMetadata.LENS_FACING_BACK) {
                    picked = id
                    break
                }
            }
            if (picked == null) picked = ids[0]
            val characteristics = manager.getCameraCharacteristics(picked)
            sensorOrientation = (characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) as Int?) ?: 0
            flashAvailable = (characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) as Boolean?) == true
            if (torchOn && !flashAvailable) {
                torchOn = false
                flashButton.text = "闪光灯（没有）"
            }
            pickSize(characteristics)
            this.characteristics = characteristics
            cameraId = picked
            // 只挂 ImageReader：画面由 drawPreview 自己画，不需要相机的预览 surface
            startPreview()
        } catch (t: Throwable) {
            Log.e(TAG, "打不开相机", t)
            toast("打不开相机：${t.message ?: t.javaClass.simpleName}")
        }
    }

    private fun pickSize(characteristics: CameraCharacteristics) {
        try {
            val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) as StreamConfigurationMap?
            val sizes = map?.getOutputSizes(ImageFormat.YUV_420_888) ?: return
            if (sizes.isEmpty()) return

            // 两条流分开挑：解码要大概 1280×720（离得远、码小才解得动），画面要小（30 帧/秒的预算只有 33ms）。
            // 画面 640×480 = 30.7 万像素/帧，查表 + 块色度大概 10–15ms，跑得满；1280×720 逐像素乘法要 25–40ms，只能 15–20 帧。
            val draw = closest(sizes, 640L * 480L)
            val decode = closest(sizes, 1280L * 720L)
            if (draw != null) {
                drawWidth = draw.width
                drawHeight = draw.height
            }
            if (decode != null) {
                frameWidth = decode.width
                frameHeight = decode.height
            }
        } catch (ignored: Exception) {
            // 用默认的 640×480
        }
    }

    private fun closest(sizes: Array<Size>, targetArea: Long): Size? {
        var best: Size? = null
        var bestDiff = Long.MAX_VALUE
        for (size in sizes) {
            val area = size.width.toLong() * size.height
            if (area < 320L * 240L) continue
            val diff = if (area > targetArea) area - targetArea else targetArea - area
            if (best == null || diff < bestDiff) {
                bestDiff = diff
                best = size
            }
        }
        return best
    }

    /** 预览帧率：很多 HAL 为了省电把预览压到 15–20 帧，这里把目标帧率抬到 30（有 60 的 range 就用 60） */
    private fun pickFps(characteristics: CameraCharacteristics, request: CaptureRequest.Builder) {
        try {
            @Suppress("UNCHECKED_CAST")
            val ranges = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) as Array<Range<Int>>?
            if (ranges == null || ranges.isEmpty()) return
            var best: Range<Int>? = null
            for (range in ranges) {
                if (best == null || range.getUpper() > best.getUpper()) best = range
            }
            if (best != null && best.getUpper() >= 30) request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, best)
        } catch (ignored: Exception) {
            // 有些 HAL 不让设目标帧率，忽略
        }
    }

    private fun startPreview() {
        val manager = cameraManager ?: return
        if (cameraId.isEmpty()) return
        try {
            // 画面那条流：小、消费快（每帧只转像素，不等解码）
            previewReader = ImageReader.newInstance(drawWidth, drawHeight, ImageFormat.YUV_420_888, 4)
            previewReader?.setOnImageAvailableListener({ source ->
                val image = source.acquireLatestImage()
                if (image != null) {
                    drawPreview(image, sensorOrientation)
                    closeQuietly(image)
                }
            }, bgHandler)

            // 解码那条流：大，单独一条线程；解不过来就直接丢这一帧，不占着取帧
            reader = ImageReader.newInstance(frameWidth, frameHeight, ImageFormat.YUV_420_888, 3)
            reader?.setOnImageAvailableListener({ source ->
                val image = source.acquireLatestImage()
                if (image != null) handleDecodeFrame(image)
            }, decodeHandler)
            // openCamera 是异步的：真正可用要等 StateCallback.onOpened，所以这里不接返回值
            manager.openCamera(cameraId, cameraState, bgHandler)
        } catch (t: Throwable) {
            Log.e(TAG, "开相机失败", t)
            toast("开相机失败：${t.message ?: t.javaClass.simpleName}（可能被别的 App 占着）")
        }
    }

    private val cameraState = object : CameraDevice.StateCallback() {
        override fun onOpened(device: CameraDevice) {
            camera = device
            startRepeating(device)
        }

        override fun onDisconnected(device: CameraDevice) {
            device.close()
            camera = null
            toast("相机被系统收走了（可能被别的 App 占用）：退出去再进来这一页")
        }

        override fun onError(device: CameraDevice, error: Int) {
            device.close()
            camera = null
            toast("相机出错（code $error）：退出去再进来这一页")
        }
    }

    private fun startRepeating(device: CameraDevice) {
        try {
            val readerSurface = reader?.surface
            val drawSurface = previewReader?.surface
            if (readerSurface == null || drawSurface == null) {
                toast("没有 ImageReader：解不了帧")
                return
            }
            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
            request.addTarget(readerSurface)
            request.addTarget(drawSurface)
            request.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO)
            val characteristics = this.characteristics
            if (characteristics != null) pickFps(characteristics, request)
            requestBuilder = request
            if (flashAvailable) {
                // 相机被我们自己开着，所以不能用 setTorchMode（那条要求相机没被占用）：走 repeating request 的 FLASH_MODE
                request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                request.set(CaptureRequest.FLASH_MODE, if (torchOn) CaptureRequest.FLASH_MODE_TORCH else CaptureRequest.FLASH_MODE_OFF)
            }

            val targets = ArrayList<Surface>()
            targets.add(readerSurface)
            targets.add(drawSurface)

            device.createCaptureSession(targets, object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(configured: CameraCaptureSession) {
                    if (camera == null) return
                    session = configured
                    try {
                        // setRepeatingRequest 要的是 CaptureRequest，不是 Builder：先 build()
                        configured.setRepeatingRequest(request.build(), null, bgHandler)
                    } catch (t: Throwable) {
                        Log.e(TAG, "预览循环失败", t)
                        toast("预览循环失败：${t.message ?: t.javaClass.simpleName}")
                    }
                }

                override fun onConfigureFailed(configured: CameraCaptureSession) {
                    toast("预览配置失败：相机可能被别的 App 占着")
                }
            }, bgHandler)
        } catch (t: Throwable) {
            Log.e(TAG, "建预览会话失败", t)
            toast("建预览会话失败：${t.message ?: t.javaClass.simpleName}")
        }
    }

    private fun applyTorch() {
        try {
            if (!flashAvailable) {
                toast("这个摄像头没有闪光灯")
                return
            }
            val builder = requestBuilder ?: return
            val currentSession = session ?: return
            builder.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
            builder.set(CaptureRequest.FLASH_MODE, if (torchOn) CaptureRequest.FLASH_MODE_TORCH else CaptureRequest.FLASH_MODE_OFF)
            currentSession.setRepeatingRequest(builder.build(), null, bgHandler)
        } catch (t: Throwable) {
            Log.e(TAG, "闪光灯设不了", t)
            toast("闪光灯设不了：${t.message ?: t.javaClass.simpleName}")
        }
    }

    // ---------------- 解帧 + 画面 ----------------

    /**
     * 解码这条流。解不过来就直接丢这一帧 —— 画面那条流不受影响，这是帧率能不能跑满 30 的关键。
     * Play 服务接下了这帧就由它在回调里 close + 清 busy（onFrameDone）。
     */
    private fun handleDecodeFrame(image: Image?) {
        if (image == null) return
        try {
            val now = SystemClock.elapsedRealtime()
            if (busy || now - lastFrameAt < MIN_FRAME_MS) {
                closeQuietly(image)
                return
            }
            lastFrameAt = now
            busy = true

            if (!forceCamera && play.active && play.scan(image, sensorOrientation)) return

            val text = QrScanner.decode(image, sensorOrientation)
            play.framesCamera++
            if (text != null) {
                hitsCamera++
                onHit(text)
            }
            closeQuietly(image)
        } catch (t: Throwable) {
            // 后台线程上抛出去就是闪退：记下来，继续跑
            Log.e(TAG, "解帧出错", t)
            CrashLog.record(this, t)
            play.framesCamera++
            toast("解帧出错：${t.message ?: t.javaClass.simpleName}")
            closeQuietly(image)
        }
        busy = false
    }

    /**
     * 把 YUV_420_888 转成彩色图（按 sensor 角度转正），贴到 ScanPreviewView。
     *
     * 要跑满 30 帧/秒，每帧只有 33ms 的预算，所以省两处：
     *  - 每像素的乘法换成查表（`lutY` / `lutU*` / `lutV*` / `clampTbl`）；
     *  - 色度按 2×2 块算一次（4:2:0 本来就是半分辨率），块里 4 个像素只算亮度。
     * 缓冲和位图都复用；`setPixels` 在 UI 线程做。
     * 仍然是"同一个源像素"的对应关系：色度块 (cy, cx) 对应亮度像素 (2cy, 2cx) —— 之前错在亮度取 (y,x)、色度取 (2y,2x)，画面就成了灰图 + 随机色斑。
     */
    private fun drawPreview(image: Image, rotationDegrees: Int) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastPreviewAt < PREVIEW_MS) return
            lastPreviewAt = now

            val planes = image.planes
            if (planes.size < 3) return
            val yPlane = planes[0]
            val uPlane = planes[1]
            val vPlane = planes[2]

            val yRow = yPlane.rowStride
            val uRow = uPlane.rowStride
            val vRow = vPlane.rowStride
            val uPix = uPlane.pixelStride
            val vPix = vPlane.pixelStride
            if (yRow <= 0 || uRow <= 0 || vRow <= 0 || uPix <= 0 || vPix <= 0) return

            val sw = image.width
            val sh = image.height
            if (sw < 2 || sh < 2) return

            yBuf = readPlane(yPlane, yBuf)
            uBuf = readPlane(uPlane, uBuf)
            vBuf = readPlane(vPlane, vBuf)

            val rot = ((rotationDegrees % 360) + 360) % 360
            val outW = if (rot == 90 || rot == 270) sh else sw
            val outH = if (rot == 90 || rot == 270) sw else sh
            if (previewPixels.size != outW * outH) previewPixels = IntArray(outW * outH)

            val chromaRows = smaller(sh / 2, uBuf.size / uRow)
            val chromaCols = smaller(sw / 2, uRow / uPix)
            if (chromaRows <= 0 || chromaCols <= 0) return

            for (cy in 0 until chromaRows) {
                val uBase = cy * uRow
                val vBase = cy * vRow
                for (cx in 0 until chromaCols) {
                    val ui = uBase + cx * uPix
                    val vi = vBase + cx * vPix
                    if (ui >= uBuf.size || vi >= vBuf.size) continue

                    // 块色度：一次算好三个分量，块里 4 个像素共用（4:2:0 本来就是半分辨率）
                    val ub = lutUg[uBuf[ui].toInt() and 0xFF]
                    val bb = lutUb[uBuf[ui].toInt() and 0xFF]
                    val rb = lutVr[vBuf[vi].toInt() and 0xFF]
                    val gb = lutVg[vBuf[vi].toInt() and 0xFF]

                    for (dy in 0 until 2) {
                        val sy = cy * 2 + dy
                        val rowOff = sy * yRow
                        if (rowOff >= yBuf.size) continue

                        // 这一行（2 个像素）在输出数组里的起点和步进：映射是仿射的，步进固定
                        // 列是 cx（色度块列），行是 cy —— 之前这里写成 cy，只有 cx==cy 的块写对，所以画面只剩一条对角线
                        var idx = 0
                        var step = 1
                        when (rot) {
                            90 -> { idx = cx * 2 * outW + (sh - 1 - sy); step = outW }   // 列方向在输出里是"往下走"，所以步进是 outW
                            180 -> { idx = (sh - 1 - sy) * outW + (sw - 1 - cx * 2); step = -1 }
                            270 -> { idx = (sw - 1 - cx * 2) * outW + sy; step = -outW }
                            else -> { idx = sy * outW + cx * 2; step = 1 }
                        }

                        for (dx in 0 until 2) {
                            val at = idx + dx * step
                            if (at < 0 || at >= previewPixels.size) continue
                            val yi = rowOff + cx * 2 + dx
                            if (yi >= yBuf.size) continue
                            val c = lutY[yBuf[yi].toInt() and 0xFF]
                            previewPixels[at] = -0x1000000 or
                                (clampTbl[((c + rb) shr 10) + 320] shl 16) or
                                (clampTbl[((c + gb + ub) shr 10) + 320] shl 8) or
                                clampTbl[((c + bb) shr 10) + 320]
                        }
                    }
                }
            }

            var bitmap = previewBitmap
            if (bitmap == null || bitmap.width != outW || bitmap.height != outH) {
                bitmap = Bitmap.createBitmap(outW, outH, Bitmap.Config.ARGB_8888)
                previewBitmap = bitmap
            }
            val target = bitmap
            if (pendingUi) return          // UI 还没画完上一帧：别把队列堆满（30 帧/秒时很容易堆）
            pendingUi = true
            ui.post {
                try {
                    pendingUi = false
                    target.setPixels(previewPixels, 0, outW, 0, 0, outW, outH)
                    if (::preview.isInitialized) {
                        preview.bitmap = target
                        preview.invalidate()
                    }
                } catch (ignored: Exception) {
                    // 页面已经关了
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "画画面出错", t)
        }
    }

    /** 平面的 buffer 位置不一定从 0 开始，先 rewind 再读；数组不够长才 new */
    private fun readPlane(plane: Plane, dst: ByteArray): ByteArray {
        val buffer = plane.buffer
        buffer.rewind()
        val n = buffer.remaining()
        val target = if (dst.size < n) ByteArray(n) else dst
        buffer.get(target, 0, n)
        return target
    }

    private fun smaller(a: Int, b: Int): Int = if (a < b) a else b

    private fun closeQuietly(image: Image) {
        try {
            image.close()
        } catch (ignored: Exception) {
            // 已经关了
        }
    }

    private fun onFrameDone() {
        busy = false
    }

    // ---------------- 扫到之后 ----------------

    private fun onHit(text: String) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (text == lastText && now - lastHitAt < 1200) return   // 同一个码连扫，别刷屏
            lastText = text
            lastHitAt = now
            prefs.edit().putString("qr_last", text).apply()
            try {
                val vibrator = getSystemService(android.os.Vibrator::class.java)
                if (vibrator != null && vibrator.hasVibrator()) vibrator.vibrate(60)
            } catch (ignored: Exception) {
                // 震不了就算了
            }
            val parsed = Protocol.parseQr(text)
            if (parsed == null) {
                toast("扫到的内容里没有地址：$text（电脑客户端那个二维码内容应是 xpad://IP:端口）")
                return
            }
            // 扫到 → 括号变绿 + 自动连 + 回第一屏（第一屏状态行只显示已连接/未连接；扫码记录在 logcat）
            ui.post {
                if (::preview.isInitialized) {
                    preview.hit = true
                    preview.invalidate()
                }
                applyTo(parsed)
                ui.postDelayed({ finish() }, 500)
            }
        } catch (t: Throwable) {
            Log.e(TAG, "扫到后的处理出错", t)
            CrashLog.record(this, t)
            toast("扫到后的处理出错：${t.message ?: t.javaClass.simpleName}")
        }
    }

    private fun applyTo(parsed: Pair<String, Int>) {
        val scannedIp = parsed.first
        val scannedPort = parsed.second
        prefs.edit().putInt("pc_port", scannedPort).apply()
        Controller.port = scannedPort
        // 扫码就是用户要连：把「点过断开」关掉的自动重连恢复
        Controller.autoConnect = true

        if (Controller.link == Controller.LINK_ADB) {
            // adb 只转发到本机：这条只能用 127.0.0.1，扫来的 IP 只当 Wi-Fi 的候选
            toast("走 ADB 只能连 127.0.0.1（adb reverse 只转到本机）。已按 127.0.0.1 连接；扫到的 $scannedIp 已存进 prefs，改走 Wi-Fi 时能用")
            Controller.connect("127.0.0.1")
        } else {
            prefs.edit().putString("pc_ip", scannedIp).apply()
            Controller.connect(scannedIp)
            toast("已按扫到的 $scannedIp:$scannedPort 连接（Wi-Fi UDP）")
        }
    }

    // 这一页没有状态区了：出错和结果只能弹 Toast（CrashLog 那行还能在 `adb logcat -s XjoyQR XjoyCrash` 里看）
    private fun toast(message: String) {
        Log.w(TAG, message)
        try {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        } catch (ignored: Exception) {
            // Toast 弹不了就算了
        }
    }
}
