using System.Text.Json;
using Polytopia.Data;
using UnityEngine;

namespace BoardCaptureLoop;

internal static class Capture
{
    internal static void Save(string prefix, int size)
    {
        if (size < 1 || size > 100) throw new ArgumentOutOfRangeException(nameof(size), "Supported square maps have 1–100 tiles per side.");
        int width = Screen.width, height = Screen.height;
        if (width <= 0 || height <= 0) throw new InvalidOperationException("No render area available.");
        var camera = CameraController.Camera;
        var position = camera.transform.position;
        bool orthographic = camera.orthographic;
        float scale = camera.orthographicSize, aspect = camera.aspect;
        float near = camera.nearClipPlane, far = camera.farClipPlane;
        var target = camera.targetTexture;
        var active = RenderTexture.active;
        RenderTexture? buffer = null;
        Texture2D? image = null;
        try
        {
            camera.targetTexture = null;
            camera.orthographic = true;
            camera.aspect = (float)width / height;

            Vector3 origin = new WorldCoordinates(0, 0).ToPosition();
            Vector3 alongX = (Vector3)new WorldCoordinates(1, 0).ToPosition() - origin;
            Vector3 alongY = (Vector3)new WorldCoordinates(0, 1).ToPosition() - origin;
            Vector3 right = camera.transform.right, up = camera.transform.up, forward = camera.transform.forward;
            Vector3 midpoint = origin + (alongX + alongY) * ((size - 1) / 2f);
            Vector3 displacement = midpoint - position;
            camera.transform.position += right * Vector3.Dot(displacement, right) + up * Vector3.Dot(displacement, up);
            float extent = (size - 1) / 2f + 5f;
            float horizontal = extent * (Mathf.Abs(Vector3.Dot(alongX, right)) + Mathf.Abs(Vector3.Dot(alongY, right)));
            float vertical = extent * (Mathf.Abs(Vector3.Dot(alongX, up)) + Mathf.Abs(Vector3.Dot(alongY, up)));
            camera.orthographicSize = Mathf.Max(vertical, horizontal / camera.aspect) * 1.05f;
            float depth = Vector3.Dot(midpoint - camera.transform.position, forward);
            float radius = extent * (Mathf.Abs(Vector3.Dot(alongX, forward)) + Mathf.Abs(Vector3.Dot(alongY, forward)));
            camera.nearClipPlane = Mathf.Max(0.01f, depth - radius - 50f);
            camera.farClipPlane = Mathf.Max(far, depth + radius + 50f);

            foreach (float x in new[] { -extent, extent })
                foreach (float y in new[] { -extent, extent })
                {
                    var point = camera.WorldToViewportPoint(midpoint + x * alongX + y * alongY);
                    if (point.z <= 0 || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1)
                        throw new InvalidOperationException("Projected board exceeds capture bounds.");
                }

            int tilePixels = CaptureResolution.ParseTarget(Environment.GetEnvironmentVariable("BOARDCAPTURELOOP_TILE_PIXELS"));
            Vector3 p = default, px = default, py = default;
            bool sized = false;
            for (int iteration = 0; iteration < 8; iteration++)
            {
                p = camera.WorldToViewportPoint(origin);
                px = camera.WorldToViewportPoint(origin + alongX);
                py = camera.WorldToViewportPoint(origin + alongY);
                (width, height) = CaptureResolution.Calculate(width, height,
                    (double)px.x - p.x, (double)px.y - p.y,
                    (double)py.x - p.x, (double)py.y - p.y, tilePixels, SystemInfo.maxTextureSize);
                camera.aspect = (float)width / height;
                camera.orthographicSize = Mathf.Max(vertical, horizontal / camera.aspect) * 1.05f;
                p = camera.WorldToViewportPoint(origin);
                px = camera.WorldToViewportPoint(origin + alongX);
                py = camera.WorldToViewportPoint(origin + alongY);
                double edgeX = Math.Sqrt(Math.Pow(((double)px.x - p.x) * width, 2) + Math.Pow(((double)px.y - p.y) * height, 2));
                double edgeY = Math.Sqrt(Math.Pow(((double)py.x - p.x) * width, 2) + Math.Pow(((double)py.y - p.y) * height, 2));
                if (Math.Min(edgeX, edgeY) >= tilePixels) { sized = true; break; }
            }
            if (!sized) throw new InvalidOperationException("Could not achieve the requested tile pixel size with a stable camera projection.");
            foreach (float x in new[] { -extent, extent })
                foreach (float y in new[] { -extent, extent })
                {
                    var point = camera.WorldToViewportPoint(midpoint + x * alongX + y * alongY);
                    if (point.z <= 0 || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1)
                        throw new InvalidOperationException("Projected board exceeds final capture bounds.");
                }
            buffer = new RenderTexture(width, height, 24);
            if (!buffer.Create()) throw new InvalidOperationException($"Could not allocate the {width}x{height} capture render target. Lower BOARDCAPTURELOOP_TILE_PIXELS.");
            image = new Texture2D(width, height, TextureFormat.RGB24, false);
            camera.targetTexture = buffer;
            var vx = new[] { ((double)px.x - p.x) * width, ((double)p.y - px.y) * height };
            var vy = new[] { ((double)py.x - p.x) * width, ((double)p.y - py.y) * height };
            double ax = (double)p.x * width, ay = (1d - p.y) * height + (vx[1] + vy[1]) / 8d;

            camera.Render();
            RenderTexture.active = buffer;
            image.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            File.WriteAllBytes(prefix + ".png", image.EncodeToPNG());
            var grid = new
            {
                size, width, height, targetTilePixels = tilePixels, anchor = new[] { ax, ay }, stepX = vx, stepY = vy,
                sideLengthPixels = Math.Sqrt(vx[0] * vx[0] + vx[1] * vx[1]),
                otherSideLengthPixels = Math.Sqrt(vy[0] * vy[0] + vy[1] * vy[1])
            };
            File.WriteAllText(prefix + ".grid.json", JsonSerializer.Serialize(grid, new JsonSerializerOptions { WriteIndented = true }));
            var pixels = image.GetPixels32();
            for (int i = 0; i <= size; i++)
            {
                double edge = i - 0.5;
                Draw(ax + edge * vx[0] - 0.5 * vy[0], ay + edge * vx[1] - 0.5 * vy[1],
                    ax + edge * vx[0] + (size - 0.5) * vy[0], ay + edge * vx[1] + (size - 0.5) * vy[1]);
                Draw(ax - 0.5 * vx[0] + edge * vy[0], ay - 0.5 * vx[1] + edge * vy[1],
                    ax + (size - 0.5) * vx[0] + edge * vy[0], ay + (size - 0.5) * vx[1] + edge * vy[1]);
            }
            image.SetPixels32(pixels);
            image.Apply();
            File.WriteAllBytes(prefix + ".grid.png", image.EncodeToPNG());

            void Draw(double x0, double y0, double x1, double y1)
            {
                double dx = x1 - x0, dy = y1 - y0, lo = 0, hi = 1;
                foreach ((double a, double b) in new[]
                {
                    (-dx, x0), (dx, width - 1 - x0), (-dy, y0), (dy, height - 1 - y0)
                })
                {
                    if (a == 0) { if (b < 0) return; }
                    else if (a < 0) lo = Math.Max(lo, b / a);
                    else hi = Math.Min(hi, b / a);
                }
                if (lo > hi) return;
                int left = Math.Clamp((int)Math.Round(x0 + lo * dx), 0, width - 1);
                int top = Math.Clamp((int)Math.Round(y0 + lo * dy), 0, height - 1);
                int endX = Math.Clamp((int)Math.Round(x0 + hi * dx), 0, width - 1);
                int endY = Math.Clamp((int)Math.Round(y0 + hi * dy), 0, height - 1);
                int count = Math.Max(Math.Abs(endX - left), Math.Abs(endY - top));
                for (int j = 0; j <= count; j++)
                {
                    int x = left + (int)Math.Round((double)(endX - left) * j / Math.Max(1, count));
                    int y = top + (int)Math.Round((double)(endY - top) * j / Math.Max(1, count));
                    pixels[(height - 1 - y) * width + x] = new Color32(255, 0, 0, 255);
                }
            }
        }
        finally
        {
            camera.targetTexture = target;
            camera.orthographic = orthographic;
            camera.orthographicSize = scale;
            camera.aspect = aspect;
            camera.nearClipPlane = near;
            camera.farClipPlane = far;
            camera.transform.position = position;
            RenderTexture.active = active;
            if (buffer != null) UnityEngine.Object.Destroy(buffer);
            if (image != null) UnityEngine.Object.Destroy(image);
        }
    }
}
