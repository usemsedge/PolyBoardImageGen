using System.Text.Json;
using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class MigrationTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "MigrationTests-" + Guid.NewGuid().ToString("N"));
    public MigrationTests() { Directory.CreateDirectory(directory); }
    public void Dispose() { Directory.Delete(directory, true); }

    [Fact]
    public void LegacyCleanupResetsDonePreservesLinksAndRunsOnce()
    {
        Guid id = Guid.NewGuid();
        string csv = Path.Combine(directory, "queue.csv"), root = Path.Combine(directory, "captures");
        string link = "https://share.polytopia.io/g/" + id;
        File.WriteAllText(csv, "REPLAY LINK,note,capture_status\r\n" + link + ",keep,done\r\n");
        string old = Path.Combine(root, id.ToString("D")); Directory.CreateDirectory(old);
        File.WriteAllText(Path.Combine(old, "manifest.json"), "{\"SchemaVersion\":1}");
        using var catalog = ReplayCatalog.Open(csv);
        CaptureMigration.Run(root, catalog);
        Assert.False(Directory.Exists(old));
        Assert.Single(catalog.GetPending());
        Assert.Contains(link + ",keep", File.ReadAllText(csv));
        Directory.CreateDirectory(old);
        File.WriteAllText(Path.Combine(old, "manifest.json"), "{\"SchemaVersion\":2}");
        catalog.Mark(id, ReplayStatus.Done, old);
        CaptureMigration.Run(root, catalog);
        Assert.True(Directory.Exists(old));
        Assert.Single(catalog.GetCompleted());
    }

    [Fact]
    public void InterruptedJournalResumesWithoutRediscoveringTargets()
    {
        Guid id = Guid.NewGuid();
        string csv = Path.Combine(directory, "queue.csv"), root = Path.Combine(directory, "captures");
        File.WriteAllText(csv, "REPLAY LINK,capture_status\r\nhttps://share.polytopia.io/g/" + id + ",done\r\n");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, ".annotation-migration.json"), JsonSerializer.Serialize(new { Version = 1, Complete = false, Paths = new[] { id.ToString("D") }, ReplayIds = new[] { id } }));
        using var catalog = ReplayCatalog.Open(csv);
        CaptureMigration.Run(root, catalog);
        Assert.Single(catalog.GetPending());
        using var journal = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, ".annotation-migration.json")));
        Assert.True(journal.RootElement.GetProperty("Complete").GetBoolean());
    }

    [Fact]
    public void ResumedJournalDoesNotDeleteReplacementAnnotatedCapture()
    {
        Guid id = Guid.NewGuid();
        string csv = Path.Combine(directory, "queue.csv"), root = Path.Combine(directory, "captures");
        File.WriteAllText(csv, "REPLAY LINK,capture_status\r\nhttps://share.polytopia.io/g/" + id + ",done\r\n");
        string capture = Path.Combine(root, id.ToString("D")); Directory.CreateDirectory(capture);
        File.WriteAllText(Path.Combine(capture, "manifest.json"), "{\"SchemaVersion\":2}");
        File.WriteAllText(Path.Combine(root, ".annotation-migration.json"), JsonSerializer.Serialize(new { Version = 1, Complete = false, Paths = new[] { id.ToString("D") }, ReplayIds = new[] { id } }));
        using var catalog = ReplayCatalog.Open(csv);
        CaptureMigration.Run(root, catalog);
        Assert.True(Directory.Exists(capture));
        Assert.Single(catalog.GetCompleted());
    }

    [Fact]
    public void FutureSchemaIsNotDeleted()
    {
        Guid id = Guid.NewGuid();
        string csv = Path.Combine(directory, "queue.csv"), root = Path.Combine(directory, "captures");
        File.WriteAllText(csv, "REPLAY LINK\r\nhttps://share.polytopia.io/g/" + id + "\r\n");
        string future = Path.Combine(root, id.ToString("D")); Directory.CreateDirectory(future);
        File.WriteAllText(Path.Combine(future, "manifest.json"), "{\"SchemaVersion\":100}");
        using var catalog = ReplayCatalog.Open(csv);
        CaptureMigration.Run(root, catalog);
        Assert.True(Directory.Exists(future));
    }
}
