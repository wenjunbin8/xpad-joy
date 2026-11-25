package com.xpad.joy

/**
 * 传输层抽象。现在两条路，包内容完全一样（20 字节紧凑包 / JSON），只是"怎么送"不同：
 *
 *   Wi-Fi：UDP，一个数据报一个包 → target = 电脑在同一网段的 IP
 *   USB：ADB 隧道（不是 USB 网络共享）。ADB 只能转发 TCP，所以这条走 TCP，
 *         电脑先跑 `adb reverse tcp:27042 tcp:27042`，手机连 127.0.0.1:27042，
 *         TCP 流里每个包 = 2 字节大端长度 + 原始包字节（原始包一个字节都不变）。
 *
 * 蓝牙 HID 模式已删掉。扫码也删掉了：连接只靠手输 IP。
 */
interface Transport {
    val modeName: String
    val isConnected: Boolean
    val target: String
    val lastPongAt: Long
    val lastRtt: Int

    /** 一条补充信息：UDP = 网卡省电锁；TCP = adb 隧道 */
    fun extra(): String

    fun start(target: String?): Boolean
    fun send(state: GamepadState): Boolean
    fun stop()
}
