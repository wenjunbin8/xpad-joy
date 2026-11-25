package com.xpad.joy

import android.content.Context
import android.util.Log

/**
 * 崩溃原因只在 logcat 里能看到，手机没连 adb 时看不到。
 * 所以把最近一次未捕获异常存进 prefs（xpadjoy / crash_last），
 * 第一屏的状态行会显示它：崩溃过一次之后回到第一屏就能看到是哪一行。
 */
object CrashLog {

    private const val TAG = "XjoyCrash"
    private const val KEY = "crash_last"

    fun install(context: Context) {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, t ->
            record(context, t)
            previous?.uncaughtException(thread, t)
        }
    }

    fun record(context: Context, t: Throwable) {
        val text = format(t)
        Log.e(TAG, text, t)
        try {
            context.getSharedPreferences("xpadjoy", Context.MODE_PRIVATE).edit().putString(KEY, text).apply()
        } catch (ignored: Exception) {
            // 存不了就算了，logcat 里还是有
        }
    }

    fun last(context: Context): String =
        context.getSharedPreferences("xpadjoy", Context.MODE_PRIVATE).getString(KEY, "") ?: ""

    fun clear(context: Context) {
        context.getSharedPreferences("xpadjoy", Context.MODE_PRIVATE).edit().remove(KEY).apply()
    }

    private fun format(t: Throwable): String {
        val sb = StringBuilder()
        sb.append(t.javaClass.simpleName)
        if (t.message != null) sb.append(": ").append(t.message)
        val cause = t.cause
        if (cause != null) {
            sb.append(" ← ").append(cause.javaClass.simpleName)
            if (cause.message != null) sb.append(": ").append(cause.message)
        }
        val frames = t.stackTrace
        if (frames.isNotEmpty()) {
            val mine = frames.firstOrNull { it.className.startsWith("com.xpad.joy") } ?: frames[0]
            sb.append(" @ ").append(mine.className.substringAfterLast('.'))
                .append('.').append(mine.methodName).append(':').append(mine.lineNumber)
        }
        return sb.toString()
    }
}
