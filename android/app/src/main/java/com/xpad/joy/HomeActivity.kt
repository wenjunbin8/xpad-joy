package com.xpad.joy

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.net.Uri
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast

/**
 * 第一屏：连接状态、走哪条路（Wi-Fi / USB 网络共享）、当前布局的状态图。
 * 蓝牙模式已删掉；运行信息（按键/摇杆/扳机/收包数）在电脑端程序里。
 *
 * 体感这块在第一屏只有「体感幅度」滑块（转多少度 = 摇杆满量程，3–90°）。
 * 回正按钮在手柄屏里（打游戏的时候点得到），存进 prefs `gyro_ref`。
 */
class HomeActivity : Activity() {

    private lateinit var prefs: SharedPreferences
    private lateinit var statusText: TextView
    private lateinit var preview: LayoutPreviewView
    private lateinit var ipField: EditText
    private lateinit var connectButton: Button
    private lateinit var scanButton: Button
    private lateinit var linkAdbButton: Button
    private lateinit var gyroButton: Button
    private lateinit var batteryButton: Button
    private lateinit var linkWifiButton: Button
    private lateinit var gyroRange: SeekBar
    private lateinit var gyroRangeValue: TextView

    private val refresh: () -> Unit = { render() }
    private val uiHandler = Handler(Looper.getMainLooper())

    // 连接必须在后台线程做：在主线程连 socket 会抛 NetworkOnMainThreadException
    // （这就是之前"走 ADB 永远连不上"的直接原因——点连接按钮是在主线程里连的）
    private val connectThread: HandlerThread = HandlerThread("xjoy-connect").apply { start() }
    private val connectHandler: Handler = Handler(connectThread.looper)

    /** 每 3 秒刷一次：不然"电脑没回复"这种状态只有等下一次 pong 才会变 */
    private val ticker = object : Runnable {
        override fun run() {
            render()
            uiHandler.postDelayed(this, 3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashLog.install(this)
        setContentView(R.layout.activity_home)

        prefs = getSharedPreferences("xpadjoy", Context.MODE_PRIVATE)
        LayoutConfig.load(this)

        statusText = findViewById(R.id.home_status) as TextView
        preview = findViewById(R.id.home_preview) as LayoutPreviewView
        ipField = findViewById(R.id.home_ip) as EditText
        connectButton = findViewById(R.id.home_connect) as Button
        scanButton = findViewById(R.id.home_scan) as Button
        linkAdbButton = findViewById(R.id.link_adb) as Button
        gyroButton = findViewById(R.id.gyro_toggle) as Button
        batteryButton = findViewById(R.id.battery_button) as Button
        linkWifiButton = findViewById(R.id.link_wifi) as Button
        gyroRange = findViewById(R.id.gyro_range) as SeekBar
        gyroRangeValue = findViewById(R.id.gyro_range_value) as TextView

        ipField.setText(prefs.getString("pc_ip", ""))
        Controller.link = prefs.getInt("link", Controller.LINK_WIFI)

        gyroRange.max = MAX_DEG - MIN_DEG
        gyroRange.progress = gyroDegrees() - MIN_DEG
        gyroRange.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                prefs.edit().putInt("gyro_range", MIN_DEG + progress).apply()
                render()
            }

            override fun onStartTrackingTouch(seekBar: SeekBar?) {
                // 不需要
            }

            override fun onStopTrackingTouch(seekBar: SeekBar?) {
                // 不需要
            }
        })

        connectButton.setOnClickListener { connect() }
        scanButton.setOnClickListener { startActivity(Intent(this, QrScanActivity::class.java)) }
        gyroButton.setOnClickListener {
            val on = !prefs.getBoolean("gyro", false)
            prefs.edit().putBoolean("gyro", on).apply()
            say(if (on) "体感已开：手柄屏里左右转动 = 左摇杆 X（Y 保持 0），回正用手柄屏那个「回正」键" else "体感已关：左摇杆回到手搓")
            render()
        }
        batteryButton.setOnClickListener {
            try {
                val pm = getSystemService(PowerManager::class.java)
                if (pm == null) {
                    say("读不到电池状态")
                } else if (pm.isIgnoringBatteryOptimizations(packageName)) {
                    say("Xpad-joy 已在电池优化白名单（不会被 Doze 降频）")
                } else {
                    val intent = Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    intent.data = Uri.parse("package:$packageName")
                    startActivity(intent)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "电池优化请求失败", t)
                say("打不开电池优化设置：设置 → 应用 → Xpad-joy → 电池 → 不限制")
            }
        }
        linkWifiButton.setOnClickListener { setLink(Controller.LINK_WIFI) }
        linkAdbButton.setOnClickListener { setLink(Controller.LINK_ADB) }
        findViewById<Button>(R.id.home_enter).setOnClickListener { openGamepad() }
        findViewById<Button>(R.id.home_customize).setOnClickListener { openLayout() }

