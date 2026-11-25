package com.xpad.joy

import android.app.Activity
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.widget.Button
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.roundToInt

/**
 * 第二屏：按键面板（排布按参考图）+ 体感进度条 + 回正按钮。
 *
 * 体感（第一屏「体感→左摇杆」开关）：左右转手机 = 左摇杆 X，Y 保持 0。
 *
 * 算的是「参照姿态 → 当前姿态」的相对旋转，取**绕竖直方向**的分量：
 *   - 手机平放（屏幕朝上）时，竖直方向 = 屏幕法线（device Z）；
 *   - 手机竖着拿（屏幕对着自己）时，竖直方向是机身的短边/长边那一轴（横屏 = device X，竖屏 = device Y）。
 * 之前固定读 device Z，所以只有平放时对，竖着拿就反了。现在读的是世界竖直方向那条分量，
 * 平放、竖着拿、横屏、竖屏都是同一个动作。想固定某个轴：改 `GYRO_AXIS`（AXIS_AUTO 是默认）。
 *
 * 满量程 = 第一屏那个滑块（prefs `gyro_range`，3–90°）。回正 = 手柄屏那个「回正」按钮（存进 prefs）。
 */
class GamepadActivity : Activity() {

    private var sensorManager: SensorManager? = null
    private var sensor: Sensor? = null
    private var useOrientation = false
    private var gyroOn = false

    private lateinit var leftStick: StickView
    private lateinit var gyroBar: GyroBarView
    private lateinit var centerButton: Button

    /** 当前姿态与参照姿态（都是 world → device） */
    private val rotationMatrix = FloatArray(9)
    private val baseMatrix = FloatArray(9)
    private val relative = FloatArray(9)
    private val worldRelative = FloatArray(9)

    private var basePending = true
    private var angleDeg = 0f
    private var lastEventNs = 0L
    private var lastGyroX = 0
    private var lastGyroSendAt = 0L
    private var gyroRangeDeg = 8f
    private var deadzoneDeg = 0.3f
    private var prefs: android.content.SharedPreferences? = null

    private val gyroListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            if (!gyroOn) return

            if (useOrientation) {
                SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
                if (basePending) {
                    for (i in 0 until 9) baseMatrix[i] = rotationMatrix[i]
                    basePending = false
                    saveBase()
                }
                angleDeg = axisAngle() * 57.29578f * ORIENTATION_SIGN
            } else {
                // 退路：只有陀螺仪时，取"屏幕里看起来竖直的那条轴"的分量
                val axis = screenVerticalAxis()
                val rate = event.values[screenVerticalAxis()] * screenAxisFlip()
                val nowNs = event.timestamp
                if (lastEventNs != 0L) {
                    val dt = (nowNs - lastEventNs) / 1_000_000_000.0f
                    if (dt > 0 && dt < 0.2 && abs(rate) >= GYRO_DEADZONE_RATE) {
                        angleDeg += (rate * dt * 57.29578f) * ORIENTATION_SIGN
                    }
                }
                lastEventNs = nowNs
            }

            if (abs(angleDeg) < deadzoneDeg) angleDeg = 0f
            angleDeg = angleDeg.coerceIn(-gyroRangeDeg, gyroRangeDeg)

            val x = ((angleDeg / gyroRangeDeg) * 127f).roundToInt()
            if (x == lastGyroX) return
            lastGyroX = x
            leftStick.setGyro(x)
            gyroBar.value = x
            gyroBar.degrees = angleDeg
            gyroBar.invalidate()

