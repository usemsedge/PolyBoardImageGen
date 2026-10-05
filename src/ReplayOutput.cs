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
    internal ReplayAttempt(Guid id, int version, string path, string? snapshotSha256)
    { Id = id; Version = version; DirectoryPath = path; SnapshotSha256 = snapshotSha256; }
}

public sealed class ReplayArtifact
{
    public string Name { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public long Length { get; set; }
}

public sealed class ReplayManifest
{
    public int SchemaVersion { get; set; } = 1;
    public Guid ReplayId { get; set; }
    public int SerializationVersion { get; set; }
    public string? SnapshotSha256 { get; set; }
    public int MapSize { get; set; }
    public int[] PlayerIds { get; set; } = Array.Empty<int>();
    public string[] Views { get; set; } = Array.Empty<string>();
    public ReplayArtifact[] Artifacts { get; set; } = Array.Empty<ReplayArtifact>();
    public DateTime CompletedUtc { get; set; }
    [System.Text.Json.Serialization.JsonIgnore]
    public string DirectoryPath { get; internal set; } = "";
}

/// <summary>Publishes validated four-view directories. The caller marks the CSV only after Commit succeeds.</summary>
public sealed class ReplayOutput
{
    private readonly string root;
    private readonly HashSet<ReplayAttempt> active = new();
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    public ReplayOutput(string root) { this.root = Path.GetFullPath(root); }