        render()
    }

    override fun onResume() {
        super.onResume()
        val savedIp = prefs.getString("pc_ip", "")
        if (ipField.text.toString() != savedIp) ipField.setText(savedIp)
        Controller.port = prefs.getInt("pc_port", Protocol.UDP_PORT)
        Controller.attach(this, refresh)
        uiHandler.removeCallbacksAndMessages(null)
        uiHandler.post(ticker)
        render()
        scheduleRetry()
    }

    override fun onPause() {
        uiHandler.removeCallbacksAndMessages(null)
        super.onPause()
    }

    override fun onDestroy() {
        uiHandler.removeCallbacksAndMessages(null)
        connectThread.quitSafely()
        Controller.detach(refresh)
        super.onDestroy()
    }

    private fun gyroDegrees(): Int {
        return prefs.getInt("gyro_range", DEFAULT_DEG).coerceIn(MIN_DEG, MAX_DEG)
    }

    // ---------------- 连接 ----------------

    private fun currentTarget(): String {
        // ADB 隧道只到本机：走 ADB 时电脑 IP 一律不算数，只能 127.0.0.1
        if (Controller.link == Controller.LINK_ADB) return "127.0.0.1"
        val ip = ipField.text.toString().trim()
        if (ip.isEmpty()) {
            say("填入电脑 IP（Wi-Fi 用同一网段的 IP）")
            return ""
        }
        prefs.edit().putString("pc_ip", ip).apply()
        return ip
    }

    private fun connect() {
        val target = currentTarget()
        if (target.isEmpty()) return
        connectHandler.post {
            if (alive()) {
                Controller.disconnect()
                // 用户主动断开：自动重连关掉（不然过几秒那个 4 秒循环又把它连回来）
                Controller.autoConnect = false
                uiHandler.removeCallbacks(retryTask)
                uiHandler.post {
                    say("已断开：自动重连已关闭（点「连接」或扫码会恢复）")
                    render()
                }
                return@post
            }
            Controller.autoConnect = true
            val ok = try {
                Controller.connect(target)
            } catch (t: Throwable) {
                Log.e(TAG, "连接出错", t)
                false
            }
            uiHandler.post {
                if (ok) {
                    // UDP 没有握手，连上不等于电脑收到了包：过一会儿再刷新一次状态
                    if (Controller.link == Controller.LINK_WIFI) uiHandler.postDelayed(refresh, 6000)
                } else {
                    Log.w(TAG, "连 $target:${Controller.port} 失败：${Controller.lastStatus}")
                    if (Controller.link == Controller.LINK_ADB) {
                        say("连不上 127.0.0.1:${Controller.port}：电脑上客户端要开着，而且先跑 adb reverse tcp:${Controller.port} tcp:${Controller.port}")
                    } else {
                        say("连不上 $target:${Controller.port}：${Controller.lastStatus}")
                    }
                }
                render()
                scheduleRetry()
            }
        }
    }

    private fun setLink(newLink: Int) {
        Controller.link = newLink
        prefs.edit().putInt("link", newLink).apply()
        render()
        scheduleRetry()
    }

    /** 没连上就每隔 4 秒再试一次（只在第一屏）：走 ADB 时电脑可能晚一点才跑 adb reverse；走 Wi-Fi 时客户端可能重启过。
     *  用户点过「断开」就不试（Controller.autoConnect），点「连接」或扫码连会恢复。 */
    private val retryTask: Runnable = Runnable {
        val target = retryTarget()
        if (Controller.autoConnect && !alive() && target.isNotEmpty()) {
            connectHandler.post {
                val ok = try { Controller.connect(target) } catch (t: Throwable) { false }
                uiHandler.post {
                    if (ok) Log.i(TAG, "自动重连成功（${Controller.modeName} → $target）")
                    else Log.w(TAG, "自动重连失败（${Controller.modeName} → $target）：${Controller.lastStatus}")
                    render()
                    // render() 里也会排一次（200ms）：这里统一成 4 秒一次
                    uiHandler.removeCallbacks(retryTask)
                    if (Controller.autoConnect && !alive()) uiHandler.postDelayed(retryTask, 4000)
                }
            }
        }
    }

    /** 重连目标：走 ADB 只能 127.0.0.1；走 Wi-Fi 用存着的 pc_ip（空的就不自动连） */
    private fun retryTarget(): String =
        if (Controller.link == Controller.LINK_ADB) "127.0.0.1" else (prefs.getString("pc_ip", "") ?: "").trim()

    private fun scheduleRetry() {
        if (!Controller.autoConnect) return
        if (uiHandler.hasCallbacks(retryTask)) return
        if (!alive() && retryTarget().isNotEmpty()) {
            // 第一次马上试（进页面就能连上），之后每 4 秒一次
            uiHandler.postDelayed(retryTask, 200)
        }
    }

    private fun openGamepad() {
        startActivity(Intent(this, GamepadActivity::class.java))
    }

    private fun openLayout() {
        startActivity(Intent(this, LayoutActivity::class.java))
    }

    // ---------------- 界面刷新 ----------------

    private fun render() {
        try {
            statusText.text = connectionStatus()
            connectButton.text = if (alive()) getString(R.string.disconnect) else getString(R.string.connect)
            linkWifiButton.setBackgroundResource(
                if (Controller.link == Controller.LINK_WIFI) R.drawable.pill_primary else R.drawable.pill_outline
            )
            linkAdbButton.setBackgroundResource(
                if (Controller.link == Controller.LINK_ADB) R.drawable.pill_primary else R.drawable.pill_outline
            )
            gyroButton.setBackgroundResource(
                if (prefs.getBoolean("gyro", false)) R.drawable.pill_primary else R.drawable.pill_outline
            )
            batteryButton.setBackgroundResource(if (batteryExempt()) R.drawable.pill_primary else R.drawable.pill_outline)
            val degrees = gyroDegrees()
            gyroRange.progress = degrees - MIN_DEG
            val refSaved = !prefs.getString("gyro_ref", "").isNullOrEmpty()
            gyroRangeValue.text = "$degrees°（回正${if (refSaved) "已存" else "未存"}）"
            // 卡片里画的是当前生效的布局
            preview.invalidate()
            // 状态行只写「已连接 / 未连接」；扫码记录和崩溃记录只进 logcat（adb logcat -s XjoyHome）
            val crash = CrashLog.last(this)
            if (crash.isNotEmpty()) Log.w(TAG, "上次崩溃：$crash")
            val scanned = prefs.getString("qr_last", "")
            if (!scanned.isNullOrEmpty()) Log.i(TAG, "扫码记录：$scanned")
            // 没连上就继续试（电脑客户端可能重启过，或 adb reverse 还没跑）
            if (!alive() && retryTarget().isNotEmpty()) scheduleRetry()
        } catch (t: Throwable) {
            Log.e(TAG, "状态刷新出错", t)
        }
    }

    /** 状态行：只有「已连接」和「未连接」两个状态；RTT、回复时间只写 logcat */
    private fun connectionStatus(): String {
        val link = Controller.transport
        if (!alive()) {
            if (link != null) Log.i(TAG, "没连上：${link.target}:${Controller.port} ${Controller.lastStatus}")
            return getString(R.string.not_connected)
        }
        val ageSec = (SystemClock.elapsedRealtime() - link!!.lastPongAt) / 1000L
        Log.i(TAG, "连接详情：${link.target} RTT ${link.lastRtt} ms 上次回复 $ageSec 秒前 ${link.extra()}")
        return getString(R.string.connected)
    }

    /**
     * "已连接"的判据是电脑真的回复过（pong / XACK），不是 socket 连上了：
     * adb reverse 在手机上会先接受连接，电脑没客户端时手机这边也"连得上"，但包进不去。
     * 10 秒没回复就算没连上（手机每秒 ping 一次，正常 1 秒内就该回复）。
     */
    private fun alive(): Boolean {
        val t = Controller.transport ?: return false
        if (!Controller.connected) return false
        if (t.lastPongAt == 0L) return false
        return (SystemClock.elapsedRealtime() - t.lastPongAt) / 1000L <= PONG_MAX_AGE_SEC
    }

    private fun batteryExempt(): Boolean {
        return try {
            val pm = getSystemService(PowerManager::class.java)
            pm != null && pm.isIgnoringBatteryOptimizations(packageName)
        } catch (t: Throwable) {
            false
        }
    }

    private fun say(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    companion object {
        private const val TAG = "XjoyHome"
        private const val MIN_DEG = 3
        private const val MAX_DEG = 90
        private const val DEFAULT_DEG = 8
        private const val PONG_MAX_AGE_SEC = 10L
    }
}
