using System.Buffers.Binary;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class OutputContractTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "OutputContract-" + Guid.NewGuid().ToString("N"));
    private readonly Guid id = Guid.NewGuid();
    public OutputContractTests() { Directory.CreateDirectory(root); }
    public void Dispose() { Directory.Delete(root, true); }

    [Theory]
    [InlineData(false, 6)]
    [InlineData(true, 8)]
    public void RequiredAnnotationsAndOptionalOverlaysAreHashedAndRecoverable(bool overlay, int artifacts)
    {
        var output = new ReplayOutput(root);
        var settings = new CaptureSettings { ShowGridOverlay = overlay, TargetTilePixels = 32, CsvFilename = "relative.csv" };
        var attempt = output.Begin(id, 123, settings: settings);
        settings.TargetTilePixels = 512; // Begin records a snapshot, not the mutable run object.
        OutputFixture.Fill(attempt.DirectoryPath, id, overlay: overlay, target: 32);
        var manifest = output.Commit(attempt, 1, OutputFixture.Participants);
        Assert.Equal(2, manifest.SchemaVersion);
        Assert.Equal(artifacts, manifest.Artifacts.Length);
        Assert.Equal(32, manifest.Settings.TargetTilePixels);
        Assert.Equal(AnnotationMapping.Version, manifest.MappingVersion);
        Assert.Equal(2, manifest.Participants.Length);
        Assert.True(new ReplayOutput(root).TryRecover(id, out var recovered));
        Assert.Equal("relative.csv", recovered!.Settings.CsvFilename);
        File.AppendAllText(Path.Combine(manifest.DirectoryPath, "player-1-normal.tiles.json"), " ");
        Assert.False(output.TryRecover(id, out _));
    }

    [Theory]
    [InlineData("missing-tiles")]
    [InlineData("extra-overlay")]
    [InlineData("duplicate-grid-field")]
    [InlineData("wrong-target")]
    [InlineData("wrong-length")]
    [InlineData("outside-image")]
    [InlineData("wrong-player")]
    [InlineData("wrong-mapping")]
    [InlineData("extra-revealed")]
    public void RejectsIncompleteOrInvalidContract(string corruption)
    {
        var output = new ReplayOutput(root);
        var attempt = output.Begin(id, 123, settings: new CaptureSettings { TargetTilePixels = 32 });
        OutputFixture.Fill(attempt.DirectoryPath, id, target: 32);
        string prefix = Path.Combine(attempt.DirectoryPath, "player-1-normal");
        if (corruption == "missing-tiles") File.Delete(prefix + ".tiles.json");
        if (corruption == "extra-overlay") File.WriteAllBytes(prefix + ".grid.png", OutputFixture.Png(128, 128));
        if (corruption == "duplicate-grid-field") Rewrite(prefix + ".grid.json", s => s.Replace("\"size\":1", "\"size\":1,\"size\":1"));
        if (corruption == "wrong-target") Rewrite(prefix + ".grid.json", s => s.Replace("\"targetTilePixels\":32", "\"targetTilePixels\":33"));
        if (corruption == "wrong-length") Rewrite(prefix + ".grid.json", s => s.Replace("\"sideLengthPixels\":32", "\"sideLengthPixels\":31"));
        if (corruption == "outside-image") Rewrite(prefix + ".grid.json", s => s.Replace("\"anchor\":[64,64]", "\"anchor\":[0,0]"));
        if (corruption == "wrong-player") Rewrite(prefix + ".tiles.json", s => s.Replace("\"player_id\":1", "\"player_id\":99"));
        if (corruption == "wrong-mapping") Rewrite(prefix + ".tiles.json", s => s.Replace(AnnotationMapping.Version, "unknown"));
        if (corruption == "extra-revealed") File.Copy(prefix + ".png", Path.Combine(attempt.DirectoryPath, "player-1-revealed.png"));
        Assert.ThrowsAny<Exception>(() => output.Commit(attempt, 1, OutputFixture.Participants));
        Assert.False(output.TryRecover(id, out _));
        output.Abandon(attempt);
    }

    [Theory]
    [InlineData("mapping")]
    [InlineData("schema")]
    [InlineData("participants")]
    [InlineData("settings")]
    [InlineData("duplicate")]
    public void RecoveryRejectsInvalidManifestMetadata(string corruption)
    {
        var output = new ReplayOutput(root);
        var attempt = output.Begin(id, 123);
        OutputFixture.Fill(attempt.DirectoryPath, id);
        var manifest = output.Commit(attempt, 1, OutputFixture.Participants);
        string path = Path.Combine(manifest.DirectoryPath, "manifest.json");
        if (corruption == "mapping") manifest.MappingVersion = "unknown";
        if (corruption == "schema") manifest.SchemaVersion = 1;
        if (corruption == "participants") manifest.Participants[0].TribeSkin = 32;
        if (corruption == "settings") manifest.Settings.TargetTilePixels = 512;
        File.WriteAllText(path, JsonSerializer.Serialize(manifest));
        if (corruption == "duplicate") Rewrite(path, s => s.Replace("\"SchemaVersion\":2", "\"SchemaVersion\":2,\"SchemaVersion\":2"));
        Assert.False(output.TryRecover(id, out _));
    }

    [Fact]
    public void StatisticsRebuildCountsCleanPovImagesAndIgnoresNoncanonicalAndDamagedDirectories()
    {
        var output = new ReplayOutput(root);
        var attempt = output.Begin(id, 123);
        OutputFixture.Fill(attempt.DirectoryPath, id);
        var manifest = output.Commit(attempt, 1, OutputFixture.Participants);
        string duplicate = Path.Combine(root, ".staging-copy"); Directory.CreateDirectory(duplicate);
        foreach (string file in Directory.GetFiles(manifest.DirectoryPath)) File.Copy(file, Path.Combine(duplicate, Path.GetFileName(file)));
        string statistics = Path.Combine(root, "output.json");
        File.WriteAllText(statistics, "broken");
        var counts = CaptureStatistics.Rebuild(root, statistics);
        Assert.Equal(16, counts.Count);
        Assert.Equal(1, counts["aimo"].Default);
        Assert.Equal(1, counts["imperius"].Default);
        Assert.Equal(0, counts["bardur"].Default);
        Assert.Equal(2,counts.Values.Sum(c => c.Default + c.Skin));
        Assert.Equal(2,CaptureStatistics.Rebuild(root, statistics).Values.Sum(c => c.Default + c.Skin));
        Assert.Single(output.EnumerateCompleted());
        File.Delete(Path.Combine(manifest.DirectoryPath, "player-7-normal.tiles.json"));
        var logs = new List<string>();
        Assert.Equal(0, CaptureStatistics.Rebuild(root, statistics, logs.Add).Values.Sum(c => c.Default + c.Skin));
        Assert.NotEmpty(logs);
        Assert.Empty(Directory.GetFiles(root, ".statistics-*"));
    }

    [Fact]
    public void PremiumStatisticsCountOncePerParticipantAndDoNotRequireCurrentSettings()
    {
        var output = new ReplayOutput(root);
        var attempt = output.Begin(id, 123, settings: new CaptureSettings { ShowGridOverlay = true, TargetTilePixels = 32 });
        OutputFixture.Fill(attempt.DirectoryPath, id, overlay: true, target: 32);
        var participants = OutputFixture.Participants;
        participants[0].SkinId = AnnotationMapping.Default.PremiumSkin(participants[0].TribeId);
        participants[0].TribeSkin = 17;
        output.Commit(attempt, 1, participants);
        var counts = CaptureStatistics.Rebuild(root, Path.Combine(root, "output.json"));
        Assert.Equal(1, counts["aimo"].Skin);
        Assert.Equal(0, counts["aimo"].Default);
        Assert.Equal(1, counts["imperius"].Default);
        Assert.True(new ReplayOutput(root).TryRecover(id, out _));
    }

    [Fact]
    public void PngPixelLimitIsValidatedBeforeDecoding()
    {
        var output = new ReplayOutput(root); var attempt = output.Begin(id, 123);
        OutputFixture.Fill(attempt.DirectoryPath, id);
        File.WriteAllBytes(Path.Combine(attempt.DirectoryPath, "player-1-normal.png"), OutputFixture.Png(4001, 4000));
        var exception = Assert.Throws<InvalidDataException>(() => output.Commit(attempt, 1, OutputFixture.Participants));
        Assert.Contains("bounded dimensions", exception.Message);
    }

    [Fact]
    public void LegacyPlayerIdCommitDoesNotGuessTribeMetadata()
    {
        var output = new ReplayOutput(root); var attempt = output.Begin(id, 123);
        Assert.Throws<InvalidDataException>(() => output.Commit(attempt, 1, new[] { 1, 7 }));
    }

    private static void Rewrite(string path, Func<string, string> transform) => File.WriteAllText(path, transform(File.ReadAllText(path)));
}

