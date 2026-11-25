package com.xpad.joy

import android.app.Activity
import android.graphics.drawable.Drawable
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.SeekBar
import android.widget.TextView
import kotlin.math.roundToInt

/**
 * 布局页：画布就是手柄屏的实际区域（含刘海区域）。
 * 单个槽 → 拖动移位 + 改宽/高；正方形框（ABXY）→ 拖动移动整组 + 改边长（按键大小按锁定比例一起变）。
 * 弹窗默认收起：屏幕上只有一个「展开」按钮（没有框）；展开后固定宽 320dp。
 *
 * 角度（只有 LT/RT）：滑条只做粗调（1 格 = 5°，滑条全长 360° 太密，手指动一点就跳十几度），
 * 精确落定用 0°/90°/180°/270° 四个按钮，微调用 -5/-1/+1/+5 按钮。
 *
 * 进页面和点按键都不应该闪退：出错就记到 CrashLog（第一屏状态行会显示）+ logcat -s XjoyCrash。
 */
class LayoutActivity : Activity() {

    private lateinit var editor: EditorView
    private lateinit var panelRoot: View
    private lateinit var panelBody: View
    private lateinit var rowH: View
    private lateinit var nameText: TextView
    private lateinit var labelW: TextView
    private lateinit var labelH: TextView
    private lateinit var barW: SeekBar
    private lateinit var barH: SeekBar
    private lateinit var toggleButton: Button

    private lateinit var rowAngle: View
    private lateinit var rowCardinal: View
    private lateinit var rowFine: View
    private lateinit var barAngle: SeekBar
    private lateinit var labelAngle: TextView

    private var panelBackground: Drawable? = null
    private var updatingBars = false

    private val cardinals = listOf(
        R.id.btn_a0 to 0f,
        R.id.btn_a90 to 90f,
        R.id.btn_a180 to 180f,
        R.id.btn_a270 to 270f,
    )

