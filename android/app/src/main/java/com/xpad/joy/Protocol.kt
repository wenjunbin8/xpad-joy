package com.xpad.joy

/**
 * 手柄字段定义 —— 安卓端与电脑端必须完全一致（见 README / pc-receiver）。
 */
object Protocol {

    /** Wi-Fi（UDP）/ adb 隧道（TCP）默认端口 */
    const val UDP_PORT = 27042
    const val PING_INTERVAL_MS = 1000      // 手机每 1 秒发一次 ping，电脑回 pong → 手机算 RTT（顺便让路径保持热）

    /** 二维码内容：电脑客户端画的就是 xpad://<电脑 IP>:<端口> */
    const val QR_SCHEME = "xpad://"

    /**
     * 解析扫到的内容：`xpad://ip:port`、`ip:port`、裸 `ip` 都认（手抄的、别的 App 生成的也能扫）。
     * 端口没写就用 UDP_PORT。认不出地址返回 null。
     */
    fun parseQr(text: String): Pair<String, Int>? {
        var body = text.trim()
        if (body.startsWith(QR_SCHEME)) body = body.substring(QR_SCHEME.length)
        val schemeEnd = body.indexOf("://")
        if (schemeEnd >= 0) body = body.substring(schemeEnd + 3)
        body = body.split('/', '?', '#', ' ', '\n').firstOrNull() ?: return null
        val host = body.substringBefore(':').trim()
        if (!host.matches(Regex("[0-9A-Za-z.\\-_]{2,64}"))) return null
        val port = body.substringAfter(':', "").toIntOrNull()?.coerceIn(1, 65535) ?: UDP_PORT
        return Pair(host, port)
    }

    // ---- 按钮位（bit 序号，从 bit0 开始）----
    const val BTN_A = 0
    const val BTN_B = 1
    const val BTN_X = 2
    const val BTN_Y = 3
    const val BTN_LB = 4
    const val BTN_RB = 5
    const val BTN_BACK = 6
    const val BTN_START = 7
    const val BTN_GUIDE = 8   // Xbox 圆形 LOGO
    const val BTN_L3 = 9
    const val BTN_R3 = 10

    // ---- 十字键（HID hat switch 取值）----
    const val HAT_N = 0
    const val HAT_NE = 1
    const val HAT_E = 2
    const val HAT_SE = 3
    const val HAT_S = 4
    const val HAT_SW = 5
    const val HAT_W = 6
    const val HAT_NW = 7
    const val HAT_NEUTRAL = 8

    const val REPORT_ID_INPUT = 1
    const val REPORT_ID_RUMBLE = 2

    /**
     * HID Report Descriptor。
     *
     * 输入报告（Report ID 1，正文 9 字节，不含 Report ID）：
     *   [0] 按钮 bit0..bit7（A,B,X,Y,LB,RB,BACK,START）
     *   [1] 按钮 bit8..bit10（GUIDE,L3,R3）+ 5 bit padding
     *   [2] hat（4 bit）+ 4 bit padding
     *   [3] LX  [4] LY  [5] RX  [6] RY    —— 有符号 -128..127，中心为 0
     *   [7] LT（0..255，模拟量）
     *   [8] RT（0..255，模拟量）
     *
     * 输出报告（Report ID 2，2 字节，电脑 → 手机）：左马达、右马达，用于震动。
     */
    val HID_DESCRIPTOR: ByteArray = hex(
        "05 01 09 04 A1 01 " +
            "85 01 " +
            // 11 个按钮 + 5 bit padding
            "05 09 19 01 29 0B 15 00 25 01 75 01 95 0B 81 02 " +
            "75 01 95 05 81 03 " +
            // hat switch：0..8（8 = 中立）
            "05 01 09 39 15 00 25 08 75 04 95 01 81 00 " +
            "75 04 95 01 81 03 " +
            // 左右摇杆 X/Y/RX/RY：-128..127
            "15 80 25 7F 09 30 09 31 09 33 09 34 75 08 95 04 81 02 " +
            // 模拟扳机 Z(LT) / Rz(RT)：0..255
            "15 00 25 FF 09 32 09 35 75 08 95 02 81 02 " +
            // 输出报告：震动马达（vendor usage page）
            "85 02 06 FF 00 09 01 15 00 25 FF 75 08 95 02 91 02 " +
            "C0"
    )

    private fun hex(text: String): ByteArray =
        text.trim().split(Regex("\\s+")).map { it.toInt(16).toByte() }.toByteArray()
}
