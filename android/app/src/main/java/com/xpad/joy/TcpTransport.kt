package com.xpad.joy

import android.util.Log
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException

/**
 * USB 这条走 ADB 隧道（不再用 USB 网络共享）。
 *
 * 用法：电脑先跑 `adb reverse tcp:27042 tcp:27042`，手机里填 127.0.0.1，连上后
 * 手机发的包会从这个隧道到电脑客户端。ADB 只转发 TCP，所以这条是 TCP；
 * 流里每条消息 = **2 字节大端长度 + 原始包字节**，原始包内容跟 UDP 那条完全一样
 * （20 字节紧凑包 / JSON / XACK），一个字节都没改 —— 电脑端 client.py 按同样的帧读。
 *
 * 为什么比 USB 网络共享好：隧道是本地回环 + USB 传输，没有 Wi-Fi 网卡省电攒包的问题；
 * 代价是要在电脑上跑一次 adb reverse，而且 adb 本身是批量传输（单次几 ms）。
 */
class TcpTransport(
    state: GamepadState,
    onStatus: (String) -> Unit,
    onRumble: (Int, Int) -> Unit,
    port: Int = Protocol.UDP_PORT,
) : BaseTransport(state, onStatus, onRumble, port) {

    private var socket: Socket? = null
    private var reader: Thread? = null
    private var sender: Thread? = null

    override val channelName: String get() = "adb 隧道"

    override fun extra(): String = "走 adb reverse（TCP，2 字节长度 + 原始包）"

    override fun open(target: String): Boolean {
        return try {
            val s = Socket()
            s.tcpNoDelay = true
            // 读超时用来"没有回复也要发 ping"，顺便保证线程能退出
            s.soTimeout = Protocol.PING_INTERVAL_MS
            s.connect(InetSocketAddress(target, port), 3000)
            socket = s
            reader = Thread({ readerLoop(s) }, "adb-reader").apply { isDaemon = true; start() }
            sender = Thread({ senderLoop(s) }, "adb-sender").apply { isDaemon = true; start() }
            true
        } catch (t: Throwable) {
            lastError = t.message
            Log.e("XjoyLink", "adb 隧道连不上 $target:$port（${t.javaClass.simpleName}: ${t.message}）", t)
            onStatus("连不上 $target:$port：走 ADB 要先在电脑上跑 adb reverse tcp:$port tcp:$port")
            false
        }
    }

    private fun readerLoop(s: Socket) {
        val input = s.getInputStream()
        while (!Thread.currentThread().isInterrupted && !s.isClosed) {
            val frame = try {
                readFrame(input)
            } catch (e: SocketTimeoutException) {
                maybePing()
                continue
            } catch (t: Throwable) {
                markDisconnected("adb 隧道读包中断：${t.message ?: t.javaClass.simpleName}")
                break
            }
            if (frame == null) {
                // 读到 EOF：电脑端把这条连接关了（客户端关掉/重启）
                markDisconnected("adb 隧道被电脑端关闭")
                break
            }
            if (frame.isNotEmpty()) onPacket(frame)
            maybePing()
        }
    }

    /** 2 字节大端长度 + 正文；半包要读满，不能读到一半就解。null = 读到头（EOF） */
    private fun readFrame(input: InputStream): ByteArray? {
        val header = ByteArray(2)
        var got = 0
        while (got < 2) {
            val n = input.read(header, got, 2 - got)
            if (n < 0) return null
            got += n
        }
        val len = ((header[0].toInt() and 0xFF) shl 8) or (header[1].toInt() and 0xFF)
        if (len <= 0 || len > 4096) return ByteArray(0)
        val data = ByteArray(len)
        var off = 0
        while (off < len) {
            val n = input.read(data, off, len - off)
            if (n < 0) return null
            off += n
        }
        return data
    }

    private fun senderLoop(s: Socket) {
        while (!Thread.currentThread().isInterrupted && !s.isClosed) {
            val data = takeForWrite() ?: continue
            write(data)
        }
    }

    override fun write(data: ByteArray): Boolean {
        val s = socket ?: return false
        return try {
            val out = s.getOutputStream()
            out.write(byteArrayOf(((data.size shr 8) and 0xFF).toByte(), (data.size and 0xFF).toByte()))
            out.write(data)
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
    }
}
