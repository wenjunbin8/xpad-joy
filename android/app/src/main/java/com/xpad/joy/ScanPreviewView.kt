package com.xpad.joy

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.min

/**
 * 扫码页的画面 + 四角括号，一个 View 全画完。
 *
 * 为什么不用 ImageView：这台机器硬件加速关着，ImageView 放大位图走的是软件路径、而且默认不滤波
 * （nearest-neighbor）→ 小图放大就是马赛克。这里自己画，`isFilterBitmap = true` 拿双线性。
 * 位图由 QrScanActivity 在后台线程算好像素、再在 UI 线程 setPixels + invalidate（所以这里只在 UI 线程读）。
 */
class ScanPreviewView : View {

    var bitmap: Bitmap? = null

    /** true = 这一帧扫到了（括号变绿） */
    var hit = false

    private val paint = Paint()
    private val cornerColors = intArrayOf(
        0xFF3B82F6.toInt(),   // 左上
        0xFFF59E0B.toInt(),   // 右上
        0xFF22C55E.toInt(),   // 左下
        0xFFEF4444.toInt(),   // 右下
    )

    constructor(context: Context) : super(context)
    constructor(context: Context, attrs: AttributeSet?) : super(context, attrs, 0)

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (width == 0 || height == 0) return
        val d = resources.displayMetrics.density

        paint.isFilterBitmap = true
        paint.isDither = true

        val image = bitmap
        if (image == null || image.width <= 0 || image.height <= 0) return

        val inset = 14f * d
        val availW = width - inset * 2
        val availH = height - inset * 2
        if (availW <= 0 || availH <= 0) return

        val scale = min(availW / image.width.toFloat(), availH / image.height.toFloat())
        val drawW = image.width * scale
        val drawH = image.height * scale
        val left = (width - drawW) / 2f
        val top = (height - drawH) / 2f
        canvas.drawBitmap(image, null, RectF(left, top, left + drawW, top + drawH), paint)

        // 四角括号：按画面实际画出来的范围，不是按整个 View
        val bracketInset = 26f * d
        val len = 42f * d
        paint.style = Paint.Style.STROKE
        paint.strokeCap = Paint.Cap.ROUND
        paint.strokeWidth = 4f * d
        val green = 0xFF22C55E.toInt()

        corner(canvas, left + bracketInset, top + bracketInset, 1, 1, len, if (hit) green else cornerColors[0])
        corner(canvas, left + drawW - bracketInset, top + bracketInset, -1, 1, len, if (hit) green else cornerColors[1])
        corner(canvas, left + bracketInset, top + drawH - bracketInset, 1, -1, len, if (hit) green else cornerColors[2])
        corner(canvas, left + drawW - bracketInset, top + drawH - bracketInset, -1, -1, len, if (hit) green else cornerColors[3])
    }

    private fun corner(canvas: Canvas, x: Float, y: Float, dirX: Int, dirY: Int, len: Float, color: Int) {
        paint.color = color
        canvas.drawLine(x, y, x + dirX * len, y, paint)
        canvas.drawLine(x, y, x, y + dirY * len, paint)
    }
}
