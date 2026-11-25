package com.xpad.joy

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

object Palette {
    // 蓝黑主题（更耐看）
    val bg: Int = Color.parseColor("#111519")
    val panel: Int = Color.parseColor("#232A33")
    val arm: Int = Color.parseColor("#2C3641")
    val accent: Int = Color.parseColor("#3B82F6")
    val line: Int = Color.parseColor("#465361")
    val ink: Int = Color.parseColor("#E7ECF3")
    val dim: Int = Color.parseColor("#8A94A2")
    val knob: Int = Color.parseColor("#E9EDF2")
}

enum class Shape { CIRCLE, ROUND_RECT }

/**
 * 所有触控控件的基类：
 *  - 一个控件只认「第一个按在它上面的手指」，其余手指按别的控件互不影响
 *  - Android 会把同一根手指从按下到抬起的整段事件派发给同一个 View
 *  - square = true 时强制成正方形，避免被拉伸成长条
 *  - highlightOnPress = false：按下不染色（摇杆用，染色会挡住摇杆帽）
 *  - angle：把控件自身绕中心转一个角度（LT/RT 用）。PadContainer 把 View 的尺寸设成
 *    旋转后的外接框，所以画和判定都要用 baseW/baseH（旋转前自己的尺寸），触摸点要反向旋转回自己的坐标系。
 */
