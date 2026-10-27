using System.Text.Json;
using System.Text.Json.Serialization;

namespace BoardCaptureLoop;

public sealed class TileAnnotationDocument
{
    public const string CurrentSchemaVersion = "1";
    [JsonPropertyName("schema_version")] public string SchemaVersion { get; set; } = CurrentSchemaVersion;
    [JsonPropertyName("replay_id")] public string ReplayId { get; set; } = "";
    [JsonPropertyName("player_id")] public int PlayerId { get; set; }
    [JsonPropertyName("view")] public string View { get; set; } = "";
    [JsonPropertyName("size")] public int Size { get; set; }
    [JsonPropertyName("grid_file")] public string GridFile { get; set; } = "";
    [JsonPropertyName("mapping_version")] public string MappingVersion { get; set; } = AnnotationMapping.Version;
    [JsonPropertyName("tiles")] public List<TileAnnotation> Tiles { get; set; } = new();
}

public sealed class TileAnnotation
{
    [JsonPropertyName("x")] public int X { get; set; }
    [JsonPropertyName("y")] public int Y { get; set; }
    [JsonPropertyName("fog")] public bool Fog { get; set; }
    [JsonPropertyName("improvement")] public int Improvement { get; set; }
    [JsonPropertyName("resource")] public int Resource { get; set; }
    [JsonPropertyName("terrain")] public int Terrain { get; set; }
    [JsonPropertyName("road")] public bool Road { get; set; }
    [JsonPropertyName("terrain_tribe_skin")] public int TerrainTribeSkin { get; set; }
    [JsonPropertyName("terrain_appearance")] public AppearanceAnnotation TerrainAppearance { get; set; } = new();
    [JsonPropertyName("main_unit")] public UnitAnnotation MainUnit { get; set; } = new();
    [JsonPropertyName("top_right_unit_icon")] public UnitIconAnnotation TopRightUnitIcon { get; set; } = new();

    public static TileAnnotation Masked(int x, int y) => new() { X = x, Y = y, Fog = true };
}

public sealed class AppearanceAnnotation
{
    [JsonPropertyName("tribe_id")] public int TribeId { get; set; }
    [JsonPropertyName("skin_id")] public int SkinId { get; set; }
}

public sealed class UnitAnnotation
{
    [JsonPropertyName("type")] public int Type { get; set; }
    [JsonPropertyName("tribe_skin")] public int TribeSkin { get; set; }
    [JsonPropertyName("tribe_id")] public int TribeId { get; set; }
    [JsonPropertyName("skin_id")] public int SkinId { get; set; }
    [JsonPropertyName("color_rgb")] public int[] ColorRgb { get; set; } = new[] { 0, 0, 0 };
    [JsonPropertyName("color_name")] public string ColorName { get; set; } = "none";
    [JsonPropertyName("hp")] public int Hp { get; set; }

    /// <summary>Explicit health scale prevents accidentally converting displayed-scale HP twice.</summary>
    public static int DisplayHealth(int value, bool storedInTenths)
    {
        if (value < 0) throw new InvalidDataException($"Negative unit health {value}.");
        return storedInTenths ? value / 10 + (value % 10 == 0 ? 0 : 1) : value;
    }
}

public sealed class UnitIconAnnotation
{
    [JsonPropertyName("type")] public int Type { get; set; }
}

/// <summary>Checks only exported data invariants; native visibility/rendering must be verified by the adapter.</summary>
public static class TileAnnotationValidator
{
    public static TileAnnotationDocument ParseAndValidate(string json, Action<string>? log = null)
    {
        try
        {
            using var parsed = JsonDocument.Parse(json);
            var root = parsed.RootElement;
            Require(root, "document", "schema_version", "replay_id", "player_id", "view", "size", "grid_file", "mapping_version", "tiles");
            string context = $"replay={root.GetProperty("replay_id")} player={root.GetProperty("player_id")} view={root.GetProperty("view")}";
            var tiles = root.GetProperty("tiles");
            if (tiles.ValueKind != JsonValueKind.Array) throw new InvalidDataException($"{context}: tiles must be an array.");
            int index = 0;
            foreach (var tile in tiles.EnumerateArray())
            {
                string where = $"{context} tile[{index++}]";
                Require(tile, where, "x", "y", "fog", "improvement", "resource", "terrain", "road", "terrain_tribe_skin", "terrain_appearance", "main_unit", "top_right_unit_icon");
                Require(tile.GetProperty("terrain_appearance"), where + " terrain_appearance", "tribe_id", "skin_id");
                Require(tile.GetProperty("main_unit"), where + " main_unit", "type", "tribe_skin", "tribe_id", "skin_id", "color_rgb", "color_name", "hp");
                Require(tile.GetProperty("top_right_unit_icon"), where + " top_right_unit_icon", "type");
            }
            var document = JsonSerializer.Deserialize<TileAnnotationDocument>(json) ?? throw new InvalidDataException("Null annotation document.");
            Validate(document, log);
            return document;
        }
        catch (JsonException ex) { throw new InvalidDataException($"Invalid annotation JSON: {ex.Message}", ex); }
    }

