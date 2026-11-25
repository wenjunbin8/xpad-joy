package com.xpad.joy

import android.content.Context
import android.graphics.RectF
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/** 不在组里的槽：归一化中心 + dp 尺寸（angle = 绕中心旋转，只有 canRotate 的槽能用） */
data class Slot(
    val name: String,
    val circle: Boolean,
    val resId: Int,
    var cx: Float,
    var cy: Float,
    var w: Float,
    var h: Float,
    val group: String = "",
    val rx: Float = 0f,   // 组内相对位置（单位 = 边长）
    val ry: Float = 0f,
    var angle: Float = 0f,
    val canRotate: Boolean = false,
    val lockRatio: Boolean = false,   // 等比例调（LT/RT）：只改长边，短边按 ratio 算
    val ratio: Float = 0f,            // w / h
)

/** 正方形框：边长和框内按键大小锁定一起调整（按键大小 = 边长 × ratio） */
data class Group(
    val name: String,
    var cx: Float,
    var cy: Float,
    var side: Float,
    var ratio: Float,
) {
    val keySize: Float get() = side * ratio
}

/**
 * 可自定义布局：手柄屏和编辑器都读同一份配置。
 * 保存到 SharedPreferences（xpadjoy / layout_json）。
 */
object LayoutConfig {

    private const val PREFS = "xpadjoy"
    private const val KEY = "layout_json"

    const val MIN_SIZE = 24
    const val MAX_SIZE = 200
    const val MAX_SIDE = 240
    const val MAX_ANGLE = 359
    /** 滑条靠近 90° 的整倍数时吸上去（0 / 90 / 180 / 270），方便摆正 */
    /** 滑条 1 格 = 5°，所以吸附窗口就是 5°（整倍数 0/90/180/270） */
    const val SNAP_DEG = 5f

    val slots = ArrayList<Slot>()
    val groups = ArrayList<Group>()

    init {
        resetDefaults()
    }

    fun resetDefaults() {
        slots.clear()
        groups.clear()

        add("LT", false, R.id.lt, 0.055f, 0.270f, 70f, 120f, canRotate = true, lockRatio = true, ratio = 70f / 120f)
        add("LB", true, R.id.lb, 0.140f, 0.420f, 54f, 54f)
        add("十字键", true, R.id.dpad, 0.170f, 0.700f, 110f, 110f)
        add("左摇杆", true, R.id.left_stick, 0.310f, 0.820f, 110f, 110f)

        add("✕", true, R.id.pad_close, 0.500f, 0.130f, 44f, 44f)
        add("回正", false, R.id.gyro_center, 0.630f, 0.130f, 74f, 42f)
        add("体感条", false, R.id.gyro_bar, 0.500f, 0.560f, 190f, 40f)
        add("BACK", true, R.id.back, 0.425f, 0.320f, 46f, 46f)
        add("GUIDE", true, R.id.guide, 0.500f, 0.320f, 50f, 50f)
        add("START", true, R.id.start, 0.575f, 0.320f, 46f, 46f)

        add("RT", false, R.id.rt, 0.945f, 0.270f, 70f, 120f, canRotate = true, lockRatio = true, ratio = 70f / 120f)
        add("RB", true, R.id.rb, 0.860f, 0.420f, 54f, 54f)
        add("右摇杆", true, R.id.right_stick, 0.690f, 0.820f, 110f, 110f)

        // ABXY = 一个正方形框（边长 120dp，按键 = 边长 × 0.383 ≈ 46dp）
        groups.add(Group("ABXY", 0.830f, 0.700f, 120f, 46f / 120f))
        addGrouped("Y", R.id.y, 0f, -0.30f)
        addGrouped("A", R.id.a, 0f, 0.30f)
        addGrouped("X", R.id.x, -0.30f, 0f)
        addGrouped("B", R.id.b, 0.30f, 0f)
    }

    private fun add(
        name: String,
        circle: Boolean,
        resId: Int,
        cx: Float,
        cy: Float,
        w: Float,
        h: Float,
        canRotate: Boolean = false,
        lockRatio: Boolean = false,
        ratio: Float = 0f,
    ) {
        slots.add(Slot(name, circle, resId, cx, cy, w, h, "", 0f, 0f, 0f, canRotate, lockRatio, ratio))
    }

    /** 靠近 90° 整倍数就吸上去，其它角度按滑条 */
    /** 滑条 1 格 = 5°：滑条只负责粗调，精确角度用按钮 */
    fun snap(angle: Float): Float {
        var nearest = (angle / 90f).roundToInt() * 90f
        if (nearest >= 360f) nearest = 0f
        return if (abs(angle - nearest) <= SNAP_DEG) nearest else angle
    }

    private fun addGrouped(name: String, resId: Int, rx: Float, ry: Float) {
        slots.add(Slot(name, true, resId, 0f, 0f, 46f, 46f, "ABXY", rx, ry))
    }

    fun slotFor(resId: Int): Slot? = slots.firstOrNull { it.resId == resId }

    fun slotByName(name: String): Slot? = slots.firstOrNull { it.name == name }

    fun groupByName(name: String): Group? = groups.firstOrNull { it.name == name }

    /** 等比例改大小（LT/RT）：value = 长边（dp），短边按锁定的 ratio 算 */
    fun setSize(slot: Slot, value: Float) {
        if (!slot.lockRatio) {
            slot.w = value.coerceIn(MIN_SIZE.toFloat(), MAX_SIZE.toFloat())
            if (slot.circle) slot.h = slot.w
            return
        }
        val r = if (slot.ratio > 0f) slot.ratio else 1f
        // 长边下限 = MIN / 比例，这样短边也不会低于 MIN_SIZE
        val longSide = value.coerceIn(minLongSide(slot), MAX_SIZE.toFloat())
        if (r >= 1f) {
            slot.w = longSide
            slot.h = longSide / r
        } else {
            slot.h = longSide
            slot.w = longSide * r
        }
    }