abstract class ControlView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    var label: String = ""
    var bit: Int = -1
    /** 双击摇杆时用这个位（L3/R3），与摇杆方向互不干扰 */
    var pressBit: Int = -1
    var pressLabel: String = ""
    var shape: Shape = Shape.CIRCLE
    var cornerLabel: Boolean = false
    var square: Boolean = false
    var highlightOnPress: Boolean = true

    /** 自身旋转角度（度，顺时针）。0 = 不转 */
    var angle: Float = 0f
    /** 旋转前自己的尺寸（像素）。View 的 bounds 是旋转后的外接框，所以这两个值要单独给 */
    var baseW: Float = 0f
    var baseH: Float = 0f

    protected fun ownW(): Float = if (baseW > 0f) min(baseW, width.toFloat()) else width.toFloat()
    protected fun ownH(): Float = if (baseH > 0f) min(baseH, height.toFloat()) else height.toFloat()

    protected var state: GamepadState = GamepadState()
    private var onChanged: () -> Unit = {}

    protected var isDown: Boolean = false
    protected var pointerId: Int = -1

    private var downX = 0f
    private var downY = 0f
    private var downAt = 0L
    private var moved = false

    protected val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    protected val stroke = Paint(Paint.ANTI_ALIAS_FLAG)
    protected val textPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        isClickable = true
        stroke.style = Paint.Style.STROKE
        stroke.strokeWidth = dp(2f)
        stroke.color = Palette.line
        textPaint.color = Palette.ink
        textPaint.textAlign = Paint.Align.CENTER
    }

    fun configure(target: GamepadState, notify: () -> Unit) {
        state = target
        onChanged = notify
    }

    protected fun dp(v: Float): Float = v * resources.displayMetrics.density

    protected fun changed() {
        onChanged()
        invalidate()
    }

    protected open fun onPointer(x: Float, y: Float) {}

    /** 按下那一刻的坐标（控件自己坐标系）。扳机用它当起点：按下先给 0，拖动才涨 */
    protected open fun onPress(x: Float, y: Float) {}

    /** 判定为「点击」：按下到抬起不超过 TAP_MS，且手指没有明显移动 */
    protected open fun onTap(x: Float, y: Float) {}

    protected open fun onReleased() {
        isDown = false
        if (bit >= 0) state.setBit(bit, false)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        if (square) {
            val side = min(measuredWidth, measuredHeight)
            setMeasuredDimension(side, side)
        }
    }

    /** 触摸点（View 坐标系 = 旋转后的外接框）→ 控件自己的坐标系 */
    private fun toLocal(x: Float, y: Float): Pair<Float, Float> {
        if (angle == 0f) return Pair(x, y)
        val rad = Math.toRadians(angle.toDouble())
        val c = cos(rad).toFloat()
        val s = sin(rad).toFloat()
        val dx = x - width / 2f
        val dy = y - height / 2f
        // canvas.rotate(正角度) 是屏幕上的顺时针，所以逆变换是反号
        return Pair(ownW() / 2f + dx * c + dy * s, ownH() / 2f - dx * s + dy * c)
    }

    /** 转了角度以后，外接框的四个角其实不在形状上：手指按在角上不判定 */
    private fun inside(x: Float, y: Float): Boolean {
        if (angle == 0f) return true
        val p = toLocal(x, y)
        if (shape == Shape.CIRCLE) return hypot(p.first - ownW() / 2f, p.second - ownH() / 2f) <= circleRadius()
        return p.first >= 0f && p.second >= 0f && p.first <= ownW() && p.second <= ownH()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                if (pointerId == -1) {
                    if (!inside(event.getX(event.actionIndex), event.getY(event.actionIndex))) return true
                    pointerId = event.actionIndex
                    isDown = true
                    moved = false
                    downAt = System.currentTimeMillis()
                    val p = toLocal(event.getX(pointerId), event.getY(pointerId))
                    downX = p.first
                    downY = p.second
                    if (bit >= 0) state.setBit(bit, true)
                    onPress(downX, downY)
                    onPointer(downX, downY)
                    changed()
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (pointerId != -1) {
                    val p = toLocal(event.getX(pointerId), event.getY(pointerId))
                    if (hypot(p.first - downX, p.second - downY) > dp(18f)) moved = true
                    onPointer(p.first, p.second)
                    changed()
                }
            }
            MotionEvent.ACTION_POINTER_UP, MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                if (pointerId == event.actionIndex) {
                    val p = toLocal(event.getX(event.actionIndex), event.getY(event.actionIndex))
                    if (!moved && System.currentTimeMillis() - downAt <= TAP_MS) onTap(p.first, p.second)
                    onReleased()
                    pointerId = -1
                    changed()
                }
            }
        }
        return true
    }

    override fun onDraw(canvas: Canvas) {
        canvas.save()
        if (angle != 0f) {
            canvas.translate(width / 2f, height / 2f)
            canvas.rotate(angle)
            canvas.translate(-ownW() / 2f, -ownH() / 2f)
        }
        drawBackground(canvas)
        drawExtra(canvas)
        drawLabel(canvas)
        canvas.restore()
    }

    protected open fun drawExtra(canvas: Canvas) {}

    protected fun circleRadius(): Float {
        val r = min(ownW(), ownH()) / 2f - dp(4f)
        return if (r > 0) r else 0f
    }

    private fun drawBackground(canvas: Canvas) {
        val pad = dp(4f)
        val w = ownW()
        val h = ownH()
        fill.color = if (highlightOnPress && isDown) Palette.accent else Palette.panel
        if (shape == Shape.CIRCLE) {
            val r = circleRadius()
            if (r > 0) {
                canvas.drawCircle(w / 2f, h / 2f, r, fill)
                canvas.drawCircle(w / 2f, h / 2f, r, stroke)
            }
        } else {
            val rect = RectF(pad, pad, w - pad, h - pad)
            canvas.drawRoundRect(rect, dp(10f), dp(10f), fill)
            canvas.drawRoundRect(rect, dp(10f), dp(10f), stroke)
        }
    }

    private fun drawLabel(canvas: Canvas) {
        if (label.isEmpty()) return
        val w = ownW()
        val h = ownH()
        val fm = textPaint.fontMetrics
        if (cornerLabel) {
            textPaint.textSize = dp(12f)
            textPaint.color = Palette.dim
            textPaint.textAlign = Paint.Align.LEFT
            canvas.drawText(label, dp(8f), dp(8f) - fm.ascent, textPaint)
        } else {
            textPaint.textSize = min(w, h) * 0.34f
            textPaint.color = if (highlightOnPress && isDown) Color.WHITE else Palette.ink
            canvas.drawText(label, w / 2f, h / 2f - (fm.ascent + fm.descent) / 2f, textPaint)
        }
    }

    companion object {
        const val TAP_MS = 250
        const val DOUBLE_TAP_MS = 350
    }
}

/** 圆形按键（ABXY、GUIDE、BACK、START、LB、RB） */
class GameButtonView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ControlView(context, attrs)

/** 十字键：8 方向，写入 HID hat 值（0=上 … 7=左上，8=中立）。画成方形十字 + chevron */
class DpadView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ControlView(context, attrs) {

    private val armPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val chevron = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()
    private var dir: Int = Protocol.HAT_NEUTRAL

