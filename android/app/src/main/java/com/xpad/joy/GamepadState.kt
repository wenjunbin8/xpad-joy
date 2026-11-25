package com.xpad.joy

/**
 * 手柄当前状态。所有触控 View 共用同一个实例，任何变化都会触发一次上报。
 */
class GamepadState {

    var buttons: Int = 0
    var hat: Int = Protocol.HAT_NEUTRAL
    var lx: Int = 0
    var ly: Int = 0
    var rx: Int = 0
    var ry: Int = 0
    var lt: Int = 0
    var rt: Int = 0
    /** 最后一次 ping→pong 的往返延迟（毫秒），只用于 JSON，不进 HID 报告 */
    var rtt: Int = -1
    /** 输入路径往返：手机发 state → 电脑回 ack 的时间（毫秒），只用于 JSON */
    var stateRtt: Int = -1
    /** 发这个 state 包的时刻（elapsedRealtime），电脑收到后原样回传 */
    var ts: Long = 0

    fun setBit(bit: Int, on: Boolean) {
        if (bit < 0 || bit > 15) return
        buttons = if (on) buttons or (1 shl bit) else buttons and (1 shl bit).inv()
    }

    fun applyHat(value: Int) {
        hat = value.coerceIn(0, 8)
    }

    fun setStick(left: Boolean, x: Int, y: Int) {
        if (left) {
            lx = x.coerceIn(-128, 127)
            ly = y.coerceIn(-128, 127)
        } else {
            rx = x.coerceIn(-128, 127)
            ry = y.coerceIn(-128, 127)
        }
    }

    fun setTrigger(left: Boolean, value: Int) {
        val v = value.coerceIn(0, 255)
        if (left) lt = v else rt = v
    }

    /** HID 输入报告正文（9 字节，Report ID 由 API 单独传入） */
    fun inputReport(): ByteArray {
        val out = ByteArray(9)
        out[0] = (buttons and 0xFF).toByte()
        out[1] = ((buttons shr 8) and 0xFF).toByte()
        out[2] = (hat and 0x0F).toByte()
        out[3] = (lx and 0xFF).toByte()
        out[4] = (ly and 0xFF).toByte()
        out[5] = (rx and 0xFF).toByte()
        out[6] = (ry and 0xFF).toByte()
        out[7] = (lt and 0xFF).toByte()
        out[8] = (rt and 0xFF).toByte()
        return out
    }

    /**
     * 紧凑包（20 字节，UDP 用）：省掉 JSON 的约 110 字节和解析。
     * 0 'X' | 1-2 buttons(大端) | 3 hat | 4-7 lx,ly,rx,ry | 8-9 lt,rt | 10-17 ts(大端) | 18-19 srtt(大端, 0xFFFF=没测到)
     * 电脑端两种格式都认，所以老接收端仍然兼容。
     */
    fun toCompact(): ByteArray {
        val out = ByteArray(20)
        out[0] = 'X'.code.toByte()
        val b = buttons and 0xFFFF
        out[1] = (b shr 8).toByte()
        out[2] = (b and 0xFF).toByte()
        out[3] = (hat and 0xFF).toByte()
        out[4] = (lx and 0xFF).toByte()
        out[5] = (ly and 0xFF).toByte()
        out[6] = (rx and 0xFF).toByte()
        out[7] = (ry and 0xFF).toByte()
        out[8] = (lt and 0xFF).toByte()
        out[9] = (rt and 0xFF).toByte()
        val t = ts
        for (i in 0 until 8) out[10 + i] = ((t shr (56 - 8 * i)) and 0xFF).toByte()
        val s = if (stateRtt < 0) 0xFFFF else (stateRtt and 0xFFFF)
        out[18] = (s shr 8).toByte()
        out[19] = (s and 0xFF).toByte()
        return out
    }

    /** Wi-Fi（UDP）模式下的 JSON，字段与 pc-receiver/receiver.py 一致 */
    fun toJson(): String {
        val sb = StringBuilder(128)
        sb.append("{\"t\":\"state\",\"buttons\":").append(buttons and 0x7FF)
        sb.append(",\"hat\":").append(hat)
        sb.append(",\"lx\":").append(lx)
        sb.append(",\"ly\":").append(ly)
        sb.append(",\"rx\":").append(rx)
        sb.append(",\"ry\":").append(ry)
        sb.append(",\"lt\":").append(lt)
        sb.append(",\"rt\":").append(rt)
        if (rtt >= 0) sb.append(",\"rtt\":").append(rtt)
        if (stateRtt >= 0) sb.append(",\"srtt\":").append(stateRtt)
        if (ts > 0) sb.append(",\"ts\":").append(ts)
        sb.append('}')
        return sb.toString()
    }

    /** 用于界面上的状态展示 */
    fun describe(): String {
        val pressed = (0..10).filter { (buttons shr it) and 1 == 1 }.joinToString("/") { BIT_NAMES[it] }
        return "按键: ${(if (pressed.isEmpty()) "—" else pressed)}\n" +
            "十字键: ${HAT_NAMES[hat]}\n" +
            "左摇杆: ${pct(lx)},${pct(ly)}   右摇杆: ${pct(rx)},${pct(ry)}\n" +
            "扳机: LT ${lt * 100 / 255}%  RT ${rt * 100 / 255}%"
    }

    private fun pct(v: Int): String = (v * 100 / 127).toString()

    private val BIT_NAMES = arrayOf("A", "B", "X", "Y", "LB", "RB", "BACK", "START", "GUIDE", "L3", "R3")
    private val HAT_NAMES = arrayOf("上", "右上", "右", "右下", "下", "左下", "左", "左上", "中立")
}
