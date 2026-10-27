using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace BoardCaptureLoop;

public sealed class ReplayAttempt
{
    public Guid Id { get; }
    public int Version { get; }
    public string DirectoryPath { get; }
    public string? SnapshotSha256 { get; }
    private readonly CaptureSettings settings;
    public CaptureSettings Settings => settings.Snapshot();
    internal ReplayAttempt(Guid id, int version, string path, string? snapshotSha256, CaptureSettings settings)
    { Id = id; Version = version; DirectoryPath = path; SnapshotSha256 = snapshotSha256; this.settings = settings; }
}

public sealed class ReplayArtifact
{
    public string Name { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public long Length { get; set; }
}

public sealed class ReplayParticipant
{
    public int Id { get; set; }
    public int TribeId { get; set; }
    public int SkinId { get; set; }
    public int TribeSkin { get; set; }
}

public sealed class ReplayManifest
{
    public int SchemaVersion { get; set; } = 2;
    public Guid ReplayId { get; set; }
    public int SerializationVersion { get; set; }
    public string? SnapshotSha256 { get; set; }
    public int MapSize { get; set; }
    public int[] PlayerIds { get; set; } = Array.Empty<int>();
    public ReplayParticipant[] Participants { get; set; } = Array.Empty<ReplayParticipant>();
    public CaptureSettings Settings { get; set; } = new();
    public string MappingVersion { get; set; } = AnnotationMapping.Version;
    public string[] Views { get; set; } = Array.Empty<string>();
    public ReplayArtifact[] Artifacts { get; set; } = Array.Empty<ReplayArtifact>();
    public DateTime CompletedUtc { get; set; }
    [System.Text.Json.Serialization.JsonIgnore]
    public string DirectoryPath { get; internal set; } = "";
}

/// <summary>Publishes complete annotated normal-view directories before CSV completion is marked.</summary>
public sealed class ReplayOutput
{
    private readonly string root;
    private readonly HashSet<ReplayAttempt> active = new();
    private readonly Action<string>? log;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    public ReplayOutput(string root, Action<string>? log = null) { this.root = Path.GetFullPath(root); this.log = log; }