    private static void Require(JsonElement value, string context, params string[] fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException($"{context}: expected an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!names.Add(property.Name)) throw new InvalidDataException($"{context}: duplicate field '{property.Name}'.");
        foreach (string name in fields)
            if (!value.TryGetProperty(name, out var field) || field.ValueKind == JsonValueKind.Null)
                throw new InvalidDataException($"{context}: missing required field '{name}'.");
    }

    public static void Validate(TileAnnotationDocument document, Action<string>? log = null)
    {
        if (document == null) throw new InvalidDataException("Null annotation document.");
        string context = $"replay={document.ReplayId} player={document.PlayerId} view={document.View}";
        void Check(bool valid, string message)
        {
            if (!valid) throw new InvalidDataException($"{context}: {message}");
        }
        Check(document.SchemaVersion == TileAnnotationDocument.CurrentSchemaVersion, $"unsupported schema_version '{document.SchemaVersion}'.");
        Check(document.MappingVersion == AnnotationMapping.Version, $"unsupported mapping_version '{document.MappingVersion}'.");
        Check(Guid.TryParseExact(document.ReplayId, "D", out var replayId) && replayId != Guid.Empty, $"invalid replay_id '{document.ReplayId}'.");
        Check(document.PlayerId > 0, $"invalid player_id {document.PlayerId}.");
        Check(document.View is "normal" or "revealed", $"invalid view '{document.View}'.");
        Check(document.Size >= 1 && document.Size <= 100, $"invalid size {document.Size}.");
        Check(document.GridFile == $"player-{document.PlayerId}-{document.View}.grid.json", $"invalid grid_file '{document.GridFile}'.");
        Check(document.Tiles != null && document.Tiles.Count == document.Size * document.Size, "tile count must equal size * size.");
        var mapping = AnnotationMapping.Default;
        int nature = 0;
        for (int i = 0; i < document.Tiles!.Count; i++)
        {
            var tile = document.Tiles[i];
            Check(tile != null, $"tile[{i}] is null.");
            string where = $"tile[{i}] ({tile!.X},{tile.Y})";
            Check(tile.X == i % document.Size && tile.Y == i / document.Size, $"{where}: coordinates must be unique, in-range, row-major.");
            Check(tile.TerrainAppearance != null && tile.MainUnit != null && tile.TopRightUnitIcon != null, $"{where}: appearance, main unit and icon objects are required.");
            var appearance = tile.TerrainAppearance!;
            var unit = tile.MainUnit!;
            var icon = tile.TopRightUnitIcon!;
            Check(mapping.IsDefined("terrain", tile.Terrain), $"{where}: unsupported terrain {tile.Terrain}.");
            Check(mapping.IsDefined("resource", tile.Resource), $"{where}: unsupported resource {tile.Resource}.");
            Check(mapping.IsDefined("improvement", tile.Improvement), $"{where}: unsupported improvement {tile.Improvement}.");
            Check(mapping.IsDefined("unit", unit.Type) && mapping.IsDefined("unit", icon.Type), $"{where}: unsupported main/icon unit {unit.Type}/{icon.Type}.");
            Check(unit.Hp >= 0, $"{where}: negative hp {unit.Hp}.");
            Check(document.View != "revealed" || !tile.Fog, $"{where}: revealed view cannot contain fog.");
            if (tile.Fog)
            {
                Check(tile.Improvement == 0 && tile.Resource == 0 && tile.Terrain == 0 && !tile.Road && tile.TerrainTribeSkin == 0
                    && appearance.TribeId == 0 && appearance.SkinId == 0 && unit.Type == 0 && icon.Type == 0,
                    $"{where}: fog must mask every label and appearance.");
            }
            else
            {
                Check(tile.Improvement == 0 || tile.Resource == 0, $"{where}: improvement {tile.Improvement} must override resource {tile.Resource}.");
                int label;
                try { label = mapping.CompactAppearance(appearance.TribeId, appearance.SkinId); }
                catch (InvalidDataException ex) { throw new InvalidDataException($"{context} {where}: {ex.Message}", ex); }
                Check(tile.TerrainTribeSkin == label, $"{where}: terrain compact label {tile.TerrainTribeSkin} does not match appearance {appearance.TribeId}/{appearance.SkinId} (expected {label}).");
                if (appearance.TribeId == 1) nature++;
            }
            if (unit.Type == 0)
            {
                Check(unit.TribeSkin == 0 && unit.TribeId == 0 && unit.SkinId == 0 && unit.Hp == 0 && unit.ColorName == "none"
                    && unit.ColorRgb != null && unit.ColorRgb.SequenceEqual(new[] { 0, 0, 0 }), $"{where}: absent/invisible unit must have zero attributes and color_name='none'.");
            }
            else
            {
                Check(mapping.IsPlayableTribe(unit.TribeId), $"{where}: visible unit has unsupported playable tribe {unit.TribeId}.");
                int label;
                string color;
                try { label = mapping.CompactAppearance(unit.TribeId, unit.SkinId); color = mapping.ColorName(unit.ColorRgb); }
                catch (InvalidDataException ex) { throw new InvalidDataException($"{context} {where}: {ex.Message}", ex); }
                Check(unit.TribeSkin == label, $"{where}: unit compact label {unit.TribeSkin} does not match appearance {unit.TribeId}/{unit.SkinId} (expected {label}).");
                Check(unit.ColorName == color, $"{where}: RGB [{string.Join(",", unit.ColorRgb)}] requires exact color_name '{color}', got '{unit.ColorName}'.");
            }
        }
        log?.Invoke($"{context}: visible Nature terrain tiles={nature}.");
    }
}
