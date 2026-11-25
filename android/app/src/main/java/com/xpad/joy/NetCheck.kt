package com.xpad.joy

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.util.Log
import java.net.Inet4Address

/**
 * 连不上电脑时给一条看得懂的诊断：手机走的是哪个网络、手机自己的 IP、和电脑是否同一网段。
 * 只在"电脑没回复"时显示，正常连接不显示这些。需要 ACCESS_NETWORK_STATE 权限。
 */
object NetCheck {

    private const val TAG = "XjoyNet"

    fun diagnose(context: Context, targetIp: String?): String {
        try {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            if (cm == null) return "读不到网络状态"
            val network: Network = cm.activeNetwork ?: return "手机当前没有可用网络"
            val caps = cm.getNetworkCapabilities(network)
            val link = cm.getLinkProperties(network)
            val own = link?.linkAddresses?.firstOrNull { it.address is Inet4Address }
            val ownIp = own?.address?.hostAddress
            val prefix = own?.prefixLength ?: -1
            val iface = link?.interfaceName ?: "?"
            val viaWifi = caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
            val viaUsb = !viaWifi && (iface.contains("rndis") || iface.startsWith("usb"))
            val label = when {
                viaWifi -> "Wi-Fi"
                viaUsb -> "USB 网卡（$iface）"
                else -> "移动数据（$iface）"
            }

            if (!viaWifi && !viaUsb) return "手机走的是$label，发不到 $targetIp：连同一个 Wi-Fi 再填电脑 IP；走 ADB 就填 127.0.0.1（电脑先 adb reverse tcp:27042 tcp:27042）"
            if (ownIp == null) return "$label 已连上但读不到手机自己的 IP"
            if (targetIp.isNullOrEmpty()) return "手机 IP $ownIp（$label）"
            if (prefix <= 0 || prefix > 32) return "手机 IP $ownIp（$label），判断不了网段"
            return if (sameSubnet(ownIp, targetIp, prefix)) {
                "手机 IP $ownIp（$label /$prefix），和 $targetIp 同一网段 → 收不到包就查电脑防火墙"
            } else {
                "手机 IP $ownIp（$label /$prefix），和 $targetIp 不在同一网段（路由器可能开了 AP 隔离）"
            }
        } catch (t: Throwable) {
            Log.e(TAG, "网络诊断失败", t)
            return "网络诊断出错：${t.message ?: t.javaClass.simpleName}"
        }
    }

    private fun sameSubnet(a: String, b: String, prefix: Int): Boolean {
        val x = a.toIpInt() ?: return false
        val y = b.toIpInt() ?: return false
        val mask = if (prefix >= 32) -1 else (-1 shl (32 - prefix))
        return (x and mask) == (y and mask)
    }

    private fun String.toIpInt(): Int? {
        val parts = split('.')
        if (parts.size != 4) return null
        var value = 0
        for (part in parts) {
            val number = part.toIntOrNull() ?: return null
            if (number !in 0..255) return null
            value = (value shl 8) or number
        }
        return value
    }
}