    /** 等比例槽滑条的下限（长边）：短边不低于 MIN_SIZE */
    fun minLongSide(slot: Slot): Float = MIN_SIZE / min(1f, if (slot.ratio > 0f) slot.ratio else 1f)

    /** 面板滑条那一条画的是长边（等比例槽），其它槽还是宽 */
    fun longSide(slot: Slot): Float = if (slot.lockRatio) max(slot.w, slot.h) else slot.w

    /** 改边长时按键大小按锁定比例一起变 */
    fun setSide(group: Group, value: Float) {
        group.side = value.coerceIn(MIN_SIZE.toFloat(), MAX_SIDE.toFloat())
    }

    /** 槽的实际矩形（像素）：在组里的槽由正方形框决定 */
    fun rectFor(slot: Slot, widthPx: Int, heightPx: Int, density: Float): RectF {
        val group = if (slot.group.isEmpty()) null else groupByName(slot.group)
        if (group == null) {
            val cx = slot.cx * widthPx
            val cy = slot.cy * heightPx
            val pw = slot.w * density
            val ph = slot.h * density
            if (slot.canRotate && slot.angle != 0f) {
                // 旋转后的外接框：View 的 bounds 要变大，不然转 90° 会画到框外
                val rad = Math.toRadians(slot.angle.toDouble())
                val c = abs(cos(rad)).toFloat()
                val s = abs(sin(rad)).toFloat()
                val bw = pw * c + ph * s
                val bh = pw * s + ph * c
                return RectF(cx - bw / 2f, cy - bh / 2f, cx + bw / 2f, cy + bh / 2f)
            }
            return RectF(cx - pw / 2f, cy - ph / 2f, cx + pw / 2f, cy + ph / 2f)
        }
        val side = group.side * density
        val size = group.keySize * density
        val cx = group.cx * widthPx + slot.rx * side
        val cy = group.cy * heightPx + slot.ry * side
        return RectF(cx - size / 2f, cy - size / 2f, cx + size / 2f, cy + size / 2f)
    }

    fun rectForGroup(group: Group, widthPx: Int, heightPx: Int, density: Float): RectF {
        val side = group.side * density
        val cx = group.cx * widthPx
        val cy = group.cy * heightPx
        return RectF(cx - side / 2f, cy - side / 2f, cx + side / 2f, cy + side / 2f)
    }

    fun load(context: Context) {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
        if (json == null) return
        try {
            val root = JSONObject(json)

            val groupsArr = root.optJSONArray("groups")
            if (groupsArr != null) {
                for (i in 0 until groupsArr.length()) {
                    val o = groupsArr.optJSONObject(i) ?: continue
                    val g = groupByName(o.optString("name")) ?: continue
                    g.cx = o.optDouble("cx", g.cx.toDouble()).toFloat()
                    g.cy = o.optDouble("cy", g.cy.toDouble()).toFloat()
                    g.side = o.optDouble("side", g.side.toDouble()).toFloat()
                    if (o.has("ratio")) {
                        g.ratio = o.optDouble("ratio", g.ratio.toDouble()).toFloat()
                    } else if (o.has("keySize") && g.side > 0f) {
                        // 兼容旧存档：用旧的按键大小反推锁定比例
                        g.ratio = (o.optDouble("keySize", g.keySize.toDouble()).toFloat() / g.side)
                            .coerceIn(0.10f, 0.60f)
                    }
                }
            }

            val slotsArr = root.optJSONArray("slots")
            if (slotsArr != null) {
                for (i in 0 until slotsArr.length()) {
                    val o = slotsArr.optJSONObject(i) ?: continue
                    val s = slotByName(o.optString("name")) ?: continue
                    if (!s.group.isEmpty()) continue
                    s.cx = o.optDouble("cx", s.cx.toDouble()).toFloat()
                    s.cy = o.optDouble("cy", s.cy.toDouble()).toFloat()
                    s.w = o.optDouble("w", s.w.toDouble()).toFloat()
                    s.h = o.optDouble("h", s.h.toDouble()).toFloat()
                    if (s.lockRatio) {
                        // 老存档里宽高可能已经偏离锁定比例，按长边拉回比例
                        setSize(s, max(s.w, s.h))
                    }
                    if (s.canRotate) s.angle = snap(o.optDouble("angle", s.angle.toDouble()).toFloat())
                }
            }
        } catch (e: Exception) {
            // 配置损坏时保持默认值
        }
    }

    fun save(context: Context) {
        val root = JSONObject()

        val groupsArr = JSONArray()
        for (g in groups) {
            val o = JSONObject()
            o.put("name", g.name)
            o.put("cx", g.cx.toDouble())
            o.put("cy", g.cy.toDouble())
            o.put("side", g.side.toDouble())
            o.put("ratio", g.ratio.toDouble())
            groupsArr.put(o)
        }
        root.put("groups", groupsArr)

        val slotsArr = JSONArray()
        for (s in slots) {
            if (!s.group.isEmpty()) continue
            val o = JSONObject()
            o.put("name", s.name)
            o.put("cx", s.cx.toDouble())
            o.put("cy", s.cy.toDouble())
            o.put("w", s.w.toDouble())
            o.put("h", s.h.toDouble())
            if (s.canRotate) o.put("angle", s.angle.toDouble())
            slotsArr.put(o)
        }
        root.put("slots", slotsArr)

        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, root.toString()).apply()
    }
}
