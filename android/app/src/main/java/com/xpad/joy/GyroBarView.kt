package com.xpad.joy

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import kotlin.math.roundToInt

/**
 * 体感进度条（只显示，不响应点击）：
 * 上面一条轨道（中心刻度），从中心往左或往右填；下面写「左 11°（-93）」。
 * 参照姿态是进手柄屏后的第一个读数，所以没有双击回正。
 */
class GyroBarView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    /** 当前值：-127（最左）… 0（中心）… 127（最右） */
    var value: Int = 0

    /** 相对参照姿态的角度（度），正 = 向右 */
    var degrees: Float = 0f

    var gyroEnabled = false

    /** 第一屏滑块那个度数：转满它 = 摇杆满量程（标签里显示） */
    var rangeDeg = 8

    private var hint = ""
    private var hintUntil = 0L

    private val track = Paint(Paint.ANTI_ALIAS_FLAG)
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val tick = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        track.color = Palette.dim
        track.alpha = 90
        fill.color = Palette.accent
        tick.color = Palette.ink
        tick.alpha = 150
        textPaint.color = Palette.ink
        textPaint.textAlign = Paint.Align.CENTER
        textPaint.textSize = dp(13f)
    }

    private fun dp(v: Float): Float = v * resources.displayMetrics.density

    fun showHint(text: String) {
        hint = text
        hintUntil = System.currentTimeMillis() + 1400L
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        val barH = dp(12f)
        if (w <= 0f || h < barH + dp(18f)) return

        track.alpha = if (gyroEnabled) 110 else 60
        canvas.drawRoundRect(0f, 0f, w, barH, barH / 2f, barH / 2f, track)

        val cx = w / 2f
        tick.strokeWidth = dp(2f)
        canvas.drawLine(cx, 0f, cx, barH, tick)

        if (gyroEnabled && value != 0) {
            val half = w / 2f - barH / 2f
            val pos = cx + (value / 127f) * half
            val left = if (pos < cx) pos else cx
            val right = if (pos < cx) cx else pos
            canvas.drawRoundRect(left, 0f, right, barH, barH / 2f, barH / 2f, fill)
        }

        val label = when {
            hint.isNotEmpty() && System.currentTimeMillis() < hintUntil -> hint
            !gyroEnabled -> "体感关"
            value == 0 -> "体感 0°（参照 = 进屏第一个读数）"
            else -> "${if (value < 0) "左" else "右"} ${degrees.roundToInt()}°/${rangeDeg}°（${value}）"
        }
        canvas.drawText(label, w / 2f, barH + dp(16f), textPaint)
    }
}
