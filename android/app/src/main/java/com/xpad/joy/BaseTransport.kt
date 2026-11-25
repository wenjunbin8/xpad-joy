package com.xpad.joy

import android.content.Context
import android.os.SystemClock
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * 两条路共用的部分：拼包、只留最新一帧、每秒一次 ping、解析电脑端的回复。
 * 子类只写"怎么送出去 / 怎么读到一包"：
 *   UDP：一个数据报一个包；
 *   TCP（adb 隧道）：2 字节大端长度 + 原始包字节。
 * 包内容（20 字节紧凑包、JSON、XACK）两边完全一样，一个字节都不能改。
 */
abstract class BaseTransport(
    protected val state: GamepadState,
    protected val onStatus: (String) -> Unit,
    private val onRumble: (Int, Int) -> Unit,
    val port: Int,
) : Transport {

    @Volatile
    private var connectedFlag = false

    override val isConnected: Boolean get() = connectedFlag

    @Volatile
    protected var lastError: String? = null

    /** 最后一次收到 pong / XACK 的时刻（elapsedRealtime），0 = 电脑还没回复过 */
    @Volatile
    private var pongAt = 0L

    override val lastPongAt: Long get() = pongAt

    override val lastRtt: Int get() = state.rtt

    private var dest = ""

    override val target: String get() = dest

    override val modeName: String get() = Controller.modeName

    override fun extra(): String = ""

    /** 只留最新一帧（长度 1）：输入这种数据旧包没意义，不能被排后面的旧包堵住 */
    protected val queue = ArrayBlockingQueue<ByteArray>(1)
    protected var compact = true
    private var lastPingAt = 0L

    /** 状态行里的路名（UDP / adb 隧道） */
    protected open val channelName: String = "UDP"

    protected abstract fun open(target: String): Boolean
    protected abstract fun write(data: ByteArray): Boolean
    protected abstract fun closeTransport()

    /** 读/写线程发现通道断了：状态改回未连接，第一屏的重连循环会接手（电脑客户端重启后能自己连回来；
     *  但用户自己点过「断开」（Controller.autoConnect = false）就不再连） */
    protected fun markDisconnected(reason: String) {
        if (!connectedFlag) return
        connectedFlag = false
        lastError = reason
        onStatus(reason)
    }

    override fun start(t: String?): Boolean {
        stop()
        val host = t?.takeIf { it.isNotBlank() }
        if (host == null) {
            onStatus("请输入电脑 IP（Wi-Fi 填电脑 IP；走 ADB 就填 127.0.0.1）")
            return false
        }
        val context = Controller.appContext
        compact = context?.getSharedPreferences("xpadjoy", Context.MODE_PRIVATE)?.getBoolean("compact", true) ?: true
        dest = host
        connectedFlag = true
        lastError = null
        lastPingAt = 0L
        pongAt = 0L
        queue.clear()
        state.rtt = -1
        if (!open(host)) {
            connectedFlag = false
            return false
        }
        onStatus("$modeName → $host:$port（$channelName）")
        return true
    }

    override fun stop() {
        closeTransport()
        queue.clear()
        connectedFlag = false
    }

    /** UI 线程拼完包就马上交出去；队列里只保留最新一帧 */
    protected fun deliver(data: ByteArray) {
        queue.clear()
        queue.offer(data)
    }

    /** 子类的发送线程取一帧（没有就等 200ms，保证能退出） */
    protected fun takeForWrite(): ByteArray? =
        try {
            queue.poll(200, TimeUnit.MILLISECONDS)
        } catch (t: Throwable) {
            null
        }

    override fun send(gamepad: GamepadState): Boolean {
        if (!connectedFlag) return false
        gamepad.ts = SystemClock.elapsedRealtime()
        deliver(if (compact) gamepad.toCompact() else gamepad.toJson().toByteArray(StandardCharsets.UTF_8))
        lastError = null
        return true
    }

    /** 每秒一次 ping：电脑回 pong 就是"包真能进电脑"的证据，RTT 也是这么测的 */
    protected fun maybePing() {
        if (!connectedFlag) return
        val now = SystemClock.elapsedRealtime()
        if (now - lastPingAt < Protocol.PING_INTERVAL_MS) return
        lastPingAt = now
        deliver("{\"t\":\"ping\",\"ts\":$now}".toByteArray(StandardCharsets.UTF_8))
    }

    /**
     * 解析电脑端的一条回复（XACK 或 JSON）：
     *   XACK + ts(8, 大端) = 紧凑包的 ack → 输入路径往返
     *   {"t":"ack"} / {"t":"pong"} → 同样算往返 / RTT
     *   {"t":"rumble"} → 震动
     */
    protected fun onPacket(data: ByteArray) {
        if (data.size >= 12 && data[0] == 'X'.code.toByte() && data[1] == 'A'.code.toByte()
            && data[2] == 'C'.code.toByte() && data[3] == 'K'.code.toByte()) {
            var t = 0L
            // XACK 一共 12 字节：4 字节 "XACK" + 8 字节 ts（大端），ts 从下标 4 开始
            for (i in 0 until 8) t = (t shl 8) or ((data[4 + i].toInt() and 0xFF).toLong())
            if (t > 0) {
                state.stateRtt = (SystemClock.elapsedRealtime() - t).toInt().coerceAtLeast(0)
                pongAt = SystemClock.elapsedRealtime()
                onStatus("$modeName → $dest:$port（输入路径往返 ${state.stateRtt}ms）")
            }
            return
        }
        val json = try {
            JSONObject(String(data, StandardCharsets.UTF_8))
        } catch (t: Throwable) {
            lastError = "非法 JSON：${t.message}"
            return
        }
        when (json.optString("t")) {
            "ack" -> {
                val ts = json.optLong("ts", 0L)
                if (ts > 0) {
                    state.stateRtt = (SystemClock.elapsedRealtime() - ts).toInt().coerceAtLeast(0)
                    pongAt = SystemClock.elapsedRealtime()
                    onStatus("$modeName → $dest:$port（输入路径往返 ${state.stateRtt}ms）")
                }
            }
            "rumble" -> onRumble(json.optInt("left", 0), json.optInt("right", 0))
            "pong" -> {
                val ts = json.optLong("ts", 0L)
                if (ts > 0) {
                    state.rtt = (SystemClock.elapsedRealtime() - ts).toInt().coerceAtLeast(0)
                    pongAt = SystemClock.elapsedRealtime()
                    onStatus("$modeName → $dest:$port（电脑已回复，RTT ${state.rtt}ms）")
                    // 回一帧当前状态：电脑端要看到收包/延迟/按键，光有 ping 不够
                    send(state)
                }
            }
        }
    }
}
