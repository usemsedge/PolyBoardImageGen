using System.Text.Json;
using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class LocalReplayTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "LocalReplayTests-" + Guid.NewGuid().ToString("N"));
    public LocalReplayTests() { Directory.CreateDirectory(directory); }
    public void Dispose() { Directory.Delete(directory, true); }

    [Theory]
    [InlineData("links")]
    [InlineData("gamestates")]
    public void SettingsAcceptBothModesAndResolveLocalDirectory(string mode)
    {
        string path = Path.Combine(directory, "settings.json");
        File.WriteAllText(path, JsonSerializer.Serialize(new { show_grid_overlay = false, num_iterations = 5,
            csv_filename = "queue.csv", input_mode = mode, gamestates_directory = "states" }));
        CaptureSettings settings = CaptureSettings.Load(path);
        Assert.Equal(mode, settings.InputMode);
        Assert.Equal(Path.Combine(directory, "states"), settings.GamestatesDirectory);
    }

    [Fact]
    public void SettingsRejectUnknownMode()
    {
        string path = Path.Combine(directory, "settings.json");
        File.WriteAllText(path, "{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\"q.csv\",\"input_mode\":\"invalid\"}");
        Assert.Throws<InvalidDataException>(() => CaptureSettings.Load(path));
    }

    [Theory]
    [InlineData(81)]
    [InlineData(123)]
    public void LoadsLocalFinalSnapshotWithoutAuthentication(int version)
    {
        Guid id = Guid.NewGuid();
        byte[] bytes = new byte[12];
        System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(0, 4), version);
        System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(4, 4), version);
        Write(id, id, 4, bytes);
        ReplaySnapshot result = ReplaySource.LoadLocal(id, directory);
        Assert.Equal(id, result.Id);
        Assert.Equal(version, result.Version);
        Assert.Equal(bytes, result.Bytes);
    }

    [Fact]
    public void RejectsMissingWrongIdentityUnfinishedAndMalformedSnapshots()
    {
        Guid id = Guid.NewGuid();
        Assert.Throws<FileNotFoundException>(() => ReplaySource.LoadLocal(id, directory));
        Write(id, Guid.NewGuid(), 4, new byte[12]);
        Assert.Throws<InvalidDataException>(() => ReplaySource.LoadLocal(id, directory));
        Write(id, id, 3, new byte[12]);
        Assert.Throws<InvalidDataException>(() => ReplaySource.LoadLocal(id, directory));
        Write(id, id, 4, new byte[3]);
        Assert.Throws<InvalidDataException>(() => ReplaySource.LoadLocal(id, directory));
        Write(id, id, 4, new byte[12]);
        Assert.Throws<InvalidDataException>(() => ReplaySource.LoadLocal(id, directory));
    }

    private void Write(Guid fileId, Guid payloadId, int state, byte[] bytes)
    {
        File.WriteAllText(Path.Combine(directory, fileId.ToString("D") + ".json"), JsonSerializer.Serialize(new {
            success = true, data = new { id = payloadId, state, currentGameStateData = Convert.ToBase64String(bytes) } }));
    }
}
