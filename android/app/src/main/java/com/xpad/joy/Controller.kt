package com.xpad.joy

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log

/**
 * 全局共享的手柄状态与连接：第一屏（Home）负责连接与参数，
 * 手柄屏（Gamepad）只负责按键。两个界面用同一份状态，切屏不会断连接。
 */
object Controller {

    // 两条路：Wi-Fi 走 UDP；USB 走 ADB 隧道（电脑先 adb reverse，手机连 127.0.0.1 的 TCP）
    const val LINK_WIFI = 0
    const val LINK_ADB = 1

    val state = GamepadState()

    var link: Int = LINK_WIFI
    var port: Int = Protocol.UDP_PORT
    var packetsSent: Int = 0
    var lastStatus: String = "未连接"
    var lastRumble: Int = 0

    var transport: Transport? = null
        private set

    var appContext: Context? = null
    private var listener: (() -> Unit)? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var eventCount = 0
    private var lastVibrateAt = 0L
    private var rumbleCount = 0
    private var vibrator: Vibrator? = null

    /** 收到过多少次震动包（>0 就是电脑端确实回传到手机了）；手机侧看 adb logcat -s XjoyLink */
    val rumbleTotal: Int get() = rumbleCount

    val connected: Boolean get() = transport?.isConnected == true
    val modeName: String get() = if (link == LINK_ADB) "ADB 隧道（TCP）" else "Wi-Fi UDP"

    /**
     * 用户在第一屏点「断开」就置 false：自动重连循环不再自己连回来（点「连接」或扫码连会恢复 true）。
     * 被动断线（电脑客户端重启、网断了、10 秒没回复）不受影响：那时还是 true，会自己连回来。
     */
    var autoConnect = true

    fun attach(context: Context, uiListener: () -> Unit) {
        appContext = context.applicationContext
        listener = uiListener
        if (vibrator == null) vibrator = resolveVibrator()
    }

    fun detach(uiListener: () -> Unit) {
        if (listener === uiListener) listener = null
    }

    fun notifyUi() {
        mainHandler.post { listener?.invoke() }
    }

    /** 控件状态变化 → 发一次报告；UI 每 8 次事件刷新一次，避免刷屏 */
    fun send() {
        val t = transport ?: return
        if (t.send(state)) {
            packetsSent++
        } else {
            lastStatus = "发送失败（未连接）"
        }
        if (++eventCount % 8 == 0) notifyUi()
    }

    fun connect(target: String?): Boolean {
        val context = appContext ?: return false
        disconnect()
        val t = if (link == LINK_ADB) TcpTransport(state, ::onStatus, ::onRumble, port)
        else UdpTransport(state, ::onStatus, ::onRumble, port)
        transport = t
        return t.start(target)
    }

    fun disconnect() {
        transport?.stop()
        transport = null
        notifyUi()
    }

    private fun onStatus(text: String) {
        lastStatus = text
        notifyUi()
    }

    private fun onRumble(left: Int, right: Int) {
        rumbleCount++
        lastRumble = left + right
        Log.i("XjoyLink", "收到震动 #$rumbleCount left=$left right=$right")
        if (lastRumble <= 0) return
        val now = System.currentTimeMillis()
        if (now - lastVibrateAt < 120) return   // 限流
        lastVibrateAt = now
        val v = vibrator ?: return
        if (!v.hasVibrator()) {
            Log.w("XjoyLink", "这台机器没有马达（hasVibrator=false）")
            return
        }
        val amplitude = maxOf(left, right).coerceIn(1, 255)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(140, amplitude))
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(140)
            }
            Log.i("XjoyLink", "马达已触发 amplitude=$amplitude（140ms）")
        } catch (e: Exception) {
            // 部分机型不支持幅度控制，忽略
            Log.w("XjoyLink", "震动失败：${e.message ?: e.javaClass.simpleName}")
        }
        notifyUi()
    }

    private fun resolveVibrator(): Vibrator? = try {
        val context = appContext ?: return null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager = context.getSystemService(VibratorManager::class.java)
            manager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Vibrator::class.java)
        }
    } catch (e: Exception) {
        null
    }
}