    public ReplayAttempt Begin(Guid id, int version, string? snapshotSha256 = null, CaptureSettings? settings = null)
    {
        if (id == Guid.Empty || version <= 0) throw new ArgumentException("A replay ID and positive serialization version are required.");
        if (snapshotSha256 != null && !ValidHash(snapshotSha256)) throw new ArgumentException("Snapshot SHA256 must be 64 hexadecimal characters.");
        var recordedSettings = (settings ?? new CaptureSettings()).Snapshot();
        if (Directory.Exists(FinalPath(id)))
        {
            if (TryRecover(id, out _)) throw new IOException("Valid replay output already exists; recover it rather than overwrite it.");
            if ((File.GetAttributes(FinalPath(id)) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked output directories are not supported.");
            Directory.Move(FinalPath(id), Path.Combine(root, ".invalid-" + id.ToString("D") + "-" + Guid.NewGuid().ToString("N")));
        }
        Directory.CreateDirectory(root);
        string path = Path.Combine(root, ".staging-" + id.ToString("D") + "-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        var attempt = new ReplayAttempt(id, version, path, snapshotSha256, recordedSettings);
        active.Add(attempt); return attempt;
    }

    // Retain source compatibility, but never fabricate tribe/skin identities for annotation-enabled output.
    public ReplayManifest Commit(ReplayAttempt attempt, int mapSize, IReadOnlyList<int> playerIds)
    {
        RequireActive(attempt);
        throw new InvalidDataException("Annotation-enabled output requires explicit participant tribe and skin metadata.");
    }

    public ReplayManifest Commit(ReplayAttempt attempt, int mapSize, IReadOnlyList<ReplayParticipant> participants)
    {
        RequireActive(attempt);
        ValidateParticipants(participants);
        var copied = participants.Select(p => new ReplayParticipant { Id = p.Id, TribeId = p.TribeId, SkinId = p.SkinId, TribeSkin = p.TribeSkin }).ToArray();
        var manifest = new ReplayManifest
        {
            ReplayId = attempt.Id, SerializationVersion = attempt.Version, SnapshotSha256 = attempt.SnapshotSha256,
            MapSize = mapSize, PlayerIds = copied.Select(p => p.Id).ToArray(), Participants = copied,
            Settings = attempt.Settings.Snapshot(), CompletedUtc = DateTime.UtcNow
        };
        manifest.Views = ViewNames(manifest.PlayerIds);
        manifest.Artifacts = ValidateArtifacts(attempt.DirectoryPath, manifest);
        string manifestPath = Path.Combine(attempt.DirectoryPath, "manifest.json");
        byte[] bytes = System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(manifest, JsonOptions));
        using (var stream = new FileStream(manifestPath, FileMode.Create, FileAccess.Write, FileShare.None))
        { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
        ValidateManifest(attempt.DirectoryPath, attempt.Id);
        Directory.Move(attempt.DirectoryPath, FinalPath(attempt.Id));
        active.Remove(attempt);
        manifest.DirectoryPath = FinalPath(attempt.Id); return manifest;
    }

    public bool TryRecover(Guid id, out ReplayManifest? manifest)
    {
        manifest = null;
        if (id == Guid.Empty || !Directory.Exists(FinalPath(id))) return false;
        try { manifest = ValidateManifest(FinalPath(id), id); return true; }
        catch (Exception ex) when (ValidationFailure(ex))
        { log?.Invoke($"Replay {id:D}: invalid completed output: {ex.Message}"); return false; }
    }

    public IEnumerable<ReplayManifest> EnumerateCompleted(Action<string>? diagnostics = null)
    {
        if (!Directory.Exists(root)) yield break;
        foreach (string directory in Directory.EnumerateDirectories(root).OrderBy(p => p, StringComparer.Ordinal))
        {
            string name = Path.GetFileName(directory);
            if (!Guid.TryParseExact(name, "D", out Guid id) || id == Guid.Empty || name != id.ToString("D")) continue;
            ReplayManifest? manifest = null;
            try { manifest = ValidateManifest(directory, id); }
            catch (Exception ex) when (ValidationFailure(ex))
            { (diagnostics ?? log)?.Invoke($"Replay {id:D}: ignored invalid completed output: {ex.Message}"); }
            if (manifest != null) yield return manifest;
        }
    }

    public void Abandon(ReplayAttempt attempt)
    {
        RequireActive(attempt);
        if (Directory.Exists(attempt.DirectoryPath)) Directory.Delete(attempt.DirectoryPath, true);
        active.Remove(attempt);
    }

    private ReplayManifest ValidateManifest(string directory, Guid id)
    {
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked output directories are not supported.");
        using var json = StrictJson.ReadFile(Path.Combine(directory, "manifest.json"), 1024 * 1024);
        var document = json.RootElement;
        StrictJson.Properties(document, new[] { "SchemaVersion", "ReplayId", "SerializationVersion", "SnapshotSha256", "MapSize", "PlayerIds", "Participants", "Settings", "MappingVersion", "Views", "Artifacts", "CompletedUtc" });
        var manifest = document.Deserialize<ReplayManifest>() ?? throw new InvalidDataException("Empty manifest.");
        if (manifest.SchemaVersion != 2 || manifest.ReplayId != id || manifest.SerializationVersion <= 0 ||
            manifest.MapSize < 1 || manifest.MapSize > 100 || manifest.PlayerIds == null || manifest.Views == null || manifest.Artifacts == null ||
            manifest.Settings == null || manifest.MappingVersion != AnnotationMapping.Version || manifest.CompletedUtc.Kind != DateTimeKind.Utc ||
            manifest.CompletedUtc == default || (manifest.SnapshotSha256 != null && !ValidHash(manifest.SnapshotSha256)))
            throw new InvalidDataException("Invalid replay manifest identities or mapping version.");
        manifest.Settings = CaptureSettings.FromJson(document.GetProperty("Settings"));
        ValidateParticipants(manifest.Participants);
        foreach (var participant in document.GetProperty("Participants").EnumerateArray())
            StrictJson.Properties(participant, new[] { "Id", "TribeId", "SkinId", "TribeSkin" });
        if (!manifest.PlayerIds.SequenceEqual(manifest.Participants.Select(p => p.Id))) throw new InvalidDataException("Participant IDs do not match PlayerIds.");
        string[] views = ViewNames(manifest.PlayerIds);
        string[] legacyViews = manifest.PlayerIds.SelectMany(player => new[] { $"player-{player}-normal", $"player-{player}-revealed" }).ToArray();
        if (!manifest.Views.SequenceEqual(views) && !manifest.Views.SequenceEqual(legacyViews))
            throw new InvalidDataException("Manifest viewpoints do not match its player IDs.");
        foreach (var artifact in document.GetProperty("Artifacts").EnumerateArray())
            StrictJson.Properties(artifact, new[] { "Name", "Sha256", "Length" });
        var current = ValidateArtifacts(directory, manifest);
        if (current.Length != manifest.Artifacts.Length) throw new InvalidDataException("Manifest artifact count is incorrect.");
        for (int i = 0; i < current.Length; i++)
        {
            var stored = manifest.Artifacts[i];
            if (stored == null || current[i].Name != stored.Name || current[i].Length != stored.Length || current[i].Sha256 != stored.Sha256)
                throw new InvalidDataException("Published replay artifacts do not match their manifest.");
        }
        manifest.DirectoryPath = directory; return manifest;
    }

    private static void ValidateParticipants(IReadOnlyList<ReplayParticipant>? participants)
    {
        if (participants == null || participants.Count != 2 || participants.Any(p => p == null) ||
            participants[0].Id == participants[1].Id || participants.Any(p => p.Id <= 0))
            throw new InvalidDataException("Two distinct actual player identities are required.");
        foreach (var participant in participants)
        {
            if (!AnnotationMapping.Default.IsPlayableTribe(participant.TribeId) ||
                AnnotationMapping.Default.CompactAppearance(participant.TribeId, participant.SkinId) != participant.TribeSkin)
                throw new InvalidDataException($"Player {participant.Id}: unsupported or mismatched tribe/skin {participant.TribeId}/{participant.SkinId}/{participant.TribeSkin}.");
        }
    }

    private ReplayArtifact[] ValidateArtifacts(string directory, ReplayManifest manifest)
    {
        int size = manifest.MapSize;
        if (size < 1 || size > 100) throw new InvalidDataException("Supported replay maps are square with size 1 through 100.");
        manifest.Settings.Validate();
        var result = new List<ReplayArtifact>();
        var expected = new HashSet<string>(StringComparer.Ordinal) { "manifest.json" };
        foreach (string view in manifest.Views)
        {
            try
            {
                var clean = PngDimensions(Path.Combine(directory, view + ".png"));
                if (manifest.Settings.ShowGridOverlay && clean != PngDimensions(Path.Combine(directory, view + ".grid.png")))
                    throw new InvalidDataException("Clean and grid image dimensions differ.");
                using var json = StrictJson.ReadFile(Path.Combine(directory, view + ".grid.json"), 1024 * 1024);
                var grid = json.RootElement;
                StrictJson.Properties(grid, new[] { "size", "width", "height", "anchor", "stepX", "stepY", "targetTilePixels", "sideLengthPixels", "otherSideLengthPixels" });
                if (!Integer(grid, "size", size) || !Integer(grid, "width", clean.Width) || !Integer(grid, "height", clean.Height) ||
                    !Integer(grid, "targetTilePixels", manifest.Settings.TargetTilePixels))
                    throw new InvalidDataException("Grid metadata dimensions/target do not match recorded settings and images.");
                double[] anchor = Vector(grid, "anchor"), x = Vector(grid, "stepX"), y = Vector(grid, "stepY");
                double determinant = x[0] * y[1] - x[1] * y[0];
                if (!double.IsFinite(determinant) || Math.Abs(determinant) < 1e-10) throw new InvalidDataException("Grid projection is degenerate.");
                double xLength = Math.Sqrt(x[0] * x[0] + x[1] * x[1]), yLength = Math.Sqrt(y[0] * y[0] + y[1] * y[1]);
                if (!Near(Number(grid, "sideLengthPixels"), xLength) || !Near(Number(grid, "otherSideLengthPixels"), yLength) ||
                    Math.Min(xLength, yLength) + 0.001 < manifest.Settings.TargetTilePixels)
                    throw new InvalidDataException("Grid edge lengths are invalid or below the requested target.");
                foreach (double a in new[] { -0.5, size - 0.5 }) foreach (double b in new[] { -0.5, size - 0.5 })
                {
                    double px = anchor[0] + a * x[0] + b * y[0], py = anchor[1] + a * x[1] + b * y[1];
                    if (!double.IsFinite(px) || !double.IsFinite(py) || px < -0.001 || py < -0.001 || px > clean.Width + 0.001 || py > clean.Height + 0.001)
                        throw new InvalidDataException("Grid boundary extends outside the image.");
                }
                using var tilesJson = StrictJson.ReadFile(Path.Combine(directory, view + ".tiles.json"), 32 * 1024 * 1024);
                ValidateAnnotationProperties(tilesJson.RootElement);
                var tiles = TileAnnotationValidator.ParseAndValidate(tilesJson.RootElement.GetRawText(), log);
                int viewsPerPlayer = manifest.Views.Length / manifest.PlayerIds.Length;
                int playerId = manifest.PlayerIds[Array.IndexOf(manifest.Views, view) / viewsPerPlayer];
                string mode = view.EndsWith("-revealed", StringComparison.Ordinal) ? "revealed" : "normal";
                if (tiles.ReplayId != manifest.ReplayId.ToString("D") || tiles.PlayerId != playerId || tiles.View != mode || tiles.Size != size ||
                    tiles.GridFile != view + ".grid.json" || tiles.MappingVersion != manifest.MappingVersion)
                    throw new InvalidDataException("Annotation metadata does not match the replay/view/grid/mapping identities.");
                string[] suffixes = manifest.Settings.ShowGridOverlay ? new[] { ".png", ".grid.json", ".tiles.json", ".grid.png" } : new[] { ".png", ".grid.json", ".tiles.json" };
                foreach (string suffix in suffixes)
                {
                    string name = view + suffix, path = Path.Combine(directory, name);
                    expected.Add(name);
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked artifacts are not supported.");
                    using var stream = File.OpenRead(path);
                    using var hasher = SHA256.Create();
                    result.Add(new ReplayArtifact { Name = name, Length = stream.Length, Sha256 = Convert.ToHexString(hasher.ComputeHash(stream)).ToLowerInvariant() });
                }
            }
            catch (Exception ex) when (ValidationFailure(ex))
            { throw new InvalidDataException($"Replay {manifest.ReplayId:D}, view {view}: {ex.Message}", ex); }
        }
        if (Directory.EnumerateFileSystemEntries(directory).Any(path => !expected.Contains(Path.GetFileName(path)) || Directory.Exists(path)))
            throw new InvalidDataException("Replay directory contains unexpected artifacts (including disabled overlays).");
        return result.ToArray();
    }

    private static void ValidateAnnotationProperties(JsonElement document)
    {
        StrictJson.Properties(document, new[] { "schema_version", "replay_id", "player_id", "view", "size", "grid_file", "mapping_version", "tiles" });
        if (document.GetProperty("tiles").ValueKind != JsonValueKind.Array) throw new InvalidDataException("Annotation tiles must be an array.");
        foreach (var tile in document.GetProperty("tiles").EnumerateArray())
        {
            StrictJson.Properties(tile, new[] { "x", "y", "fog", "improvement", "resource", "terrain", "road", "terrain_tribe_skin", "terrain_appearance", "main_unit", "top_right_unit_icon" });
            StrictJson.Properties(tile.GetProperty("terrain_appearance"), new[] { "tribe_id", "skin_id" });
            StrictJson.Properties(tile.GetProperty("main_unit"), new[] { "type", "tribe_skin", "tribe_id", "skin_id", "color_rgb", "color_name", "hp" });
            StrictJson.Properties(tile.GetProperty("top_right_unit_icon"), new[] { "type" });
        }
    }

    private static bool ValidationFailure(Exception ex) => ex is IOException || ex is InvalidDataException || ex is JsonException || ex is ArgumentException || ex is OverflowException || ex is UnauthorizedAccessException || ex is InvalidOperationException;
    private static bool Integer(JsonElement element, string name, int expected) => StrictJson.Int(element, name) == expected;
    private static double Number(JsonElement element, string name)
    {
        var value = element.GetProperty(name);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out double result) || !double.IsFinite(result) || result <= 0)
            throw new InvalidDataException("Invalid grid edge length: " + name);
        return result;
    }
    private static bool Near(double actual, double expected) => Math.Abs(actual - expected) <= Math.Max(0.001, expected * 0.00001);
    private static double[] Vector(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 2)
            throw new InvalidDataException("Grid projection vector is missing.");
        var vector = value.EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out double d) ? d : double.NaN).ToArray();
        if (vector.Any(v => !double.IsFinite(v))) throw new InvalidDataException("Grid projection contains non-finite coordinates.");
        return vector;
    }

    private static (int Width, int Height) PngDimensions(string path)
    {
        var info = new FileInfo(path);
        if ((info.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked PNG artifacts are not supported.");
        if (info.Length < 57 || info.Length > 128 * 1024 * 1024) throw new InvalidDataException("PNG is empty, truncated or too large.");
        byte[] png = File.ReadAllBytes(path);
        if (!png.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 })) throw new InvalidDataException("Invalid PNG signature.");
        int offset = 8, width = 0, height = 0, channels = 0;
        bool ended = false, seenData = false, dataEnded = false;
        using var compressed = new MemoryStream();
        while (offset < png.Length)
        {
            if (png.Length - offset < 12) throw new InvalidDataException("Truncated PNG chunk.");
            uint length = BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset, 4));
            if (length > png.Length - offset - 12) throw new InvalidDataException("Truncated PNG chunk data.");
            int count = (int)length;
            string type = System.Text.Encoding.ASCII.GetString(png, offset + 4, 4);
            var chunk = png.AsSpan(offset + 4, count + 4);
            if (Crc32(chunk) != BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset + 8 + count, 4))) throw new InvalidDataException("PNG chunk checksum mismatch.");
            if (offset == 8 && type != "IHDR") throw new InvalidDataException("PNG header is missing.");
            if (type == "IHDR")
            {
                if (offset != 8 || count != 13) throw new InvalidDataException("Invalid PNG header.");
                width = BinaryPrimitives.ReadInt32BigEndian(png.AsSpan(offset + 8, 4));
                height = BinaryPrimitives.ReadInt32BigEndian(png.AsSpan(offset + 12, 4));
                byte depth = png[offset + 16], color = png[offset + 17];
                channels = color == 2 ? 3 : color == 6 ? 4 : 0;
                if (width < 1 || height < 1 || width > 16384 || height > 16384 || (long)width * height > 16_000_000 || depth != 8 || channels == 0 ||
                    png[offset + 18] != 0 || png[offset + 19] != 0 || png[offset + 20] != 0)
                    throw new InvalidDataException("Expected a non-interlaced RGB8/RGBA8 PNG with bounded dimensions.");
            }
            else if (type == "IDAT")
            {
                if (dataEnded) throw new InvalidDataException("PNG IDAT chunks must be contiguous.");
                seenData = true; compressed.Write(png, offset + 8, count);
            }
            else if (type == "IEND")
            {
                if (!seenData || count != 0 || offset + 12 != png.Length) throw new InvalidDataException("Invalid PNG end chunk.");
                ended = true;
            }
            else
            {
                if (type.Length != 4 || type.Any(c => !(c >= 'A' && c <= 'Z') && !(c >= 'a' && c <= 'z')) || (type[0] >= 'A' && type[0] <= 'Z' && type != "PLTE"))
                    throw new InvalidDataException("Unsupported PNG critical chunk.");
                if (type == "PLTE" && (seenData || count == 0 || count % 3 != 0 || count > 768))
                    throw new InvalidDataException("Invalid PNG palette chunk.");
                if (seenData) dataEnded = true;
            }
            offset += count + 12;
        }
        if (!ended || compressed.Length == 0) throw new InvalidDataException("PNG image data is incomplete.");
        long rowLength = (long)width * channels + 1;
        long expected = rowLength * height;
        if (expected > 256 * 1024 * 1024) throw new InvalidDataException("Decoded PNG exceeds validation limit.");
        compressed.Position = 0;
        using var decompressed = new ZLibStream(compressed, CompressionMode.Decompress);
        var buffer = new byte[81920]; long total = 0; int read;
        while ((read = decompressed.Read(buffer, 0, buffer.Length)) != 0)
        {
            for (int i = 0; i < read; i++) if ((total + i) % rowLength == 0 && buffer[i] > 4) throw new InvalidDataException("Invalid PNG scanline filter.");
            total += read;
            if (total > expected) throw new InvalidDataException("PNG contains excess image data.");
        }
        if (total != expected) throw new InvalidDataException("PNG image data is truncated.");
        return (width, height);
    }

    private static uint Crc32(ReadOnlySpan<byte> data)
    {
        uint crc = uint.MaxValue;
        foreach (byte b in data)
        {
            crc ^= b;
            for (int i = 0; i < 8; i++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0u);
        }
        return ~crc;
    }
    private static string[] ViewNames(IReadOnlyList<int> ids) => ids.Select(id => $"player-{id}-normal").ToArray();
    private static bool ValidHash(string hash) => hash.Length == 64 && hash.All(Uri.IsHexDigit);
    private string FinalPath(Guid id) => Path.Combine(root, id.ToString("D"));
    private void RequireActive(ReplayAttempt attempt)
    { if (!active.Contains(attempt)) throw new InvalidOperationException("This staging attempt is not owned by this output writer."); }
}
