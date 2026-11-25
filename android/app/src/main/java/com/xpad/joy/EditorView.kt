package com.xpad.joy

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View

/**
 * 布局编辑器画布（画的就是手柄屏的实际区域）。
 * - 单个槽：点选后拖动移位，滑条改大小
 * - 正方形框（组）：点框内任意位置选中整组，拖动移动整组，滑条改边长和框内按键大小
 * 保存后手柄屏按同一份配置摆放。
 */
class EditorView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    var selectedSlotName: String? = null
    var selectedGroupName: String? = null
    var onSelection: () -> Unit = {}

    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG)
    private val groupRing = Paint(Paint.ANTI_ALIAS_FLAG)
    private val select = Paint(Paint.ANTI_ALIAS_FLAG)
    private val direction = Paint(Paint.ANTI_ALIAS_FLAG)
    private val text = Paint(Paint.ANTI_ALIAS_FLAG)

    private var grabDX = 0f
    private var grabDY = 0f

    init {
        stroke.style = Paint.Style.STROKE
        stroke.strokeWidth = 2f * density
        stroke.color = Palette.line

        groupRing.style = Paint.Style.STROKE
        groupRing.strokeWidth = 2f * density
        groupRing.color = Palette.accent
        groupRing.pathEffect = DashPathEffect(floatArrayOf(10f * density, 8f * density), 0f)

        select.style = Paint.Style.STROKE
        select.strokeWidth = 3f * density
        select.color = Palette.accent

        text.color = Palette.ink
        text.textAlign = Paint.Align.CENTER
        text.textSize = 11f * density

        direction.style = Paint.Style.STROKE
        direction.strokeWidth = 2.5f * density
        direction.strokeCap = Paint.Cap.ROUND
        direction.color = Palette.accent
    }

    private fun slotRect(s: Slot): RectF = LayoutConfig.rectFor(s, width, height, density)

    private fun groupRect(g: Group): RectF = LayoutConfig.rectForGroup(g, width, height, density)

    fun selectedSlot(): Slot? = selectedSlotName?.let { LayoutConfig.slotByName(it) }

    fun selectedGroup(): Group? = selectedGroupName?.let { LayoutConfig.groupByName(it) }

    override fun onDraw(canvas: Canvas) {
        for (g in LayoutConfig.groups) {
            val r = groupRect(g)
            canvas.drawRoundRect(r, 8f * density, 8f * density, groupRing)
        }

        for (s in LayoutConfig.slots) {
            val r = slotRect(s)
            val corner = min(r.width(), r.height()) / 2f
            val inGroup = !s.group.isEmpty() && s.group == selectedGroupName
            fill.color = if (inGroup) Palette.arm else Palette.panel
            if (s.canRotate && s.angle != 0f) {
                // 能转的槽（LT/RT）：按旋转后的形状画，线指向按到底那一头
                canvas.save()
                canvas.translate(r.centerX(), r.centerY())
                canvas.rotate(s.angle)
                val pw = s.w * density
                val ph = s.h * density
                val local = RectF(-pw / 2f, -ph / 2f, pw / 2f, ph / 2f)
                val c = min(pw, ph) / 2f
                canvas.drawRoundRect(local, c, c, fill)
                canvas.drawRoundRect(local, c, c, stroke)
                canvas.drawLine(0f, 0f, 0f, ph / 2f - c / 2f, direction)
                canvas.restore()
            } else {
                canvas.drawRoundRect(r, corner, corner, fill)
                canvas.drawRoundRect(r, corner, corner, stroke)
            }
            if (s.name == selectedSlotName) canvas.drawRoundRect(r, corner, corner, select)
            canvas.drawText(s.name, r.centerX(), r.centerY() + text.textSize / 3f, text)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                // 按键在框之上，先逆序命中按键，再命中框
                val hit = LayoutConfig.slots.lastOrNull { slotRect(it).contains(event.x, event.y) }
                val group = hit?.group?.takeIf { it.isNotEmpty() }?.let { LayoutConfig.groupByName(it) }
                    ?: LayoutConfig.groups.lastOrNull { groupRect(it).contains(event.x, event.y) }

                if (group != null) {
                    selectedGroupName = group.name
                    selectedSlotName = null
                    val r = groupRect(group)
                    grabDX = event.x - r.centerX()
                    grabDY = event.y - r.centerY()
                } else if (hit != null) {
                    selectedSlotName = hit.name
                    selectedGroupName = null
                    val r = slotRect(hit)
                    grabDX = event.x - r.centerX()
                    grabDY = event.y - r.centerY()
                } else {
                    return true
                }

                onSelection()
                invalidate()
            }
            MotionEvent.ACTION_MOVE -> {
                val g = selectedGroup()
                if (g != null) {
                    g.cx = ((event.x - grabDX) / width).coerceIn(0f, 1f)
                    g.cy = ((event.y - grabDY) / height).coerceIn(0f, 1f)
                } else {
                    val s = selectedSlot() ?: return true
                    s.cx = ((event.x - grabDX) / width).coerceIn(0f, 1f)
                    s.cy = ((event.y - grabDY) / height).coerceIn(0f, 1f)
                }
                invalidate()
            }
        }
        return true
    }

    private fun min(a: Float, b: Float): Float = if (a < b) a else b
}
