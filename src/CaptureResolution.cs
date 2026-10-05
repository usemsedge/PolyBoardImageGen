using System.Globalization;

namespace BoardCaptureLoop;

internal static class CaptureResolution
{
    internal const int DefaultTilePixels = 128;
    internal const long MaxPixels = 16_000_000;
    internal const int MaxDimension = 16384;

    internal static int ParseTarget(string? value)
    {
        if (value == null) return DefaultTilePixels;
        if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out int target) || target < 32 || target > 512)
            throw new ArgumentException("BOARDCAPTURELOOP_TILE_PIXELS must be an integer from 32 to 512 (default 128).");
        return target;
    }

    internal static (int Width, int Height) Calculate(int width, int height,
        double stepXx, double stepXy, double stepYx, double stepYy, int target, int textureLimit)
    {
        if (width <= 0 || height <= 0 || target < 32 || target > 512 || textureLimit <= 0)
            throw new ArgumentOutOfRangeException(nameof(target), "Capture dimensions, target, and GPU texture limit must be valid.");
        if (!double.IsFinite(stepXx) || !double.IsFinite(stepXy) || !double.IsFinite(stepYx) || !double.IsFinite(stepYy))
            throw new ArgumentException("Tile projection must contain finite coordinates.");
        double determinant = stepXx * stepYy - stepXy * stepYx;
        double xLength = Math.Sqrt(Math.Pow(stepXx * width, 2) + Math.Pow(stepXy * height, 2));
        double yLength = Math.Sqrt(Math.Pow(stepYx * width, 2) + Math.Pow(stepYy * height, 2));
        double shortest = Math.Min(xLength, yLength);
        if (!double.IsFinite(shortest) || shortest <= 0 || !double.IsFinite(determinant) || determinant == 0)
            throw new ArgumentException("Tile projection must form a nondegenerate grid.");
        // Leave a tiny margin for Unity's float-valued reprojection after aspect rounding.
        double factor = (target + 0.01) / shortest;
        double outputWidth = Math.Ceiling(width * factor), outputHeight = Math.Ceiling(height * factor);
        int limit = Math.Min(textureLimit, MaxDimension);
        if (!double.IsFinite(outputWidth) || !double.IsFinite(outputHeight) || outputWidth > limit || outputHeight > limit ||
            outputWidth < 1 || outputHeight < 1 || outputWidth * outputHeight > MaxPixels)
            throw new InvalidOperationException($"A {target}-pixel tile target exceeds the GPU/image limits ({limit} pixels per dimension, {MaxPixels:N0} pixels total). Lower BOARDCAPTURELOOP_TILE_PIXELS.");
        return ((int)outputWidth, (int)outputHeight);
    }
}
