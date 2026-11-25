package com.xpad.joy

import android.app.Activity
import android.os.Build
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager

/**
 * 沉浸全屏：状态栏/导航栏隐藏，并且不使用刘海（挖孔）预留区，
 * 所以手柄屏和布局页用整块屏幕面积，左侧不会空出一条。
 */
object Immersive {

    // Kotlin 读不到接口上的静态字段，这里用 WindowInsetsController 同名常量的值
    private const val BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE = 2

    // LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS = 3（API 30 起）；API 28/29 用 SHORT_EDGES = 1
    private const val CUTOUT_ALWAYS = 3
    private const val CUTOUT_SHORT_EDGES = 1

    fun apply(activity: Activity) {
        val cutoutMode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) CUTOUT_ALWAYS else CUTOUT_SHORT_EDGES
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            activity.window.attributes.layoutInDisplayCutoutMode = cutoutMode
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            @Suppress("DEPRECATION")
            activity.window.setDecorFitsSystemWindows(false)
            val controller = activity.window.insetsController
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.setSystemBarsBehavior(BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE)
            }
        } else {
            @Suppress("DEPRECATION")
            activity.window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        }
    }

    /** 失去焦点后系统会重新显示栏，重新隐藏一次 */
    fun reapply(activity: Activity, hasFocus: Boolean) {
        if (hasFocus) apply(activity)
    }
}
