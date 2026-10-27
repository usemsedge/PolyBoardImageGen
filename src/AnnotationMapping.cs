using System.Text.Json;

namespace BoardCaptureLoop;

/// <summary>Pure, pinned renderer mappings; native enum numeric values are never assumed.</summary>
public sealed class AnnotationMapping
{
    public const string Version = "54457a8bdef9baa863ebc0926eb8c31ea0d06c41-palette28-v1";
    public const string ResourceName = "BoardCaptureLoop.annotation-mapping.json";
    public static AnnotationMapping Default { get; } = LoadEmbedded();
    private readonly Dictionary<string, Dictionary<string, int>> enums = new(StringComparer.Ordinal);
    private readonly Dictionary<string, HashSet<int>> values = new(StringComparer.Ordinal);
    private readonly Dictionary<int, int> premiumSkins = new();
    private readonly Dictionary<int, string> tribeNames = new();
    private readonly Dictionary<int, string> colors = new();
    private readonly Dictionary<int, int> tribeColors = new();
    private readonly Dictionary<int, int> skinColors = new();
    private readonly int[] legacyTribes;

    public AnnotationMapping(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.GetProperty("version").GetString() != Version)
            throw new InvalidDataException("Unsupported annotation mapping version.");
        foreach (var category in root.GetProperty("enums").EnumerateObject())
        {
            var table = new Dictionary<string, int>(StringComparer.Ordinal);
            var ids = new HashSet<int>();
            foreach (var entry in category.Value.EnumerateObject())
            {
                table.Add(Normalize(entry.Name), entry.Value.GetInt32());
                ids.Add(entry.Value.GetInt32());
                if (category.Name == "tribe") tribeNames.Add(entry.Value.GetInt32(), entry.Name.ToLowerInvariant());
            }
            enums.Add(category.Name, table);
            values.Add(category.Name, ids);
        }
        foreach (var category in root.GetProperty("aliases").EnumerateObject())
            foreach (var alias in category.Value.EnumerateObject())
                enums[category.Name].Add(Normalize(alias.Name), Map(category.Name, alias.Value.GetString()!));
        foreach (var entry in root.GetProperty("tribe_skin").EnumerateObject())
            premiumSkins.Add(int.Parse(entry.Name, System.Globalization.CultureInfo.InvariantCulture), entry.Value.GetInt32());
        foreach (var entry in root.GetProperty("tribe_colors").EnumerateObject())
            tribeColors.Add(int.Parse(entry.Name, System.Globalization.CultureInfo.InvariantCulture), entry.Value.GetInt32());
        foreach (var entry in root.GetProperty("skin_colors").EnumerateObject())
            skinColors.Add(int.Parse(entry.Name, System.Globalization.CultureInfo.InvariantCulture), entry.Value.GetInt32());
        foreach (var entry in root.GetProperty("readable_colors").EnumerateArray())
            colors.Add(Pack(entry.GetProperty("rgb").EnumerateArray().Select(x => x.GetInt32()).ToArray()), entry.GetProperty("name").GetString()!);
        legacyTribes = root.GetProperty("legacy_tribe_order").EnumerateArray().Select(x => x.GetInt32()).ToArray();
    }

    private static AnnotationMapping LoadEmbedded()
    {
        using var stream = typeof(AnnotationMapping).Assembly.GetManifestResourceStream(ResourceName)
            ?? throw new InvalidOperationException($"Missing embedded mapping resource {ResourceName}.");
        using var reader = new StreamReader(stream);
        return new AnnotationMapping(reader.ReadToEnd());
    }

    private static string Normalize(string name) => name.Replace("_", "", StringComparison.Ordinal).ToUpperInvariant();
    public int Map(string category, string nativeName)
    {
        if (nativeName != null && enums.TryGetValue(category, out var table) && table.TryGetValue(Normalize(nativeName), out int value)) return value;
        throw new InvalidDataException($"Unsupported native {category} name '{nativeName}'.");
    }
    public int MapTerrain(string name) => Map("terrain", name);
    public int MapResource(string name) => Map("resource", name);
    public int MapImprovement(string name) => Map("improvement", name);
    public int MapUnit(string name) => Map("unit", name);
    public int MapTribe(string name) => Map("tribe", name);
    public int MapSkin(string name) => Map("skin", name);
    public bool IsDefined(string category, int value) => values.TryGetValue(category, out var ids) && ids.Contains(value);
    public bool IsPlayableTribe(int tribeId) => premiumSkins.ContainsKey(tribeId);
    public string TribeName(int tribeId) => tribeNames.TryGetValue(tribeId, out var name) ? name : throw new InvalidDataException($"Unsupported tribe ID {tribeId}.");
    public int PremiumSkin(int tribeId) => premiumSkins.TryGetValue(tribeId, out int skin) ? skin : throw new InvalidDataException($"Unsupported playable tribe ID {tribeId}.");

    /// <summary>Only call for serialized legacy indexes, never for current typed TribeType values.</summary>
    public int NormalizeLegacyTribe(int style) => style >= 0 && style < legacyTribes.Length
        ? legacyTribes[style] : throw new InvalidDataException($"Unsupported legacy tribe style {style}.");

    public int CompactAppearance(int tribeId, int skinId)
    {
        if (!IsDefined("tribe", tribeId) || !IsDefined("skin", skinId))
            throw new InvalidDataException($"Unsupported appearance tribe={tribeId}, skin={skinId}.");
        // Nature is not a playable appearance: retain its known source skin, but never encode a playable label.
        if (tribeId == 1) return 0;
        if (tribeId == 0)
        {
            if (skinId is -1 or 0) return 0;
            throw new InvalidDataException($"Unsupported unset appearance tribe={tribeId}, skin={skinId}.");
        }
        if (skinId is -1 or 0) return tribeId - 1;
        if (premiumSkins[tribeId] == skinId) return tribeId - 1 + 16;
        throw new InvalidDataException($"Unsupported tribe/skin pair tribe={tribeId}, skin={skinId}.");
    }

    public string ColorName(int[] rgb) => colors.TryGetValue(Pack(rgb), out string? name) ? name : "other";
    public int[] DefaultColor(int tribeId, int skinId)
    {
        CompactAppearance(tribeId, skinId);
        int packed = skinColors.TryGetValue(skinId, out int overridden) ? overridden : tribeColors[tribeId];
        return new[] { (packed >> 16) & 255, (packed >> 8) & 255, packed & 255 };
    }
    private static int Pack(int[] rgb)
    {
        if (rgb == null || rgb.Length != 3 || rgb.Any(channel => channel < 0 || channel > 255))
            throw new InvalidDataException("RGB must contain exactly three integer channels in 0..255.");
        return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2];
    }
}
