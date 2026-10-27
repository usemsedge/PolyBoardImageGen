using System.Text.Json;

namespace BoardCaptureLoop;

public static class CaptureMigration
{
    private sealed class Journal
    {
        public int Version { get; set; } = 1;
        public bool Complete { get; set; }
        public string[] Paths { get; set; } = Array.Empty<string>();
        public Guid[] ReplayIds { get; set; } = Array.Empty<Guid>();
    }

    public static void Run(string root, ReplayCatalog catalog, Action<string>? log = null)
    {
        Directory.CreateDirectory(root);
        RejectLink(root);
        string marker = Path.Combine(root, ".annotation-migration.json");
        Journal journal;
        if (File.Exists(marker))
        {
            RejectLink(marker);
            journal = JsonSerializer.Deserialize<Journal>(File.ReadAllText(marker)) ?? throw new InvalidDataException("Invalid migration journal.");
            if (journal.Version != 1 || journal.Paths == null || journal.ReplayIds == null) throw new InvalidDataException("Unsupported migration journal.");
        }
        else
        {
            var paths = new List<string>();
            var ids = new HashSet<Guid>();
            foreach (string directory in Directory.EnumerateDirectories(root))
            {
                string name = Path.GetFileName(directory);
                bool candidate = Guid.TryParseExact(name, "D", out Guid id) || name.StartsWith(".staging-", StringComparison.Ordinal) || name.StartsWith(".invalid-", StringComparison.Ordinal);
                if (!candidate) continue;
                RejectLink(directory);
                string manifest = Path.Combine(directory, "manifest.json");
                if (File.Exists(manifest))
                {
                    RejectLink(manifest);
                    using var json = JsonDocument.Parse(File.ReadAllBytes(manifest));
                    if (!json.RootElement.TryGetProperty("SchemaVersion", out var schema) || !schema.TryGetInt32(out int version))
                        throw new InvalidDataException("Cannot classify capture for migration: " + name);
                    if (version >= 2) continue;
                    if (version != 1) throw new InvalidDataException("Unknown legacy capture schema: " + name);
                }
                paths.Add(name);
                if (id != Guid.Empty) ids.Add(id);
            }
            foreach (ReplayEntry completed in catalog.GetCompleted())
            {
                string manifest = Path.Combine(root, completed.Id.ToString("D"), "manifest.json");
                if (!File.Exists(manifest)) { ids.Add(completed.Id); continue; }
                using var json = JsonDocument.Parse(File.ReadAllBytes(manifest));
                if (json.RootElement.GetProperty("SchemaVersion").GetInt32() == 1) ids.Add(completed.Id);
            }
            journal = new Journal { Paths = paths.ToArray(), ReplayIds = ids.ToArray() };
            Save(marker, journal);
        }
        foreach (string name in journal.Paths)
            if (name != Path.GetFileName(name) || name is "." or ".." ||
                !(Guid.TryParseExact(name, "D", out _) || name.StartsWith(".staging-", StringComparison.Ordinal) || name.StartsWith(".invalid-", StringComparison.Ordinal)))
                throw new InvalidDataException("Unsafe migration path.");
        // Reconcile another configured CSV too; reset only IDs lacking a new manifest.
        var reset = journal.ReplayIds.Where(id => !HasAnnotatedManifest(root, id)).ToArray();
        catalog.ResetCompleted(reset);
        if (journal.Complete) return;
        foreach (string name in journal.Paths)
        {
            if (name != Path.GetFileName(name) || name is "." or ".." ||
                !(Guid.TryParseExact(name, "D", out _) || name.StartsWith(".staging-", StringComparison.Ordinal) || name.StartsWith(".invalid-", StringComparison.Ordinal)))
                throw new InvalidDataException("Unsafe migration path.");
            string directory = Path.Combine(root, name);
            if (!Directory.Exists(directory)) continue;
            string manifest = Path.Combine(directory, "manifest.json");
            if (File.Exists(manifest))
            {
                RejectLink(manifest);
                using var json = JsonDocument.Parse(File.ReadAllBytes(manifest));
                if (!json.RootElement.TryGetProperty("SchemaVersion", out var schema) || !schema.TryGetInt32(out int version))
                    throw new InvalidDataException("Cannot classify journaled capture: " + name);
                if (version >= 2) continue;
                if (version != 1) throw new InvalidDataException("Unknown journaled capture schema: " + name);
            }
            foreach (string item in EnumerateTree(directory)) RejectLink(item);
            Directory.Delete(directory, true);
            log?.Invoke("Deleted legacy capture " + name);
        }
        string statistics = Path.Combine(root, "output.json");
        if (File.Exists(statistics)) { RejectLink(statistics); File.Delete(statistics); }
        journal.Complete = true;
        Save(marker, journal);
    }

    private static bool HasAnnotatedManifest(string root, Guid id)
    {
        string path = Path.Combine(root, id.ToString("D"), "manifest.json");
        if (!File.Exists(path)) return false;
        RejectLink(path);
        using var json = JsonDocument.Parse(File.ReadAllBytes(path));
        return json.RootElement.TryGetProperty("SchemaVersion", out var value) && value.TryGetInt32(out int version) && version >= 2;
    }

    private static IEnumerable<string> EnumerateTree(string directory)
    {
        RejectLink(directory);
        yield return directory;
        foreach (string item in Directory.EnumerateFileSystemEntries(directory))
        {
            RejectLink(item);
            yield return item;
            if (Directory.Exists(item)) foreach (string child in EnumerateTree(item)) yield return child;
        }
    }

    private static void RejectLink(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("Migration refuses linked paths: " + path);
    }

    private static void Save(string path, Journal journal)
    {
        string temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(journal, new JsonSerializerOptions { WriteIndented = true });
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
