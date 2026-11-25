package com.xpad.joy

import android.content.Context
import android.graphics.Rect
import android.graphics.RectF
import android.util.AttributeSet
import android.view.ViewGroup

/**
 * 按 LayoutConfig 摆放子控件：手柄屏的根容器。
 * 每个按键的大小和位置完全由配置决定（在组里的槽由正方形框决定）。
 */
class PadContainer @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ViewGroup(context, attrs) {

    private val density = resources.displayMetrics.density

    /** 只有能转的槽需要「旋转前自己的尺寸」。组里的槽（ABXY）要用 View 自己的尺寸，
     *  不然画的圆比 View 大 → 被裁切（边长改小时尤其明显） */
    private fun applyRotation(child: android.view.View, slot: Slot, density: Float) {
        if (child !is ControlView) return
        if (!slot.canRotate) {
            child.angle = 0f
            child.baseW = 0f
            child.baseH = 0f
            return
        }
        child.angle = slot.angle
        child.baseW = slot.w * density
        child.baseH = slot.h * density
    }

    private fun clamp(rect: RectF, w: Int, h: Int): Rect {
        var left = rect.left.toInt()
        var top = rect.top.toInt()
        var right = rect.right.toInt()
        var bottom = rect.bottom.toInt()
        // 越界回收，保证按键不会跑到屏幕外
        if (left < 0) { right -= left; left = 0 }
        if (top < 0) { bottom -= top; top = 0 }
        if (right > w) { left -= right - w; right = w }
        if (bottom > h) { top -= bottom - h; bottom = h }
        if (left < 0) left = 0
        if (top < 0) top = 0
        return Rect(left, top, right, bottom)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val w = MeasureSpec.getSize(widthMeasureSpec)
        val h = MeasureSpec.getSize(heightMeasureSpec)
        for (i in 0 until childCount) {
            val child = getChildAt(i)
            val slot = LayoutConfig.slotFor(child.id)
            if (slot == null) {
                child.measure(
                    MeasureSpec.makeMeasureSpec(0, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(0, MeasureSpec.EXACTLY),
                )
                continue
            }
            val rect = LayoutConfig.rectFor(slot, w, h, density)
            applyRotation(child, slot, density)
            child.measure(
                MeasureSpec.makeMeasureSpec(rect.width().toInt(), MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(rect.height().toInt(), MeasureSpec.EXACTLY),
            )
        }
        setMeasuredDimension(w, h)
    }

    override fun onLayout(changed: Boolean, l: Int, t: Int, r: Int, b: Int) {
        val w = r - l
        val h = b - t
        for (i in 0 until childCount) {
            val child = getChildAt(i)
            val slot = LayoutConfig.slotFor(child.id)
            if (slot == null) continue
            val rect = clamp(LayoutConfig.rectFor(slot, w, h, density), w, h)
            applyRotation(child, slot, density)
            child.layout(rect.left, rect.top, rect.right, rect.bottom)
        }
    }

    /** 配置改完后重新按新配置摆放 */
    fun relayout() {
        requestLayout()
    }
}
