using System.Text.Json;
using System.Text.Json.Serialization;

namespace BoardCaptureLoop;

public sealed class TribeImageCounts
{
    [JsonPropertyName("skin")]
    public long Skin { get; set; }
    [JsonPropertyName("default")]
    public long Default { get; set; }
}

/// <summary>Statistics are derived data: only validated canonical manifests are authoritative.</summary>
public static class CaptureStatistics
{
    public static IReadOnlyDictionary<string, TribeImageCounts> Rebuild(string root, string output, Action<string>? log = null)
    {
        var counts = new SortedDictionary<string, TribeImageCounts>(StringComparer.Ordinal);
        for (int tribe = 2; tribe <= 17; tribe++) counts.Add(AnnotationMapping.Default.TribeName(tribe), new TribeImageCounts());
        foreach (var manifest in new ReplayOutput(root, log).EnumerateCompleted(log))
        {
            foreach (var participant in manifest.Participants)
            {
                var count = counts[AnnotationMapping.Default.TribeName(participant.TribeId)];
                int images = manifest.Views.Count(view => view.StartsWith($"player-{participant.Id}-", StringComparison.Ordinal));
                if (participant.TribeSkin > 16) count.Skin = checked(count.Skin + images);
                else count.Default = checked(count.Default + images);
            }
        }
        string path = Path.GetFullPath(output), parent = Path.GetDirectoryName(path)!;
        // Never replace a source capture artifact with derived statistics.
        string captureRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string relative = Path.GetRelativePath(captureRoot, path);
        if (!Path.IsPathRooted(relative) && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
            relative != ".." && relative.IndexOfAny(new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }) >= 0)
            throw new ArgumentException("Statistics must not be placed inside a replay directory.", nameof(output));
        Directory.CreateDirectory(parent);
        string temporary = Path.Combine(parent, ".statistics-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(counts, new JsonSerializerOptions { WriteIndented = true });
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            if (File.Exists(path))
            {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked statistics files are not supported.");
                File.Replace(temporary, path, null);
            }
            else File.Move(temporary, path);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
        return counts;
    }
}