    init {
        shape = Shape.CIRCLE          // 圆形底盘（大小由 LayoutConfig 决定）
        cornerLabel = true
        chevron.style = Paint.Style.STROKE
        chevron.strokeWidth = dp(2.5f)
        chevron.strokeCap = Paint.Cap.ROUND
    }

    override fun onPointer(x: Float, y: Float) {
        val cx = ownW() / 2f
        val cy = ownH() / 2f
        val dx = x - cx
        val dy = y - cy
        if (hypot(dx, dy) < dp(16f)) {
            dir = Protocol.HAT_NEUTRAL
            state.applyHat(Protocol.HAT_NEUTRAL)
            return
        }
        val deg = Math.toDegrees(atan2(dy.toDouble(), dx.toDouble()))
        var idx = ((deg + 90.0) / 45.0).roundToInt()
        idx = ((idx % 8) + 8) % 8
        dir = idx
        state.applyHat(idx)
    }

    override fun onReleased() {
        super.onReleased()
        dir = Protocol.HAT_NEUTRAL
        state.applyHat(Protocol.HAT_NEUTRAL)
    }

    override fun drawExtra(canvas: Canvas) {
        val r = circleRadius()
        if (r <= 0f) return
        val cx = ownW() / 2f
        val cy = ownH() / 2f
        val t = dp(15f)
        val reach = r - dp(10f)          // 十字臂在圆内，不顶到描边
        armPaint.color = if (isDown) Palette.accent else Palette.arm
        canvas.drawRoundRect(RectF(cx - reach, cy - t / 2f, cx + reach, cy + t / 2f), t / 2f, t / 2f, armPaint)
        canvas.drawRoundRect(RectF(cx - t / 2f, cy - reach, cx + t / 2f, cy + reach), t / 2f, t / 2f, armPaint)

        for (d in intArrayOf(0, 2, 4, 6)) drawChevron(canvas, d)
    }

    private fun drawChevron(canvas: Canvas, hatDir: Int) {
        val cx = ownW() / 2f
        val cy = ownH() / 2f
        val r = circleRadius() - dp(20f)
        if (r <= 0f) return
        val angle = Math.toRadians(DEGREES[hatDir].toDouble()).toFloat()
        val px = cx + r * cos(angle)
        val py = cy + r * sin(angle)
        chevron.color = if (dir == hatDir) Color.WHITE else Palette.dim
        val size = dp(9f)
        path.rewind()
        path.moveTo(px + size * cos(angle + ARM), py + size * sin(angle + ARM))
        path.lineTo(px, py)
        path.lineTo(px + size * cos(angle - ARM), py + size * sin(angle - ARM))
        canvas.drawPath(path, chevron)
    }

    companion object {
        private val DEGREES = intArrayOf(-90, -45, 0, 45, 90, 135, 180, -135)
        private const val ARM = 2.4435f  // 140°
    }
}

/**
 * 摇杆：一个手指拖动摇杆帽，写入 -128..127；抬手归中；双击 = L3/R3（再双击取消）。
 * 按下不染色，摇杆帽的最大行程 = 半径 - 帽半径，所以帽不会顶出描边、不会盖住标签。
 */
class StickView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ControlView(context, attrs) {

    var isLeft: Boolean = true