internal static class OutputFixture
{
    internal static ReplayParticipant[] Participants => new[]
    {
        new ReplayParticipant { Id = 1, TribeId = 2, SkinId = 0, TribeSkin = 1 },
        new ReplayParticipant { Id = 7, TribeId = 7, SkinId = 0, TribeSkin = 6 }
    };

    internal static void Fill(string directory, Guid replay, bool overlay = false, int target = 128)
    {
        int dimension = target * 4, center = dimension / 2;
        byte[] png = Png(dimension, dimension);
        foreach (int player in new[] { 1, 7 }) foreach (string view in new[] { "normal" })
        {
            string name = $"player-{player}-{view}", prefix = Path.Combine(directory, name);
            File.WriteAllBytes(prefix + ".png", png);
            if (overlay) File.WriteAllBytes(prefix + ".grid.png", png);
            File.WriteAllText(prefix + ".grid.json", JsonSerializer.Serialize(new { size = 1, width = dimension, height = dimension,
                anchor = new[] { center, center }, stepX = new[] { target, 0 }, stepY = new[] { 0, target },
                targetTilePixels = target, sideLengthPixels = target, otherSideLengthPixels = target }));
            var tile = new { x = 0, y = 0, fog = false, improvement = 0, resource = 0, terrain = 3, road = false,
                terrain_tribe_skin = 1, terrain_appearance = new { tribe_id = 2, skin_id = 0 },
                main_unit = new { type = 0, tribe_skin = 0, tribe_id = 0, skin_id = 0, color_rgb = new[] { 0, 0, 0 }, color_name = "none", hp = 0 },
                top_right_unit_icon = new { type = 0 } };
            File.WriteAllText(prefix + ".tiles.json", JsonSerializer.Serialize(new { schema_version = "1", replay_id = replay.ToString("D"),
                player_id = player, view, size = 1, grid_file = name + ".grid.json", mapping_version = AnnotationMapping.Version, tiles = new[] { tile } }));
        }
    }

    internal static byte[] Png(int width, int height)
    {
        using var result = new MemoryStream(); result.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        byte[] header = new byte[13]; BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(0, 4), width); BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(4, 4), height); header[8] = 8; header[9] = 2;
        Chunk("IHDR", header);
        using var packed = new MemoryStream();
        using (var zlib = new ZLibStream(packed, CompressionLevel.Fastest, true)) zlib.Write(new byte[(width * 3 + 1) * height]);
        Chunk("IDAT", packed.ToArray()); Chunk("IEND", Array.Empty<byte>()); return result.ToArray();
        void Chunk(string type, byte[] content)
        {
            byte[] length = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(length, content.Length); result.Write(length);
            byte[] typed = Encoding.ASCII.GetBytes(type).Concat(content).ToArray(); result.Write(typed);
            uint crc = uint.MaxValue;
            foreach (byte b in typed) { crc ^= b; for (int i = 0; i < 8; i++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0u); }
            BinaryPrimitives.WriteUInt32BigEndian(length, ~crc); result.Write(length);
        }
    }
}