            val now = SystemClock.elapsedRealtime()
            if (now - lastGyroSendAt < GYRO_SEND_INTERVAL_MS) return
            lastGyroSendAt = now
            Controller.send()
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
            // 不需要
        }
    }

    /**
     * 相对旋转 M = R · R0ᵀ（机身坐标系里）。
     * GYRO_AXIS = AXIS_AUTO：把 M 变回世界坐标系（W = R0ᵀ M R0），取绕**世界竖直轴**的分量 —— 平放和竖着拿都对。
     * 固定轴（X/Y/Z）时直接取 M 里那条轴的分量。右手定则正 = 从轴的正方向看逆时针。
     */
    private fun axisAngle(): Float {
        for (i in 0 until 3) {
            for (j in 0 until 3) {
                var sum = 0f
                for (k in 0 until 3) sum += rotationMatrix[i * 3 + k] * baseMatrix[j * 3 + k]
                relative[i * 3 + j] = sum
            }
        }

        val m: FloatArray
        if (GYRO_AXIS == AXIS_AUTO) {
            // W = R0ᵀ · M · R0
            val tmp = FloatArray(9)
            for (i in 0 until 3) {
                for (j in 0 until 3) {
                    var sum = 0f
                    for (k in 0 until 3) sum += baseMatrix[k * 3 + i] * relative[k * 3 + j]
                    tmp[i * 3 + j] = sum
                }
            }
            for (i in 0 until 3) {
                for (j in 0 until 3) {
                    var sum = 0f
                    for (k in 0 until 3) sum += tmp[i * 3 + k] * baseMatrix[k * 3 + j]
                    worldRelative[i * 3 + j] = sum
                }
            }
            m = worldRelative
        } else {
            m = relative
        }

        val axis = if (GYRO_AXIS == AXIS_AUTO) 2 else GYRO_AXIS
        val sin: Float
        val cos: Float
        when (axis) {
            1 -> {
                sin = (m[0 * 3 + 2] - m[2 * 3 + 0]) / 2f
                cos = (m[0 * 3 + 0] + m[2 * 3 + 2]) / 2f
            }
            0 -> {
                sin = (m[1 * 3 + 2] - m[2 * 3 + 1]) / 2f
                cos = (m[1 * 3 + 1] + m[2 * 3 + 2]) / 2f
            }
            else -> {
                sin = (m[0 * 3 + 1] - m[1 * 3 + 0]) / 2f
                cos = (m[0 * 3 + 0] + m[1 * 3 + 1]) / 2f
            }
        }
        return atan2(sin, cos)
    }

    /** 只有陀螺仪的退路：屏幕里"看起来竖直"的那条机身轴（竖屏 = Y，横屏 = X） */
    private fun screenVerticalAxis(): Int {
        return if (displayRotation() == 1 || displayRotation() == 3) 0 else 1
    }

    /** 屏幕转了 180° / 270° 时，那条轴的方向反过来 */
    private fun screenAxisFlip(): Float {
        val rotation = displayRotation()
        return if (rotation == 2 || rotation == 3) -1f else 1f
    }

    @Suppress("DEPRECATION")
    private fun displayRotation(): Int {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                display?.rotation ?: windowManager.defaultDisplay.rotation
            } else {
                windowManager.defaultDisplay.rotation
            }
        } catch (t: Throwable) {
            0
        }
    }

    private fun saveBase() {
        val p = prefs ?: return
        p.edit().putString("gyro_ref", baseMatrix.joinToString(",")).apply()
    }

    private fun recenter() {
        if (!gyroOn) {
            gyroBar.showHint("体感没开，先在第一屏打开「体感→左摇杆」")
            return
        }
        if (!useOrientation) {
            // 只有陀螺仪时没有绝对姿态：把当前当成 0，从这儿开始重新积分
            angleDeg = 0f
            lastEventNs = 0L
            lastGyroX = 0
            gyroBar.showHint("已回正（只有陀螺仪：从当前开始重新算）")
            Controller.send()
            return
        }
        for (i in 0 until 9) baseMatrix[i] = rotationMatrix[i]
        basePending = false
        saveBase()
        angleDeg = 0f
        lastGyroX = 0
        gyroBar.showHint("已回正（当前姿态 = 0）")
        Controller.send()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_gamepad)
        LayoutConfig.load(this)

        prefs = getSharedPreferences("xpadjoy", Context.MODE_PRIVATE)

        (findViewById(R.id.pad_close) as Button).setOnClickListener { finish() }
        centerButton = findViewById(R.id.gyro_center) as Button
        centerButton.setOnClickListener { recenter() }

        leftStick = findViewById(R.id.left_stick) as StickView
        gyroBar = findViewById(R.id.gyro_bar) as GyroBarView

        bindControls()
        Immersive.apply(this)

        sensorManager = getSystemService(SensorManager::class.java)
        val picked = sensorManager?.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)
            ?: sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
            ?: sensorManager?.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        sensor = picked
        useOrientation = picked != null && picked.type != Sensor.TYPE_GYROSCOPE
    }

    override fun onResume() {
        super.onResume()
        val p = prefs ?: getSharedPreferences("xpadjoy", Context.MODE_PRIVATE)
        prefs = p
        gyroOn = p.getBoolean("gyro", false)
        gyroRangeDeg = p.getInt("gyro_range", 8).coerceIn(3, 90).toFloat()
        deadzoneDeg = (gyroRangeDeg * 0.04f).coerceAtLeast(0.05f)

        gyroBar.gyroEnabled = gyroOn
        gyroBar.rangeDeg = gyroRangeDeg.toInt()
        leftStick.gyroDriven = gyroOn

        angleDeg = 0f
        lastEventNs = 0L
        lastGyroX = 0
        gyroBar.value = 0
        gyroBar.degrees = 0f

        val saved = p.getString("gyro_ref", null)
        val parts = saved?.split(",")
        if (parts != null && parts.size == 9) {
            for (i in 0 until 9) baseMatrix[i] = parts[i].toFloatOrNull() ?: 0f
            basePending = false          // 上次回正存过的参照
        } else {
            basePending = true           // 没存过：进屏第一个读数当参照
        }
        gyroBar.invalidate()

        val manager = sensorManager
        val activeSensor = sensor
        if (!gyroOn || manager == null || activeSensor == null) {
            if (gyroOn) Log.w(TAG, "没有可用的姿态传感器，体感不生效")
            return
        }
        manager.registerListener(gyroListener, activeSensor, SensorManager.SENSOR_DELAY_FASTEST)
    }

    override fun onPause() {
        super.onPause()
        try {
            sensorManager?.unregisterListener(gyroListener)
        } catch (t: Throwable) {
            Log.e(TAG, "取消监听失败", t)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        Immersive.reapply(this, hasFocus)
    }

    private fun bindControls() {
        bind(R.id.a, "A", Protocol.BTN_A)
        bind(R.id.b, "B", Protocol.BTN_B)
        bind(R.id.x, "X", Protocol.BTN_X)
        bind(R.id.y, "Y", Protocol.BTN_Y)
        bind(R.id.lb, "LB", Protocol.BTN_LB)
        bind(R.id.rb, "RB", Protocol.BTN_RB)
        bind(R.id.back, "BACK", Protocol.BTN_BACK)
        bind(R.id.guide, "GUIDE", Protocol.BTN_GUIDE)
        bind(R.id.start, "START", Protocol.BTN_START)

        leftStick.isLeft = true
        leftStick.label = "左摇杆"
        leftStick.pressBit = Protocol.BTN_L3
        leftStick.pressLabel = "L3"
        leftStick.configure(Controller.state, Controller::send)

        val rightStick = findViewById(R.id.right_stick) as StickView
        rightStick.isLeft = false
        rightStick.label = "右摇杆"
        rightStick.pressBit = Protocol.BTN_R3
        rightStick.pressLabel = "R3"
        rightStick.configure(Controller.state, Controller::send)

        val dpad = findViewById(R.id.dpad) as DpadView
        dpad.label = "十字键"
        dpad.configure(Controller.state, Controller::send)

        val lt = findViewById(R.id.lt) as TriggerView
        lt.isLeft = true
        lt.label = "LT"
        lt.configure(Controller.state, Controller::send)

        val rt = findViewById(R.id.rt) as TriggerView
        rt.isLeft = false
        rt.label = "RT"
        rt.configure(Controller.state, Controller::send)
    }

    private fun bind(id: Int, label: String, bit: Int, roundRect: Boolean = false) {
        val view = findViewById(id) as ControlView
        view.label = label
        view.bit = bit
        if (roundRect) view.shape = Shape.ROUND_RECT
        view.configure(Controller.state, Controller::send)
    }

    companion object {
        private const val TAG = "XjoyPad"

        private const val AXIS_X = 0
        private const val AXIS_Y = 1
        private const val AXIS_Z = 2
        private const val AXIS_AUTO = 3
        /** AXIS_AUTO = 绕世界竖直轴（平放和竖着拿都对）；想固定某个机身轴就改成 AXIS_X / AXIS_Y / AXIS_Z */
        private const val GYRO_AXIS = AXIS_AUTO

        private const val GYRO_DEADZONE_RATE = 0.02f  // 退路（角速度积分）用的死区
        private const val GYRO_SEND_INTERVAL_MS = 30L

        /** 从轴的正方向看逆时针为正（= 向左）。你这台机器上反了，所以取 1：向左 → 摇杆负 ✓。反了就改回 -1 */
        private const val ORIENTATION_SIGN = 1f
    }
}
