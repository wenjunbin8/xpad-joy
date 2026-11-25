package com.xpad.joy

import android.media.Image
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer

/**
 * 回退解码器（"原相机"那条）：只有 Google Play 服务请求失败时才用。
 *
 * 只吃 YUV_420_888 的 Y（亮度）平面，不做色彩转换：zxing 只需要亮度。
 * 全在本机 CPU，一帧大约 10–80ms（TRY_HARDER 开着的代价），所以调用方要把帧率限住。
 * 解不出就是 null（zxing 每帧都会抛 NotFoundException，不当成错误）。
 */
object QrScanner {

    private val reader = MultiFormatReader()
    private val hints: Map<DecodeHintType, Any> = mapOf(
        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
        // TRY_HARDER：多试几种策略。慢一点，但手机斜着拍、屏幕反光时更容易成功
        DecodeHintType.TRY_HARDER to true,
    )

    private var luma = ByteArray(0)
    private var packed = IntArray(0)
    private var rotated = IntArray(0)

    /** image 由调用方负责 close（这条是同步的，解完就关） */
    fun decode(image: Image, rotationDegrees: Int): String? {
        try {
            val width = image.width
            val height = image.height
            val plane = image.planes[0]
            val buffer = plane.buffer
            val rowStride = plane.rowStride
            val colStride = plane.pixelStride
            val limit = buffer.limit()
            if (luma.size != width * height) luma = ByteArray(width * height)

            for (y in 0 until height) {
                val rowBase = y * rowStride
                if (rowBase >= limit) break
                for (x in 0 until width) {
                    val i = rowBase + x * colStride
                    if (i >= limit) break
                    luma[y * width + x] = buffer.get(i)
                }
            }

            for (i in luma.indices) {
                val v = luma[i].toInt() and 0xFF
                packed[i] = (0xFF shl 24) or (v shl 16) or (v shl 8) or v
            }

            val deg = ((rotationDegrees % 360) + 360) % 360
            var sourceWidth = width
            var sourceHeight = height
            var pixels = packed
            if (deg != 0) {
                if (rotated.size != luma.size) rotated = IntArray(luma.size)
                val outWidth = if (deg == 180) width else height
                val outHeight = if (deg == 180) height else width
                for (y in 0 until height) {
                    for (x in 0 until width) {
                        val dx: Int
                        val dy: Int
                        when (deg) {
                            90 -> { dx = height - 1 - y; dy = x }
                            180 -> { dx = width - 1 - x; dy = height - 1 - y }
                            else -> { dx = y; dy = width - 1 - x }   // 270
                        }
                        rotated[dy * outWidth + dx] = packed[y * width + x]
                    }
                }
                sourceWidth = outWidth
                sourceHeight = outHeight
                pixels = rotated
            }

            val source = RGBLuminanceSource(sourceWidth, sourceHeight, pixels)
            val bitmap = BinaryBitmap(HybridBinarizer(source))
            return reader.decode(bitmap, hints)?.text
        } catch (t: Throwable) {
            // NotFoundException / FormatException / ChecksumException 都走这里：这帧没扫到
            return null
        }
    }

    fun reset() {
        reader.reset()
    }
}