    private val fineSteps = listOf(
        R.id.btn_fine_m5 to -5f,
        R.id.btn_fine_m1 to -1f,
        R.id.btn_fine_p1 to 1f,
        R.id.btn_fine_p5 to 5f,
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashLog.install(this)
        try {
            build()
        } catch (t: Throwable) {
            CrashLog.record(this, t)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        Immersive.reapply(this, hasFocus)
    }

    private fun build() {
        setContentView(R.layout.activity_editor)
        panelRoot = findViewById(R.id.editor_panel)
        // 未展开时只留「展开」按钮，不要框；展开时才有弹窗底
        panelBackground = panelRoot.background
        panelRoot.background = null

        editor = findViewById(R.id.editor) as EditorView
        panelRoot = findViewById(R.id.editor_panel)
        panelBody = findViewById(R.id.panel_body)
        rowH = findViewById(R.id.row_h)
        nameText = findViewById(R.id.sel_name) as TextView
        labelW = findViewById(R.id.label_w) as TextView
        labelH = findViewById(R.id.label_h) as TextView
        barW = findViewById(R.id.bar_w) as SeekBar
        barH = findViewById(R.id.bar_h) as SeekBar
        toggleButton = findViewById(R.id.btn_toggle) as Button

        rowAngle = findViewById(R.id.row_angle)
        rowCardinal = findViewById(R.id.row_cardinal)
        rowFine = findViewById(R.id.row_fine)
        barAngle = findViewById(R.id.bar_angle) as SeekBar
        labelAngle = findViewById(R.id.label_angle) as TextView

        editor.onSelection = { safe { refreshPanel() } }

        barW.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, progress: Int, fromUser: Boolean) {
                if (!fromUser || updatingBars) return
                safe {
                    val g = editor.selectedGroup()
                    val s = editor.selectedSlot()
                    val base = if (s != null && s.lockRatio) LayoutConfig.minLongSide(s) else LayoutConfig.MIN_SIZE.toFloat()
                    val value = progress + base
                    if (g != null) {
                        LayoutConfig.setSide(g, value)
                    } else if (s != null) {
                        LayoutConfig.setSize(s, value)
                    }
                    syncBars()
                    editor.invalidate()
                }
            }

            override fun onStartTrackingTouch(bar: SeekBar) {}
            override fun onStopTrackingTouch(bar: SeekBar) {}
        })

        barH.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, progress: Int, fromUser: Boolean) {
                if (!fromUser || updatingBars) return
                safe {
                    val s = editor.selectedSlot()
                    if (s != null && !s.circle && !s.lockRatio) {
                        s.h = (progress + LayoutConfig.MIN_SIZE).toFloat()
                        syncBars()
                        editor.invalidate()
                    }
                }
            }

            override fun onStartTrackingTouch(bar: SeekBar) {}
            override fun onStopTrackingTouch(bar: SeekBar) {}
        })

        barAngle.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, progress: Int, fromUser: Boolean) {
                if (!fromUser || updatingBars) return
                safe {
                    val s = editor.selectedSlot()
                    if (s != null && s.canRotate) {
                        // 1 格 = 5°；离 90° 整倍数在 5° 以内就落定
                        val raw = progress * 5f
                        val snapped = LayoutConfig.snap(raw)
                        s.angle = snapped
                        if (snapped != raw) {
                            updatingBars = true
                            bar.progress = (snapped / 5f).roundToInt()
                            updatingBars = false
                        }
                        labelAngle.text = angleLabel(s.angle)
                        editor.invalidate()
                    }
                }
            }

            override fun onStartTrackingTouch(bar: SeekBar) {}
            override fun onStopTrackingTouch(bar: SeekBar) {}
        })

        for ((id, value) in cardinals) {
            findViewById<Button>(id)?.setOnClickListener { setAngle(value) }
        }
        for ((id, delta) in fineSteps) {
            findViewById<Button>(id)?.setOnClickListener {
                val s = editor.selectedSlot()
                if (s != null && s.canRotate) setAngle(((s.angle + delta) % 360f + 360f) % 360f)
            }
        }

        toggleButton.setOnClickListener {
            if (panelBody.visibility == View.VISIBLE) {
                panelBody.visibility = View.GONE
                nameText.visibility = View.GONE
                panelRoot.background = null
                toggleButton.text = "展开"
            } else {
                panelBody.visibility = View.VISIBLE
                nameText.visibility = View.VISIBLE
                panelRoot.background = panelBackground
                toggleButton.text = "收起"
            }
        }

        findViewById<Button>(R.id.btn_save)?.setOnClickListener {
            safe {
                LayoutConfig.save(this)
                nameText.text = "已保存"
            }
        }
        findViewById<Button>(R.id.btn_reset)?.setOnClickListener {
            safe {
                LayoutConfig.resetDefaults()
                LayoutConfig.save(this)
                editor.selectedGroupName = null
                editor.selectedSlotName = null
                refreshPanel()
                editor.invalidate()
            }
        }
        findViewById<Button>(R.id.btn_exit)?.setOnClickListener { finish() }

        val initial = LayoutConfig.groupByName("ABXY")
        if (initial != null) {
            editor.selectedGroupName = initial.name
            refreshPanel()
        }
        editor.invalidate()

        Immersive.apply(this)
    }

    /** 点一下不该闪退：出错就记进 logcat（-s XjoyCrash）+ 第一屏状态行 */
    private fun safe(block: () -> Unit) {
        try {
            block()
        } catch (t: Throwable) {
            CrashLog.record(this, t)
        }
    }

    private fun setAngle(value: Float) {
        val s = editor.selectedSlot()
        if (s == null || !s.canRotate) return
        s.angle = value
        safe {
            syncBars()
            editor.invalidate()
        }
    }

    private fun refreshPanel() {
        safe {
            val g = editor.selectedGroup()
            val s = editor.selectedSlot()
            if (g != null) {
                nameText.text = "${g.name}（正方形框）"
                labelW.text = "边长"
                rowH.visibility = View.GONE
                rowAngle.visibility = View.GONE
                rowCardinal.visibility = View.GONE
                rowFine.visibility = View.GONE
                barW.max = LayoutConfig.MAX_SIDE - LayoutConfig.MIN_SIZE
                syncBars()
            } else if (s != null) {
                nameText.text = s.name
                labelW.text = if (s.lockRatio) "大小" else "宽"
                labelH.text = "高"
                rowH.visibility = if (s.lockRatio) View.GONE else View.VISIBLE
                barW.max = if (s.lockRatio) (LayoutConfig.MAX_SIZE - LayoutConfig.minLongSide(s)).roundToInt() else LayoutConfig.MAX_SIZE - LayoutConfig.MIN_SIZE
                barH.max = LayoutConfig.MAX_SIZE - LayoutConfig.MIN_SIZE
                barH.isEnabled = !s.circle && !s.lockRatio
                rowAngle.visibility = if (s.canRotate) View.VISIBLE else View.GONE
                rowCardinal.visibility = if (s.canRotate) View.VISIBLE else View.GONE
                rowFine.visibility = if (s.canRotate) View.VISIBLE else View.GONE
                barAngle.max = LayoutConfig.MAX_ANGLE / 5
                syncBars()
            } else {
                nameText.text = "未选择"
                rowAngle.visibility = View.GONE
                rowCardinal.visibility = View.GONE
                rowFine.visibility = View.GONE
            }
        }
    }

    private fun syncBars() {
        safe {
            val g = editor.selectedGroup()
            val s = editor.selectedSlot()
            updatingBars = true
            if (g != null) {
                barW.progress = (g.side - LayoutConfig.MIN_SIZE).toInt().coerceIn(0, barW.max)
                labelH.text = "按键 ${g.keySize.toInt()}dp"
            } else if (s != null) {
                barW.progress = (LayoutConfig.longSide(s) - (if (s.lockRatio) LayoutConfig.minLongSide(s) else LayoutConfig.MIN_SIZE.toFloat())).roundToInt().coerceIn(0, barW.max)
                if (s.lockRatio) {
                    labelH.text = "比例 ${(s.ratio * 100f).roundToInt()}%"
                } else {
                    barH.progress = (s.h - LayoutConfig.MIN_SIZE).toInt().coerceIn(0, barH.max)
                }
                if (s.canRotate) {
                    barAngle.progress = ((s.angle / 5f).roundToInt().coerceIn(0, barAngle.max))
                    labelAngle.text = angleLabel(s.angle)
                }
            }
            updatingBars = false
        }
    }

    private fun angleLabel(angle: Float): String {
        val snapped = angle % 90f == 0f
        return "${angle.toInt()}°${if (snapped) "（吸附）" else ""}"
    }
}
