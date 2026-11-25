package com.xpad.joy

import android.net.wifi.WifiManager
import android.os.Build
import android.util.Log
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/**
 * Wi-Fi 那条路：UDP，一个数据报一个包。连上期间持有 Wi-Fi 高性能/低延迟锁（关掉网卡省电，
 * 包不会被攒着一起发）。协议解析在 BaseTransport 里，两个传输层共用。
 *
 * 发送单独一个线程 + 只留最新一帧：UI 线程只做拼包，不被绘制和输入分发拖住。
 */
class UdpTransport(
    state: GamepadState,
    onStatus: (String) -> Unit,
    onRumble: (Int, Int) -> Unit,
    port: Int = Protocol.UDP_PORT,
) : BaseTransport(state, onStatus, onRumble, port) {

    private var socket: DatagramSocket? = null
    private var peer: InetSocketAddress? = null
    private var reader: Thread? = null
    private var sender: Thread? = null

    @Suppress("DEPRECATION")
    private var wifiLock: WifiManager.WifiLock? = null

    @Volatile
    var wifiLockHeld = false
        private set

    override fun extra(): String = if (wifiLockHeld) "网卡省电已关" else ""

    override fun open(target: String): Boolean {
        return try {
            val s = DatagramSocket()
            // 读超时用来"没有回复也要发 ping"，顺便保证线程能退出
            s.soTimeout = Protocol.PING_INTERVAL_MS
            socket = s
            peer = InetSocketAddress(target, port)
            acquireWifiLock()
            sender = Thread({ senderLoop(s) }, "udp-sender").apply { isDaemon = true; start() }
            reader = Thread({ readerLoop(s) }, "udp-reader").apply { isDaemon = true; start() }
            true
        } catch (t: Throwable) {
            lastError = t.message
            onStatus("UDP 启动失败: ${t.message ?: t.javaClass.simpleName}")
            false
        }
    }

    private fun readerLoop(s: DatagramSocket) {
        while (!Thread.currentThread().isInterrupted && !s.isClosed) {
            val buf = ByteArray(256)
            val packet = DatagramPacket(buf, buf.size)
            try {
                s.receive(packet)
                if (packet.length > 0) onPacket(packet.data.copyOf(packet.length))
            } catch (e: SocketTimeoutException) {
                // 超时属正常：正好用来发 ping
            } catch (t: Throwable) {
                lastError = t.message
                break
            }
            maybePing()
        }
    }

    private fun senderLoop(s: DatagramSocket) {
        while (!Thread.currentThread().isInterrupted && !s.isClosed) {
            val data = takeForWrite() ?: continue
            write(data)
        }
    }

    override fun write(data: ByteArray): Boolean {
        val s = socket ?: return false
        val p = peer ?: return false
        return try {
            s.send(DatagramPacket(data, data.size, p))
            lastError = null
            true
        } catch (t: Throwable) {
            lastError = t.message
            false
        }
    }

    override fun closeTransport() {
        reader?.interrupt()
        reader = null
        sender?.interrupt()
        sender = null
        try {
            socket?.close()
        } catch (t: Throwable) {
            // 忽略
        }
        socket = null
        peer = null
        releaseWifiLock()
    }

    private fun acquireWifiLock() {
        try {
            val context = Controller.appContext ?: return
            val wifi = context.getSystemService(WifiManager::class.java) ?: return
            val mode = if (Build.VERSION.SDK_INT >= 31) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
            val lock = wifi.createWifiLock(mode, "Xpad-joy")
            lock.setReferenceCounted(false)
            lock.acquire()
            wifiLock = lock
            wifiLockHeld = true
        } catch (t: Throwable) {
            Log.e("XjoyNet", "Wi-Fi 锁失败（不影响功能）", t)
        }
    }

    private fun releaseWifiLock() {
        try {
            wifiLock?.release()
        } catch (t: Throwable) {
            Log.e("XjoyNet", "释放 Wi-Fi 锁失败", t)
        }
        wifiLock = null
        wifiLockHeld = false
    }
}