    private val knob = Paint(Paint.ANTI_ALIAS_FLAG)
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG)
    private var nx: Float = 0f
    private var ny: Float = 0f
    private var latched = false
    /** 体感驱动时：手搓不生效、松手不回中，值由外部 setGyro 给 */
    var gyroDriven: Boolean = false
    /** 双击摇杆时的额外动作（体感回正） */
    var onDoubleTap: (() -> Unit)? = null
    private var lastTapAt = 0L

    init {
        shape = Shape.CIRCLE
        cornerLabel = true
        highlightOnPress = false
        ring.style = Paint.Style.STROKE
        ring.strokeWidth = dp(2f)
        ring.color = Palette.accent
    }

    private fun radius(): Float = circleRadius()

    private fun knobRadius(): Float = radius() * 0.42f

    /** 帽中心最远只能到这里，帽的边缘正好贴着描边 */
    private fun maxReach(): Float {
        val r = radius()
        val kr = knobRadius()
        return if (r > kr) r - kr else 0f
    }

    /** 体感值：只改显示位置 + 状态，不回中 */
    fun setGyro(value: Int) {
        state.setStick(isLeft, value, 0)
        nx = value / 127f
        ny = 0f
        invalidate()
    }

    override fun onTap(x: Float, y: Float) {
        if (pressBit < 0) return
        val now = System.currentTimeMillis()
        if (now - lastTapAt <= DOUBLE_TAP_MS) {
            latched = !latched
            state.setBit(pressBit, latched)
            lastTapAt = 0L
            onDoubleTap?.invoke()
        } else {
            lastTapAt = now
        }
        changed()
    }

    override fun onPointer(x: Float, y: Float) {
        val r = radius()
        if (r <= 0) return
        if (gyroDriven) return
        var px = (x - ownW() / 2f) / r
        var py = (y - ownH() / 2f) / r
        val mag = hypot(px, py)
        if (mag > 1f) {
            px /= mag
            py /= mag
        }
        if (mag < 0.12f) {   // 死区
            px = 0f
            py = 0f
        }
        nx = px
        ny = py
        state.setStick(isLeft, (px * 127f).roundToInt(), (py * 127f).roundToInt())
    }

    override fun onReleased() {
        super.onReleased()
        if (gyroDriven) return
        nx = 0f
        ny = 0f
        state.setStick(isLeft, 0, 0)
    }

    override fun drawExtra(canvas: Canvas) {
        val r = radius()
        if (r <= 0) return
        val cx = ownW() / 2f
        val cy = ownH() / 2f
        val kr = knobRadius()
        val reach = maxReach()
        knob.color = Palette.knob
        val kx = cx + nx * reach
        val ky = cy + ny * reach
        canvas.drawCircle(kx, ky, kr, knob)
        if (latched) {
            canvas.drawCircle(kx, ky, kr + dp(3f), ring)
            if (pressLabel.isNotEmpty()) {
                // 标签在左上角，L3/R3 状态写在描边内的下沿，不和摇杆帽重叠
                textPaint.textSize = dp(12f)
                textPaint.color = Palette.accent
                textPaint.textAlign = Paint.Align.LEFT
                val fm = textPaint.fontMetrics
                canvas.drawText(pressLabel, dp(8f), ownH() - dp(8f) - fm.descent, textPaint)
            }
        }
    }
}

/**
 * 模拟扳机：按下的那一刻输入 0，只有往「按到底」那个方向拖才涨（往回拖就降回 0）。
 * 可以绕中心转任意角度（布局页滑条，90° 整倍数吸附）：转 180° 后向上拖就是到底。
 * 深度按旋转后自己坐标系里的 y 算，所以方向跟着形状一起转，不用改别的代码。
 */
class TriggerView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ControlView(context, attrs) {

    var isLeft: Boolean = true

    private var depth: Float = 0f
    /** 按下那一刻的 y（自己坐标系）= 起点 */
    private var anchorY: Float = 0f
    private val bar = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        shape = Shape.ROUND_RECT
        cornerLabel = true
    }

    /** 单纯点一下是 0：起点就是按下的位置 */
    override fun onPress(x: Float, y: Float) {
        anchorY = y
        depth = 0f
        state.setTrigger(isLeft, 0)
    }

    override fun onPointer(x: Float, y: Float) {
        if (ownH() == 0f) return
        // 行程从按下的那点算：往「按到底」那一头拖，拖到最远端就是 255；往回拖就降回 0
        val span = max(ownH() - anchorY, dp(12f))
        depth = ((y - anchorY) / span).coerceIn(0f, 1f)
        state.setTrigger(isLeft, (depth * 255f).roundToInt())
    }

    override fun onReleased() {
        super.onReleased()
        depth = 0f
        anchorY = 0f
        state.setTrigger(isLeft, 0)
    }

    override fun drawExtra(canvas: Canvas) {
        val h = ownH()
        if (h == 0f) return
        bar.color = if (isDown) Color.WHITE else Palette.dim
        val pad = dp(4f)
        // 行程条固定从键的顶边开始画，长度 = 当前值。不按按下点画：从哪点开始亮会让用户误会。
        // 这段已经在旋转后的坐标系里画，所以「顶边」就是键自己的顶边（跟着键一起转）。
        val end = pad + (h - 2 * pad) * depth
        canvas.drawRoundRect(RectF(pad, pad, ownW() - pad, end), dp(6f), dp(6f), bar)
    }
}
