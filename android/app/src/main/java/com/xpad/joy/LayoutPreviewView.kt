package com.xpad.joy

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.max
import kotlin.math.min

/**
 * 第一屏「布局」卡片里的缩略图：按手柄（横屏）的实际比例画当前 LayoutConfig。
 * 之前直接把归一化坐标映射到卡片尺寸（竖屏比例），所以按键全部叠在一起。
 * 现在先按屏幕比例算出缩放系数，再居中画，形状比例与手柄屏一致。
 */
class LayoutPreviewView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG)
    private val groupRing = Paint(Paint.ANTI_ALIAS_FLAG)
    private val bounds = Paint(Paint.ANTI_ALIAS_FLAG)
    private val direction = Paint(Paint.ANTI_ALIAS_FLAG)
    private val text = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        fill.color = Palette.panel

        stroke.style = Paint.Style.STROKE
        stroke.strokeWidth = 1.5f * density
        stroke.color = Palette.line

        groupRing.style = Paint.Style.STROKE
        groupRing.strokeWidth = 1.5f * density
        groupRing.color = Palette.accent
        groupRing.pathEffect = DashPathEffect(floatArrayOf(8f * density, 6f * density), 0f)

        bounds.style = Paint.Style.STROKE
        bounds.strokeWidth = 1.5f * density
        bounds.color = Palette.line

        direction.style = Paint.Style.STROKE
        direction.strokeWidth = 1.5f * density
        direction.color = Palette.accent

        text.color = Palette.ink
        text.textAlign = Paint.Align.CENTER
    }

    override fun onDraw(canvas: Canvas) {
        val metrics = resources.displayMetrics
        val longPx = max(metrics.widthPixels, metrics.heightPixels).toFloat()
        val shortPx = min(metrics.widthPixels, metrics.heightPixels).toFloat()
        if (longPx <= 0f || shortPx <= 0f) return

        // 等比缩放到卡片里，居中（上下留白）
        val scale = min(width / longPx, height / shortPx)
        if (scale <= 0f) return
        val drawW = longPx * scale
        val drawH = shortPx * scale
        val ox = (width - drawW) / 2f
        val oy = (height - drawH) / 2f

        canvas.drawRect(ox, oy, ox + drawW, oy + drawH, bounds)

        for (g in LayoutConfig.groups) {
            val side = g.side * density * scale
            val cx = ox + g.cx * drawW
            val cy = oy + g.cy * drawH
            canvas.drawRoundRect(
                RectF(cx - side / 2f, cy - side / 2f, cx + side / 2f, cy + side / 2f),
                min(6f * density, side / 6f), min(6f * density, side / 6f), groupRing,
            )
        }

        for (s in LayoutConfig.slots) {
            val pw = s.w * density * scale
            val ph = s.h * density * scale
            val cx = ox + s.cx * drawW
            val cy = oy + s.cy * drawH
            val corner = min(pw, ph) / 2f
            if (s.canRotate && s.angle != 0f) {
                canvas.save()
                canvas.translate(cx, cy)
                canvas.rotate(s.angle)
                val local = RectF(-pw / 2f, -ph / 2f, pw / 2f, ph / 2f)
                canvas.drawRoundRect(local, corner, corner, fill)
                canvas.drawRoundRect(local, corner, corner, stroke)
                canvas.drawLine(0f, 0f, 0f, ph / 2f - corner / 2f, direction)   // 按到底那一头
                canvas.restore()
            } else {
                val r = RectF(cx - pw / 2f, cy - ph / 2f, cx + pw / 2f, cy + ph / 2f)
                canvas.drawRoundRect(r, corner, corner, fill)
                canvas.drawRoundRect(r, corner, corner, stroke)
            }

            text.textSize = min(14f * density, min(pw, ph) * 0.34f)
            if (text.textSize < 6f * density) continue   // 太小就不写字，避免糊
            val fm = text.fontMetrics
            canvas.drawText(s.name, cx, cy - (fm.ascent + fm.descent) / 2f, text)
        }
    }
}
