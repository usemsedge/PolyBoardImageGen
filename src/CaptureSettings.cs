using System.Text.Json;
using System.Text.Json.Serialization;

namespace BoardCaptureLoop;

/// <summary>Run settings; a snapshot is recorded with each replay and used during recovery.</summary>
public sealed class CaptureSettings
{
    [JsonPropertyName("show_grid_overlay")]
    public bool ShowGridOverlay { get; set; }
    [JsonPropertyName("num_iterations")]
    public int NumIterations { get; set; } = 1;
    [JsonPropertyName("csv_filename")]
    public string CsvFilename { get; set; } = "replays.csv";
    [JsonPropertyName("target_tile_pixels")]
    public int TargetTilePixels { get; set; } = 128;
    [JsonPropertyName("input_mode")]
    public string InputMode { get; set; } = "links";
    [JsonPropertyName("gamestates_directory")]
    public string GamestatesDirectory { get; set; } = "gamestates";

    public static CaptureSettings Load(string path)
    {
        string fullPath = Path.GetFullPath(path);
        using var document = StrictJson.ReadFile(fullPath, 1024 * 1024);
        var settings = FromJson(document.RootElement);
        settings.CsvFilename = Path.GetFullPath(settings.CsvFilename, Path.GetDirectoryName(fullPath)!);
        settings.GamestatesDirectory = Path.GetFullPath(settings.GamestatesDirectory, Path.GetDirectoryName(fullPath)!);
        return settings;
    }

    internal static CaptureSettings FromJson(JsonElement json)
    {
        StrictJson.Properties(json, new[] { "show_grid_overlay", "num_iterations", "csv_filename" }, new[] { "target_tile_pixels", "input_mode", "gamestates_directory" });
        var overlay = json.GetProperty("show_grid_overlay");
        if (overlay.ValueKind != JsonValueKind.True && overlay.ValueKind != JsonValueKind.False)
            throw new InvalidDataException("show_grid_overlay must be a boolean.");
        var settings = new CaptureSettings
        {
            ShowGridOverlay = overlay.GetBoolean(),
            NumIterations = StrictJson.Int(json, "num_iterations"),
            CsvFilename = StrictJson.String(json, "csv_filename"),
            TargetTilePixels = json.TryGetProperty("target_tile_pixels", out _) ? StrictJson.Int(json, "target_tile_pixels") : 128,
            InputMode = json.TryGetProperty("input_mode", out _) ? StrictJson.String(json, "input_mode") : "links",
            GamestatesDirectory = json.TryGetProperty("gamestates_directory", out _) ? StrictJson.String(json, "gamestates_directory") : "gamestates"
        };
        settings.Validate();
        return settings;
    }

    internal void Validate()
    {
        if (InputMode != "links" && InputMode != "gamestates")
            throw new InvalidDataException("input_mode must be links or gamestates.");
        if (string.IsNullOrWhiteSpace(GamestatesDirectory) || GamestatesDirectory.IndexOf('\0') >= 0)
            throw new InvalidDataException("gamestates_directory must be a nonempty path.");
        if (NumIterations <= 0) throw new InvalidDataException("num_iterations must be a positive integer.");
        if (string.IsNullOrWhiteSpace(CsvFilename) || CsvFilename.IndexOf('\0') >= 0)
            throw new InvalidDataException("csv_filename must be a nonempty path.");
        if (TargetTilePixels < 32 || TargetTilePixels > 512)
            throw new InvalidDataException("target_tile_pixels must be an integer from 32 through 512.");
    }

    internal CaptureSettings Snapshot()
    {
        Validate();
        return new CaptureSettings { ShowGridOverlay = ShowGridOverlay, NumIterations = NumIterations,
            CsvFilename = CsvFilename, TargetTilePixels = TargetTilePixels,
            InputMode = InputMode, GamestatesDirectory = GamestatesDirectory };
    }
}

internal static class StrictJson
{
    internal static JsonDocument ReadFile(string path, long maxLength)
    {
        var info = new FileInfo(path);
        if (!info.Exists) throw new FileNotFoundException("Required JSON file was not found.", path);
        if ((info.Attributes & FileAttributes.ReparsePoint) != 0 || info.Length < 1 || info.Length > maxLength)
            throw new InvalidDataException("Invalid or oversized JSON file: " + path);
        var document = JsonDocument.Parse(File.ReadAllBytes(path));
        try { UniqueProperties(document.RootElement); return document; }
        catch { document.Dispose(); throw; }
    }

    internal static void UniqueProperties(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            {
                if (!names.Add(property.Name)) throw new InvalidDataException("Duplicate JSON property: " + property.Name);
                UniqueProperties(property.Value);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array)
            foreach (var item in value.EnumerateArray()) UniqueProperties(item);
    }

    internal static void Properties(JsonElement value, string[] required, string[]? optional = null)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Expected a JSON object.");
        var names = new HashSet<string>(required.Concat(optional ?? Array.Empty<string>()), StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!names.Remove(property.Name)) throw new InvalidDataException("Unknown or duplicate JSON property: " + property.Name);
        foreach (string name in required)
            if (names.Contains(name)) throw new InvalidDataException("Missing JSON property: " + name);
    }

    internal static int Int(JsonElement value, string name)
    {
        if (!value.TryGetProperty(name, out var number) || number.ValueKind != JsonValueKind.Number || !number.TryGetInt32(out int result))
            throw new InvalidDataException(name + " must be an integer.");
        return result;
    }
    internal static string String(JsonElement value, string name)
    {
        if (!value.TryGetProperty(name, out var text) || text.ValueKind != JsonValueKind.String)
            throw new InvalidDataException(name + " must be a string.");
        return text.GetString()!;
    }
}