    public ReplayAttempt Begin(Guid id, int version, string? snapshotSha256 = null)
    {
        if (id == Guid.Empty || version <= 0) throw new ArgumentException("A replay ID and positive serialization version are required.");
        if (snapshotSha256 != null && !ValidHash(snapshotSha256)) throw new ArgumentException("Snapshot SHA256 must be 64 hexadecimal characters.");
        if (Directory.Exists(FinalPath(id)))
        {
            if (TryRecover(id, out _)) throw new IOException("Valid replay output already exists; recover it rather than overwrite it.");
            Directory.Move(FinalPath(id), Path.Combine(root, ".invalid-" + id.ToString("D") + "-" + Guid.NewGuid().ToString("N")));
        }
        Directory.CreateDirectory(root);
        string path = Path.Combine(root, ".staging-" + id.ToString("D") + "-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        var attempt = new ReplayAttempt(id, version, path, snapshotSha256);
        active.Add(attempt); return attempt;
    }

    public ReplayManifest Commit(ReplayAttempt attempt, int mapSize, IReadOnlyList<int> playerIds)
    {
        RequireActive(attempt);
        if (mapSize < 1 || mapSize > 100) throw new InvalidDataException("Supported replay maps are square with size 1 through 100.");
        if (playerIds.Count != 2 || playerIds[0] == playerIds[1]) throw new InvalidDataException("Two distinct actual player IDs are required.");
        string[] views = ViewNames(playerIds);
        var artifacts = ValidateArtifacts(attempt.DirectoryPath, mapSize, views);
        var manifest = new ReplayManifest
        {
            ReplayId = attempt.Id, SerializationVersion = attempt.Version, SnapshotSha256 = attempt.SnapshotSha256,
            MapSize = mapSize, PlayerIds = playerIds.ToArray(), Views = views, Artifacts = artifacts,
            CompletedUtc = DateTime.UtcNow
        };
        string manifestPath = Path.Combine(attempt.DirectoryPath, "manifest.json");
        byte[] bytes = System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(manifest, JsonOptions));
        using (var stream = new FileStream(manifestPath, FileMode.Create, FileAccess.Write, FileShare.None))
        { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
        // Revalidate the saved manifest and all artifacts before the atomic directory publication.
        ValidateManifest(attempt.DirectoryPath, attempt.Id);
        Directory.Move(attempt.DirectoryPath, FinalPath(attempt.Id));
        active.Remove(attempt);
        manifest.DirectoryPath = FinalPath(attempt.Id); return manifest;
    }

    public bool TryRecover(Guid id, out ReplayManifest? manifest)
    {
        manifest = null;
        if (!Directory.Exists(FinalPath(id))) return false;
        try { manifest = ValidateManifest(FinalPath(id), id); return true; }
        catch (Exception ex) when (ex is IOException || ex is JsonException || ex is InvalidDataException || ex is ArgumentException || ex is OverflowException)
        { return false; }
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
        string manifestPath = Path.Combine(directory, "manifest.json");
        if ((File.GetAttributes(manifestPath) & FileAttributes.ReparsePoint) != 0 || new FileInfo(manifestPath).Length > 1024 * 1024)
            throw new InvalidDataException("Invalid manifest file.");
        var manifest = JsonSerializer.Deserialize<ReplayManifest>(File.ReadAllText(manifestPath)) ?? throw new InvalidDataException("Empty manifest.");
        if (manifest.SchemaVersion != 1 || manifest.ReplayId != id || manifest.SerializationVersion <= 0 ||
            manifest.MapSize < 1 || manifest.MapSize > 100 || manifest.PlayerIds == null || manifest.PlayerIds.Length != 2 ||
            manifest.PlayerIds[0] == manifest.PlayerIds[1] || manifest.Views == null || manifest.Artifacts == null ||
            (manifest.SnapshotSha256 != null && !ValidHash(manifest.SnapshotSha256))) throw new InvalidDataException("Invalid replay manifest identities.");
        string[] views = ViewNames(manifest.PlayerIds);
        if (!manifest.Views.SequenceEqual(views)) throw new InvalidDataException("Manifest viewpoints do not match its player IDs.");
        var current = ValidateArtifacts(directory, manifest.MapSize, views);
        if (current.Length != manifest.Artifacts.Length) throw new InvalidDataException("Manifest artifact count is incorrect.");
        for (int i = 0; i < current.Length; i++)
        {
            var stored = manifest.Artifacts[i];
            if (stored == null || current[i].Name != stored.Name || current[i].Length != stored.Length || current[i].Sha256 != stored.Sha256)
                throw new InvalidDataException("Published replay artifacts do not match their manifest.");
        }
        manifest.DirectoryPath = directory; return manifest;
    }

    private static ReplayArtifact[] ValidateArtifacts(string directory, int size, string[] views)
    {
        var result = new List<ReplayArtifact>();
        foreach (string view in views)
        {
            var clean = PngDimensions(Path.Combine(directory, view + ".png"));
            var overlay = PngDimensions(Path.Combine(directory, view + ".grid.png"));
            if (clean != overlay) throw new InvalidDataException("Clean and grid image dimensions differ.");
            string gridPath = Path.Combine(directory, view + ".grid.json");
            if (new FileInfo(gridPath).Length > 1024 * 1024) throw new InvalidDataException("Grid metadata is too large.");
            using var json = JsonDocument.Parse(File.ReadAllBytes(gridPath));
            var grid = json.RootElement;
            if (!Integer(grid, "size", size) || !Integer(grid, "width", clean.Width) || !Integer(grid, "height", clean.Height))
                throw new InvalidDataException("Grid metadata dimensions do not match the replay images.");
            double[] anchor = Vector(grid, "anchor"), x = Vector(grid, "stepX"), y = Vector(grid, "stepY");
            if (Math.Abs(x[0] * y[1] - x[1] * y[0]) < 1e-10) throw new InvalidDataException("Grid projection is degenerate.");
            foreach (string suffix in new[] { ".png", ".grid.json", ".grid.png" })
            {
                string name = view + suffix, path = Path.Combine(directory, name);
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked artifacts are not supported.");
                using var stream = File.OpenRead(path);
                using var hasher = SHA256.Create();
                result.Add(new ReplayArtifact { Name = name, Length = stream.Length, Sha256 = Convert.ToHexString(hasher.ComputeHash(stream)).ToLowerInvariant() });
            }
        }
        return result.ToArray();
    }

    private static bool Integer(JsonElement element, string name, int expected) => element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int actual) && actual == expected;
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
        if (info.Length < 57 || info.Length > 128 * 1024 * 1024) throw new InvalidDataException("PNG is empty, truncated or too large.");
        byte[] png = File.ReadAllBytes(path);
        if (!png.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 })) throw new InvalidDataException("Invalid PNG signature.");
        int offset = 8, width = 0, height = 0, channels = 0;
        bool ended = false;
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
                if (width < 1 || height < 1 || width > 16384 || height > 16384 || depth != 8 || channels == 0 ||
                    png[offset + 18] != 0 || png[offset + 19] != 0 || png[offset + 20] != 0)
                    throw new InvalidDataException("Expected a non-interlaced RGB8/RGBA8 PNG with bounded dimensions.");
            }
            else if (type == "IDAT") compressed.Write(png, offset + 8, count);
            else if (type == "IEND")
            {
                if (count != 0 || offset + 12 != png.Length) throw new InvalidDataException("Invalid PNG end chunk.");
                ended = true;
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
    private static string[] ViewNames(IReadOnlyList<int> ids) => ids.SelectMany(id => new[] { $"player-{id}-normal", $"player-{id}-revealed" }).ToArray();
    private static bool ValidHash(string hash) => hash.Length == 64 && hash.All(Uri.IsHexDigit);
    private string FinalPath(Guid id) => Path.Combine(root, id.ToString("D"));
    private void RequireActive(ReplayAttempt attempt)
    { if (!active.Contains(attempt)) throw new InvalidOperationException("This staging attempt is not owned by this output writer."); }
}
