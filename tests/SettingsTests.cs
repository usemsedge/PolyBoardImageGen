using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class SettingsTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "SettingsTests-" + Guid.NewGuid().ToString("N"));
    public SettingsTests() { Directory.CreateDirectory(directory); }
    public void Dispose() { Directory.Delete(directory, true); }

    [Fact]
    public void RequiredSettingsResolveCsvRelativeToSettingsAndDefaultTarget()
    {
        string path = Settings("{\"show_grid_overlay\":true,\"num_iterations\":4,\"csv_filename\":\"queue.csv\"}");
        var settings = CaptureSettings.Load(path);
        Assert.True(settings.ShowGridOverlay);
        Assert.Equal(4, settings.NumIterations);
        Assert.Equal(128, settings.TargetTilePixels);
        Assert.Equal(Path.Combine(directory, "queue.csv"), settings.CsvFilename);
    }

    [Theory]
    [InlineData(32)]
    [InlineData(512)]
    public void AcceptsAbsoluteCsvAndTargetBoundaries(int target)
    {
        string csv = Path.Combine(Path.GetTempPath(), "input.csv");
        string json = System.Text.Json.JsonSerializer.Serialize(new { show_grid_overlay = false, num_iterations = 1, csv_filename = csv, target_tile_pixels = target });
        var settings = CaptureSettings.Load(Settings(json));
        Assert.Equal(csv, settings.CsvFilename);
        Assert.Equal(target, settings.TargetTilePixels);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("null")]
    [InlineData("{\"show_grid_overlay\":\"true\",\"num_iterations\":1,\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":0,\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":-1,\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1.5,\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":\"1\",\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\" \"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":null}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\"x.csv\",\"target_tile_pixels\":31}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\"x.csv\",\"target_tile_pixels\":513}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\"x.csv\",\"target_tile_pixels\":null}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"num_iterations\":2,\"csv_filename\":\"x.csv\"}")]
    [InlineData("{\"show_grid_overlay\":false,\"num_iterations\":1,\"csv_filename\":\"x.csv\",\"typo\":true}")]
    public void RejectsMissingMistypedOutOfRangeDuplicateAndUnknownFields(string json)
    {
        Assert.ThrowsAny<Exception>(() => CaptureSettings.Load(Settings(json)));
    }

    [Fact]
    public void MissingAndMalformedSettingsStopTheRun()
    {
        Assert.Throws<FileNotFoundException>(() => CaptureSettings.Load(Path.Combine(directory, "missing.json")));
        Assert.ThrowsAny<System.Text.Json.JsonException>(() => CaptureSettings.Load(Settings("{")));
    }

    private string Settings(string json)
    {
        string path = Path.Combine(directory, "settings.json"); File.WriteAllText(path, json); return path;
    }
}
